"""检索测试。

BM25 和 RRF 都是纯 Python 计算，不依赖向量库和模型，可以直接测。
向量检索那一路要连 PGVector 并调向量模型，放在页面上手工验证。
"""

from ai import retriever
from service import retrieval_service

CHUNKS = [
    {"chunk_id": 1, "content": "GTE-3000 系列工控机质保时长为 24 个月，质保期内非人为损坏免费维修。"},
    {"chunk_id": 2, "content": "退款审核通过后 3 到 5 个工作日原路退回到付款账户。"},
    {"chunk_id": 3, "content": "本产品支持私有化部署，可交付于客户自有服务器环境。"},
    {"chunk_id": 4, "content": "售后服务承诺：工作日 9 点到 18 点提供技术支持。"},
]


def test_tokenize_splits_model_number():
    """分词把型号里的数字单独切出来，这正是关键词检索能认出型号的原因。"""
    tokens = retriever.tokenize("GTE-3000 保修多久")
    assert "3000" in tokens
    assert "gte" in tokens
    # 停用词被丢掉，不参与打分
    assert "的" not in tokens


def test_bm25_finds_exact_model_number():
    """向量检索认不出的型号，BM25 能精确命中。"""
    results = retriever.bm25_search("GTE3000 保修", CHUNKS, top_k=3)
    assert results
    assert results[0]["chunk_id"] == 1
    # 每条结果都标出自己来自哪一路
    assert results[0]["source"] == "BM25检索"


def test_bm25_returns_nothing_when_no_word_matches():
    """一个词都对不上时 BM25 不硬凑结果。"""
    results = retriever.bm25_search("量子计算机租赁价格", CHUNKS, top_k=3)
    assert results == []


def test_bm25_ignores_zero_score_items():
    """得分为 0 的候选不进结果，避免用无关片段把 TopK 占满。"""
    results = retriever.bm25_search("退款", CHUNKS, top_k=4)
    assert len(results) < len(CHUNKS)
    assert all(item["score"] > 0 for item in results)


def test_rrf_ranks_item_hit_by_both_rankings_first():
    """两路都召回的结果排在只有一路召回的前面。"""
    vector_ranking = [
        {"chunk_id": 2, "content": "b", "source": "向量检索"},
        {"chunk_id": 1, "content": "a", "source": "向量检索"},
    ]
    bm25_ranking = [
        {"chunk_id": 3, "content": "c", "source": "BM25检索"},
        {"chunk_id": 1, "content": "a", "source": "BM25检索"},
    ]
    fused = retriever.rrf_fuse([vector_ranking, bm25_ranking], k=60, top_k=5)
    # 1 号在两路都排第 2，累加后超过了各自只排第 1 的 2 号和 3 号
    assert fused[0]["chunk_id"] == 1
    # 来源标出被哪几路召回
    assert fused[0]["source"] == "BM25检索+向量检索"


def test_rrf_dedupes_by_chunk_id():
    """同一条片段被两路召回时只保留一条。"""
    ranking_one = [{"chunk_id": 7, "content": "x", "source": "向量检索"}]
    ranking_two = [{"chunk_id": 7, "content": "x", "source": "BM25检索"}]
    fused = retriever.rrf_fuse([ranking_one, ranking_two], k=60, top_k=5)
    assert len(fused) == 1


def test_rrf_smaller_k_widens_gap_between_ranks():
    """k 越小，相邻名次之间的分数差距越大。"""
    ranking = [
        {"chunk_id": 1, "content": "a", "source": "向量检索"},
        {"chunk_id": 2, "content": "b", "source": "向量检索"},
    ]
    with_large_k = retriever.rrf_fuse([ranking], k=60, top_k=5)
    with_small_k = retriever.rrf_fuse([ranking], k=1, top_k=5)
    large_gap = with_large_k[0]["score"] - with_large_k[1]["score"]
    small_gap = with_small_k[0]["score"] - with_small_k[1]["score"]
    assert small_gap > large_gap


def test_rrf_respects_top_k():
    """融合结果按 top_k 截断。"""
    ranking = [{"chunk_id": index, "content": "x", "source": "向量检索"} for index in range(1, 11)]
    fused = retriever.rrf_fuse([ranking], k=60, top_k=3)
    assert len(fused) == 3


def test_seed_retrieval_strategies(client, admin_headers):
    """初始化数据里预置了三套检索策略，覆盖基线到完整三档。"""
    body = client.get("/retrieval/strategies", headers=admin_headers).json()
    assert body["code"] == "200"
    names = {item["name"]: item for item in body["data"]}
    baseline = names["基线-纯向量检索"]
    hybrid = names["进阶-混合检索"]
    # 基线只开向量，是第 13 章说的基础 RAG
    assert baseline["vector_enabled"] == "是"
    assert baseline["bm25_enabled"] == "否"
    assert baseline["is_default"] == "是"
    # 进阶把 BM25 也打开，两路 RRF 融合
    assert hybrid["vector_enabled"] == "是"
    assert hybrid["bm25_enabled"] == "是"
    assert hybrid["rrf_k"] == 60


def test_search_without_kb_is_rejected(client, admin_headers):
    """一个知识库都不选时给出人话提示。"""
    body = client.post(
        "/retrieval/search",
        json={"kb_ids": [], "query": "保修期多久"},
        headers=admin_headers,
    ).json()
    assert body["code"] == "500"
    assert body["msg"] == "请选择知识库"


def test_search_without_query_is_rejected(client, admin_headers):
    """问题为空时给出人话提示。"""
    body = client.post(
        "/retrieval/search",
        json={"kb_ids": [1], "query": "   "},
        headers=admin_headers,
    ).json()
    assert body["code"] == "500"
    assert body["msg"] == "请输入检索问题"

def test_rrf_scores_are_not_similarity_scale():
    """RRF 融合后的分数是名次倒数，和余弦相似度不是一个量纲。

    RRF 的分数是 1/(k+名次)，rrf_k=60 时最高也只有 1/61 约等于 0.016，
    而余弦相似度下相关片段实测在 0.46 到 0.77。
    这条用例把量纲差异钉住，它是阈值必须按量纲分开配的前提。
    """
    vector_ranking = [
        {"chunk_id": 1, "content": "内容一", "score": 0.82, "source": "向量检索"},
        {"chunk_id": 2, "content": "内容二", "score": 0.75, "source": "向量检索"},
    ]
    bm25_ranking = [
        {"chunk_id": 1, "content": "内容一", "score": 6.4, "source": "BM25检索"},
        {"chunk_id": 3, "content": "内容三", "score": 3.1, "source": "BM25检索"},
    ]

    fused = retriever.rrf_fuse([vector_ranking, bm25_ranking], k=60, top_k=5)

    assert fused
    # 融合后每条的分数都远小于策略里 0.3 的相似度阈值
    assert all(item["score"] < 0.05 for item in fused)
    # 两路都命中的那条仍然排第一，说明排序本身是对的，只是分数换了量纲
    assert fused[0]["chunk_id"] == 1


# 一组假的召回结果，分数按余弦相似度的量纲给
COSINE_RESULTS = [
    {"chunk_id": 1, "content": "内容一", "score": 0.62},
    {"chunk_id": 2, "content": "内容二", "score": 0.25},
]
# 同样两条，分数换成重排相关分的量纲。实测这个量纲下相关片段只有 0.14~0.20
RERANK_RESULTS = [
    {"chunk_id": 1, "content": "内容一", "score": 0.19},
    {"chunk_id": 2, "content": "内容二", "score": 0.006},
]
# 两种阈值各按自己量纲的实测区间标定
STRATEGY = {"vector_score_threshold": 0.3, "rerank_score_threshold": 0.05}


def test_threshold_uses_vector_field_for_cosine_scale():
    """量纲是余弦相似度时，比的是向量阈值。"""
    kept, stage = retrieval_service.apply_score_threshold(
        COSINE_RESULTS, retrieval_service.SCALE_COSINE, STRATEGY
    )
    # 0.62 留下，0.25 低于 0.3 被丢掉
    assert [item["chunk_id"] for item in kept] == [1]
    assert "0.3" in stage["name"]
    assert retrieval_service.SCALE_COSINE in stage["name"]


def test_threshold_uses_rerank_field_for_rerank_scale():
    """量纲是重排相关分时，比的是重排阈值，不是向量那个 0.3。

    这条用例钉住的就是最初的故障：重排分实测最高只有 0.2 上下，
    拿余弦那套 0.3 的门槛去卡，一条都留不下来。
    """
    kept, stage = retrieval_service.apply_score_threshold(
        RERANK_RESULTS, retrieval_service.SCALE_RERANK, STRATEGY
    )
    # 0.19 是相关片段，必须留下；0.006 是完全无关的量级，该丢
    assert [item["chunk_id"] for item in kept] == [1]
    assert "0.05" in stage["name"]
    # 换成向量那个阈值的话，0.19 会被误杀
    assert STRATEGY["vector_score_threshold"] > RERANK_RESULTS[0]["score"]


def test_threshold_is_skipped_for_rrf_scale_but_leaves_a_trace():
    """RRF 名次分不支持阈值，这一步跳过，但必须在阶段表里留痕。

    静默跳过会让页面上那个阈值框看起来生效了、其实一直空转，
    所以跳过也要产出一行阶段记录说明原因。
    """
    fused_results = [{"chunk_id": 1, "content": "内容一", "score": 0.0328}]
    kept, stage = retrieval_service.apply_score_threshold(
        fused_results, retrieval_service.SCALE_RRF, STRATEGY
    )
    # 一条都不该被过滤掉
    assert kept == fused_results
    assert stage is not None
    assert "不适用" in stage["name"]


def test_threshold_explains_why_everything_was_filtered_out():
    """结果被阈值全部砍光时，阶段明细要说清是阈值卡的，而不是让人去查知识库。"""
    low_results = [{"chunk_id": 1, "content": "内容一", "score": 0.006}]
    kept, stage = retrieval_service.apply_score_threshold(
        low_results, retrieval_service.SCALE_RERANK, STRATEGY
    )
    assert kept == []
    # 明细里要出现本次最高分和门槛，页面据此提示调阈值
    assert any("0.0060" in line and "0.05" in line for line in stage["detail"])


def test_threshold_does_nothing_when_that_scale_has_no_value():
    """量纲支持阈值但这一档没填时，不过滤也不记阶段。"""
    kept, stage = retrieval_service.apply_score_threshold(
        COSINE_RESULTS, retrieval_service.SCALE_COSINE, {"rerank_score_threshold": 0.05}
    )
    assert kept == COSINE_RESULTS
    assert stage is None


def test_predict_score_scale_covers_every_switch_combination():
    """按开关组合推算量纲的规则只有这一份，页面通过接口取，不在前端重写。

    这条用例把四种走向都钉住，改检索管线时对着它就能看出预测是不是跟着变了。
    """
    predict = retrieval_service.predict_score_scale

    # 只开向量、不开改写：单路单查询，分数就是余弦相似度
    assert predict({"vector_enabled": "是"}) == retrieval_service.SCALE_COSINE
    # 只开 BM25：分数是 BM25 打的分，没有上界
    assert predict({"bm25_enabled": "是"}) == retrieval_service.SCALE_BM25
    # 两路都开：两份榜单要融合
    assert (
        predict({"vector_enabled": "是", "bm25_enabled": "是"})
        == retrieval_service.SCALE_RRF
    )
    # 开了重排：最后一步是重排打分，前面走没走融合都不影响
    assert (
        predict({"vector_enabled": "是", "bm25_enabled": "是", "rerank_enabled": "是"})
        == retrieval_service.SCALE_RERANK
    )


def test_predict_score_scale_counts_multi_query_rankings():
    """多查询扩展会让单路也凑出多份榜单，同样要走 RRF 融合。

    只看"开了几路"会漏掉这种情况，把只开向量的策略错判成余弦相似度。
    """
    predict = retrieval_service.predict_score_scale

    multi = {
        "vector_enabled": "是",
        "query_rewrite_enabled": "是",
        "rewrite_type": "多查询扩展",
        "multi_query_count": 3,
    }
    assert predict(multi) == retrieval_service.SCALE_RRF

    # 指代消解和 HyDE 只产出一条查询，榜单还是一份，量纲不变
    for rewrite_type in ("指代消解", "HyDE"):
        one = dict(multi, rewrite_type=rewrite_type)
        assert predict(one) == retrieval_service.SCALE_COSINE
