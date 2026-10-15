"""检索策略管理与调试台测试。

策略 CRUD 全部可以直接测；调试台的对比接口要真实跑检索，
这里只覆盖参数校验和存档相关的路径。
"""

STRATEGY_NAME = "测试检索策略-单元测试专用"


def _cleanup(client, admin_headers):
    page = client.get(
        "/retrievalStrategy/selectPage",
        params={"name": STRATEGY_NAME, "page_num": 1, "page_size": 10},
        headers=admin_headers,
    ).json()
    for item in page["data"]["list"]:
        if item["name"] == STRATEGY_NAME:
            client.delete(f"/retrievalStrategy/delete/{item['id']}", headers=admin_headers)


def _payload(**overrides):
    payload = {
        "name": STRATEGY_NAME,
        "vector_enabled": "是",
        "vector_top_k": 5,
        "bm25_enabled": "否",
        "bm25_top_k": 0,
        "rrf_k": 60,
        "rerank_enabled": "否",
        "rerank_top_n": 3,
        "query_rewrite_enabled": "否",
        "multi_query_count": 3,
        "parent_recall_enabled": "否",
        "vector_score_threshold": 0.3,
        "rerank_score_threshold": 0.05,
        "is_default": "否",
    }
    payload.update(overrides)
    return payload


def test_both_recalls_disabled_is_rejected(client, admin_headers):
    """两路检索都关掉时这套策略没法执行，直接拦住。"""
    body = client.post(
        "/retrievalStrategy/add",
        json=_payload(vector_enabled="否", bm25_enabled="否"),
        headers=admin_headers,
    ).json()
    assert body["code"] == "500"
    assert body["msg"] == "向量检索和 BM25 检索至少要启用一个"


def test_rewrite_without_type_is_rejected(client, admin_headers):
    """启用查询改写但没选改写方式时拦住。"""
    body = client.post(
        "/retrievalStrategy/add",
        json=_payload(query_rewrite_enabled="是"),
        headers=admin_headers,
    ).json()
    assert body["code"] == "500"
    assert body["msg"] == "启用查询改写时必须选择改写方式"


def test_rerank_top_n_must_be_positive(client, admin_headers):
    """启用重排时保留条数必须大于 0。"""
    body = client.post(
        "/retrievalStrategy/add",
        json=_payload(rerank_enabled="是", rerank_top_n=0),
        headers=admin_headers,
    ).json()
    assert body["code"] == "500"
    assert body["msg"] == "启用重排时保留条数必须大于 0"


def test_vector_threshold_range_is_checked(client, admin_headers):
    """余弦相似度阈值必须在 0 到 1 之间。"""
    body = client.post(
        "/retrievalStrategy/add",
        json=_payload(vector_score_threshold=1.5),
        headers=admin_headers,
    ).json()
    assert body["code"] == "500"
    assert body["msg"] == "余弦相似度阈值取值范围是 0 到 1"


def test_rerank_threshold_range_is_checked(client, admin_headers):
    """重排相关分阈值单独校验，报错要指名是哪一个阈值填错了。"""
    body = client.post(
        "/retrievalStrategy/add",
        json=_payload(rerank_score_threshold=1.5),
        headers=admin_headers,
    ).json()
    assert body["code"] == "500"
    assert body["msg"] == "重排相关分阈值取值范围是 0 到 1"


def test_two_thresholds_are_stored_separately(client, admin_headers):
    """两个阈值分开存，互不覆盖。

    余弦相似度和重排相关分是两种量纲，实测相关片段一个落在 0.46~0.77、
    另一个落在 0.14~0.20，同一个数字放在两边含义完全不同，所以必须分开存。
    """
    _cleanup(client, admin_headers)
    client.post(
        "/retrievalStrategy/add",
        json=_payload(vector_score_threshold=0.3, rerank_score_threshold=0.05),
        headers=admin_headers,
    )
    page = client.get(
        "/retrievalStrategy/selectPage",
        params={"name": STRATEGY_NAME, "page_num": 1, "page_size": 10},
        headers=admin_headers,
    ).json()
    saved = page["data"]["list"][0]
    assert saved["vector_score_threshold"] == 0.3
    assert saved["rerank_score_threshold"] == 0.05
    _cleanup(client, admin_headers)


def test_rewrite_type_is_cleared_when_disabled(client, admin_headers):
    """关掉改写时改写方式一起清掉，不留下不生效的残值。"""
    _cleanup(client, admin_headers)
    client.post(
        "/retrievalStrategy/add",
        json=_payload(query_rewrite_enabled="是", rewrite_type="多查询扩展"),
        headers=admin_headers,
    )
    page = client.get(
        "/retrievalStrategy/selectPage",
        params={"name": STRATEGY_NAME, "page_num": 1, "page_size": 10},
        headers=admin_headers,
    ).json()
    created = page["data"]["list"][0]
    assert created["rewrite_type"] == "多查询扩展"

    client.put(
        "/retrievalStrategy/update",
        json=_payload(id=created["id"], query_rewrite_enabled="否", rewrite_type="多查询扩展"),
        headers=admin_headers,
    )
    page = client.get(
        "/retrievalStrategy/selectPage",
        params={"name": STRATEGY_NAME, "page_num": 1, "page_size": 10},
        headers=admin_headers,
    ).json()
    assert page["data"]["list"][0]["rewrite_type"] is None

    _cleanup(client, admin_headers)


def test_only_one_default_strategy(client, admin_headers):
    """新增一条默认策略后原来的默认标记被清掉。"""
    _cleanup(client, admin_headers)
    before = client.get("/retrieval/strategies", headers=admin_headers).json()
    old_default = [item for item in before["data"] if item["is_default"] == "是"][0]

    client.post("/retrievalStrategy/add", json=_payload(is_default="是"), headers=admin_headers)
    after = client.get("/retrieval/strategies", headers=admin_headers).json()
    defaults = [item for item in after["data"] if item["is_default"] == "是"]
    assert len(defaults) == 1
    assert defaults[0]["name"] == STRATEGY_NAME

    # 复原。更新接口是整行覆盖：没传的字段一律按默认值写回去，
    # 所以这里要把原来那行原样传回，只改 is_default，
    # 只传几个字段的话会把这条策略的召回条数、阈值等配置一起抹掉
    restore = dict(old_default)
    restore["is_default"] = "是"
    client.put("/retrievalStrategy/update", json=restore, headers=admin_headers)

    # 确认复原到位，配置没有在这条用例里被顺手清掉
    restored = client.get("/retrieval/strategies", headers=admin_headers).json()
    same = [item for item in restored["data"] if item["id"] == old_default["id"]][0]
    assert same["vector_top_k"] == old_default["vector_top_k"]
    assert same["vector_score_threshold"] == old_default["vector_score_threshold"]
    _cleanup(client, admin_headers)


def test_default_strategy_cannot_be_deleted(client, admin_headers):
    """默认策略不允许删除。"""
    strategies = client.get("/retrieval/strategies", headers=admin_headers).json()
    default = [item for item in strategies["data"] if item["is_default"] == "是"][0]
    body = client.delete(f"/retrievalStrategy/delete/{default['id']}", headers=admin_headers).json()
    assert body["code"] == "500"
    assert body["msg"] == "默认策略不能删除，请先把其他策略设为默认"


def test_compare_requires_strategies(client, admin_headers):
    """一套策略都不选时给出人话提示。"""
    body = client.post(
        "/retrievalStrategy/compare",
        json={"kb_ids": [1], "strategy_ids": [], "query": "保修期"},
        headers=admin_headers,
    ).json()
    assert body["code"] == "500"
    assert body["msg"] == "请至少选择一套检索策略"


def test_compare_limits_strategy_count(client, admin_headers):
    """一次最多对比四套策略。"""
    body = client.post(
        "/retrievalStrategy/compare",
        json={"kb_ids": [1], "strategy_ids": [1, 2, 3, 1, 2], "query": "保修期"},
        headers=admin_headers,
    ).json()
    assert body["code"] == "500"
    assert body["msg"] == "一次最多对比 4 套策略"


def test_records_list_is_available(client, admin_headers):
    """调试记录列表接口可用，且不返回快照正文。"""
    body = client.get(
        "/retrievalStrategy/records",
        params={"page_num": 1, "page_size": 5},
        headers=admin_headers,
    ).json()
    assert body["code"] == "200"
    for item in body["data"]["list"]:
        assert "result_snapshot" not in item


def test_chunk_type_summary(client, admin_headers):
    """片段类型分布接口返回三种类型的条数。"""
    body = client.get("/retrievalStrategy/chunkTypes/1", headers=admin_headers).json()
    assert body["code"] == "200"
    assert set(body["data"].keys()) == {"plain", "child", "parent"}
