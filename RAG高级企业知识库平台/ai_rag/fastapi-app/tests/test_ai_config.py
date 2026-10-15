"""AI 模型配置与 Prompt 模板接口测试。

连通性测试要真实调百炼接口，需要有效的 API Key，这里只覆盖没填 Key 时的失败路径，
填了 Key 之后的成功路径在页面上手工验证。
"""

CONFIG_NAME = "测试模型配置-单元测试专用"
TEMPLATE_CODE = "TEST_TEMPLATE_UNIT"


def _cleanup_config(client, admin_headers):
    page = client.get(
        "/aiModelConfig/selectPage",
        params={"name": CONFIG_NAME, "page_num": 1, "page_size": 10},
        headers=admin_headers,
    ).json()
    for item in page["data"]["list"]:
        if item["name"] == CONFIG_NAME:
            client.delete(f"/aiModelConfig/delete/{item['id']}", headers=admin_headers)


def _find_config(client, admin_headers):
    page = client.get(
        "/aiModelConfig/selectPage",
        params={"name": CONFIG_NAME, "page_num": 1, "page_size": 10},
        headers=admin_headers,
    ).json()
    for item in page["data"]["list"]:
        if item["name"] == CONFIG_NAME:
            return item
    return None


def _cleanup_template(client, admin_headers):
    page = client.get(
        "/promptTemplate/selectAll", headers=admin_headers
    ).json()
    for item in page["data"]:
        if item["code"] == TEMPLATE_CODE:
            client.delete(f"/promptTemplate/delete/{item['id']}", headers=admin_headers)


def test_seed_configs_cover_three_model_types(client, admin_headers):
    """初始化数据里三类模型各有一条启用的配置。"""
    body = client.get("/aiModelConfig/selectAll", headers=admin_headers).json()
    enabled = {item["model_type"]: item for item in body["data"] if item["enabled"] == "是"}
    assert set(enabled.keys()) == {"对话模型", "向量模型", "重排模型"}
    # 重排在百炼没有 OpenAI 兼容接口，协议必须是原生
    assert enabled["重排模型"]["protocol"] == "DashScope原生"
    assert enabled["对话模型"]["protocol"] == "OpenAI兼容"
    # 向量维度要和 PGVector 建表时的 vector(1024) 一致
    assert enabled["向量模型"]["dimension"] == 1024


def test_api_key_is_masked_in_list(client, admin_headers):
    """列表接口返回的密钥是脱敏的，不会把整串密钥发到前端。"""
    _cleanup_config(client, admin_headers)
    client.post(
        "/aiModelConfig/add",
        json={
            "name": CONFIG_NAME,
            "model_type": "对话模型",
            "protocol": "OpenAI兼容",
            "base_url": "https://dashscope.aliyuncs.com/compatible-mode/v1",
            "api_key": "sk-abcdefghijklmnop",
            "model_name": "qwen-plus",
        },
        headers=admin_headers,
    )
    created = _find_config(client, admin_headers)
    assert created["api_key"] == "sk-a" + "*" * 8 + "mnop"

    _cleanup_config(client, admin_headers)


def test_embedding_requires_dimension(client, admin_headers):
    """向量模型必须填维度。"""
    body = client.post(
        "/aiModelConfig/add",
        json={
            "name": CONFIG_NAME,
            "model_type": "向量模型",
            "protocol": "OpenAI兼容",
            "base_url": "https://dashscope.aliyuncs.com/compatible-mode/v1",
            "model_name": "text-embedding-v4",
        },
        headers=admin_headers,
    ).json()
    assert body["code"] == "500"
    assert body["msg"] == "向量模型必须填写向量维度"


def test_only_one_enabled_per_model_type(client, admin_headers):
    """同一类型下只允许一条启用，新启用一条会把原来那条停掉。"""
    _cleanup_config(client, admin_headers)
    before = client.get("/aiModelConfig/selectAll", params={"model_type": "对话模型"}, headers=admin_headers).json()
    old_enabled = [item for item in before["data"] if item["enabled"] == "是"][0]

    client.post(
        "/aiModelConfig/add",
        json={
            "name": CONFIG_NAME,
            "model_type": "对话模型",
            "protocol": "OpenAI兼容",
            "base_url": "https://dashscope.aliyuncs.com/compatible-mode/v1",
            "api_key": "sk-test",
            "model_name": "qwen-max",
            "enabled": "是",
        },
        headers=admin_headers,
    )
    after = client.get("/aiModelConfig/selectAll", params={"model_type": "对话模型"}, headers=admin_headers).json()
    enabled = [item for item in after["data"] if item["enabled"] == "是"]
    assert len(enabled) == 1
    assert enabled[0]["name"] == CONFIG_NAME

    # 复原：把原来那条重新启用，再删掉测试配置
    client.put(
        "/aiModelConfig/update",
        json={
            "id": old_enabled["id"],
            "name": old_enabled["name"],
            "model_type": old_enabled["model_type"],
            "protocol": old_enabled["protocol"],
            "base_url": old_enabled["base_url"],
            "model_name": old_enabled["model_name"],
            "enabled": "是",
        },
        headers=admin_headers,
    )
    _cleanup_config(client, admin_headers)


def test_enabled_config_cannot_be_deleted(client, admin_headers):
    """启用中的配置不允许删除。"""
    configs = client.get("/aiModelConfig/selectAll", headers=admin_headers).json()
    enabled = [item for item in configs["data"] if item["enabled"] == "是"][0]

    body = client.delete(f"/aiModelConfig/delete/{enabled['id']}", headers=admin_headers).json()
    assert body["code"] == "500"
    assert body["msg"] == "启用中的配置不能删除，请先启用同类型的另一条"


def test_masked_key_does_not_overwrite_real_key(client, admin_headers):
    """编辑时不改密钥，脱敏串不会把真密钥覆盖掉。"""
    _cleanup_config(client, admin_headers)
    client.post(
        "/aiModelConfig/add",
        json={
            "name": CONFIG_NAME,
            "model_type": "对话模型",
            "protocol": "OpenAI兼容",
            "base_url": "https://dashscope.aliyuncs.com/compatible-mode/v1",
            "api_key": "sk-abcdefghijklmnop",
            "model_name": "qwen-plus",
        },
        headers=admin_headers,
    )
    created = _find_config(client, admin_headers)

    # 把列表里拿到的脱敏串原样提交回去，模拟用户只改了别的字段
    client.put(
        "/aiModelConfig/update",
        json={
            "id": created["id"],
            "name": CONFIG_NAME,
            "model_type": "对话模型",
            "protocol": "OpenAI兼容",
            "base_url": "https://dashscope.aliyuncs.com/compatible-mode/v1",
            "api_key": created["api_key"],
            "model_name": "qwen-max",
        },
        headers=admin_headers,
    )
    after = _find_config(client, admin_headers)
    # 密钥没被脱敏串覆盖，脱敏结果还是原来那串的头尾
    assert after["api_key"] == "sk-a" + "*" * 8 + "mnop"
    assert after["model_name"] == "qwen-max"

    _cleanup_config(client, admin_headers)


def test_test_connection_without_key_is_rejected(client, admin_headers):
    """没填 API Key 时连通性测试给出人话提示。"""
    _cleanup_config(client, admin_headers)
    client.post(
        "/aiModelConfig/add",
        json={
            "name": CONFIG_NAME,
            "model_type": "对话模型",
            "protocol": "OpenAI兼容",
            "base_url": "https://dashscope.aliyuncs.com/compatible-mode/v1",
            "model_name": "qwen-plus",
        },
        headers=admin_headers,
    )
    created = _find_config(client, admin_headers)

    body = client.post(f"/aiModelConfig/test/{created['id']}", headers=admin_headers).json()
    assert body["code"] == "500"
    assert body["msg"] == "请先填写 API Key"

    _cleanup_config(client, admin_headers)


def test_seed_prompt_templates_exist(client, admin_headers):
    """初始化数据里预置了五条 Prompt 模板。"""
    body = client.get("/promptTemplate/selectAll", headers=admin_headers).json()
    codes = {item["code"] for item in body["data"]}
    assert {"RAG_ANSWER", "QUERY_REWRITE", "CONTEXT_GRADE", "HALLUCINATION_CHECK", "EVAL_CASE_GEN"} <= codes


def test_variables_are_extracted_from_content(client, admin_headers):
    """保存时从模板内容里自动抽出变量清单。"""
    _cleanup_template(client, admin_headers)
    client.post(
        "/promptTemplate/add",
        json={
            "code": TEMPLATE_CODE,
            "name": "单元测试模板",
            "scene": "问答生成",
            "content": "资料：{context}\n问题：{question}\n再提一次问题：{question}",
        },
        headers=admin_headers,
    )
    body = client.get("/promptTemplate/selectAll", headers=admin_headers).json()
    created = [item for item in body["data"] if item["code"] == TEMPLATE_CODE][0]
    # 重复出现的变量只记一次，顺序和模板里一致
    assert created["variables"] == "context,question"

    _cleanup_template(client, admin_headers)


def test_preview_renders_variables(client, admin_headers):
    """预览把变量值填进模板，返回真正发给模型的文本。"""
    _cleanup_template(client, admin_headers)
    client.post(
        "/promptTemplate/add",
        json={
            "code": TEMPLATE_CODE,
            "name": "单元测试模板",
            "content": "资料：{context}\n问题：{question}",
        },
        headers=admin_headers,
    )
    body = client.get("/promptTemplate/selectAll", headers=admin_headers).json()
    created = [item for item in body["data"] if item["code"] == TEMPLATE_CODE][0]

    preview = client.post(
        "/promptTemplate/preview",
        json={"id": created["id"], "values": {"context": "质保 24 个月", "question": "保修期多久"}},
        headers=admin_headers,
    ).json()
    assert preview["code"] == "200"
    assert preview["data"] == "资料：质保 24 个月\n问题：保修期多久"

    _cleanup_template(client, admin_headers)


def test_preview_missing_variable_is_rejected(client, admin_headers):
    """变量没填全时明确指出缺哪个。"""
    _cleanup_template(client, admin_headers)
    client.post(
        "/promptTemplate/add",
        json={
            "code": TEMPLATE_CODE,
            "name": "单元测试模板",
            "content": "资料：{context}\n问题：{question}",
        },
        headers=admin_headers,
    )
    body = client.get("/promptTemplate/selectAll", headers=admin_headers).json()
    created = [item for item in body["data"] if item["code"] == TEMPLATE_CODE][0]

    preview = client.post(
        "/promptTemplate/preview",
        json={"id": created["id"], "values": {"context": "质保 24 个月"}},
        headers=admin_headers,
    ).json()
    assert preview["code"] == "500"
    assert preview["msg"] == f"Prompt 模板 {TEMPLATE_CODE} 缺少变量：question"

    _cleanup_template(client, admin_headers)


def test_duplicated_template_code_is_rejected(client, admin_headers):
    """模板编码不允许重复。"""
    _cleanup_template(client, admin_headers)
    payload = {
        "code": TEMPLATE_CODE,
        "name": "单元测试模板",
        "content": "内容 {context}",
    }
    client.post("/promptTemplate/add", json=payload, headers=admin_headers)
    body = client.post("/promptTemplate/add", json=payload, headers=admin_headers).json()
    assert body["code"] == "500"
    assert body["msg"] == "模板编码重复"

    _cleanup_template(client, admin_headers)
