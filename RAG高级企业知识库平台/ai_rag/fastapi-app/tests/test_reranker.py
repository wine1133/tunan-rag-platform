"""重排组件测试。

真实调用百炼的重排接口需要 API Key，这里把 model_factory.rerank 换成假实现，
验证的是本项目自己写的那部分：结果转换、按接口返回的顺序重排、分数和来源覆盖。
"""

import pytest

from ai import model_factory, reranker
from common.exception_handler import CustomException
from models import AiModelConfig

RESULTS = [
    {"chunk_id": 11, "content": "退换货政策总则", "score": 0.81, "source": "向量检索", "document_id": 1},
    {"chunk_id": 12, "content": "售后服务承诺", "score": 0.79, "source": "向量检索", "document_id": 1},
    {"chunk_id": 13, "content": "退款审核通过后 3 到 5 个工作日原路退回", "score": 0.72, "source": "BM25检索", "document_id": 2},
]


def _fake_config() -> AiModelConfig:
    # 不入库，只构造一个内存对象给组件用
    return AiModelConfig(
        id=999,
        name="测试重排配置",
        model_type="重排模型",
        protocol="DashScope原生",
        base_url="https://example.com/api/v1",
        api_key="sk-test",
        model_name="gte-rerank-v2",
    )


def test_to_documents_keeps_metadata():
    """转成 Document 时正文进 page_content，其余字段进 metadata。"""
    documents = reranker.to_documents(RESULTS)
    assert documents[0].page_content == "退换货政策总则"
    assert documents[0].metadata["chunk_id"] == 11
    assert documents[0].metadata["source"] == "向量检索"
    # 正文不重复放进 metadata
    assert "content" not in documents[0].metadata


@pytest.mark.asyncio
async def test_rerank_reorders_by_interface_result(monkeypatch):
    """按重排接口返回的顺序重新排列，真正的答案排到第一位。"""

    async def fake_rerank(config, query, documents, top_n):
        # 接口返回的 index 指向传进去的 documents 列表
        return [
            {"index": 2, "relevance_score": 0.93},
            {"index": 0, "relevance_score": 0.41},
        ]

    monkeypatch.setattr(model_factory, "rerank", fake_rerank)

    compressor = reranker.DashScopeRerank(config=_fake_config(), top_n=2)
    documents = reranker.to_documents(RESULTS)
    ranked = await compressor.acompress_documents(documents, "退款多久到账")
    results = reranker.from_documents(ranked)

    # 粗筛里排第 3 的那条被重排提到了第 1
    assert results[0]["chunk_id"] == 13
    assert len(results) == 2
    # 分数换成了重排给的相关性得分
    assert results[0]["score"] == 0.93
    # 来源保留粗筛那一路并标上经过重排
    assert results[0]["source"] == "BM25检索→重排"


@pytest.mark.asyncio
async def test_rerank_ignores_out_of_range_index(monkeypatch):
    """接口返回越界下标时跳过，不让它把整次检索带崩。"""

    async def fake_rerank(config, query, documents, top_n):
        return [
            {"index": 99, "relevance_score": 0.99},
            {"index": 1, "relevance_score": 0.55},
        ]

    monkeypatch.setattr(model_factory, "rerank", fake_rerank)

    compressor = reranker.DashScopeRerank(config=_fake_config(), top_n=2)
    ranked = await compressor.acompress_documents(reranker.to_documents(RESULTS), "问题")
    results = reranker.from_documents(ranked)

    assert len(results) == 1
    assert results[0]["chunk_id"] == 12


@pytest.mark.asyncio
async def test_rerank_empty_result_is_rejected(monkeypatch):
    """接口一条都没返回时给出人话提示。"""

    async def fake_rerank(config, query, documents, top_n):
        return []

    monkeypatch.setattr(model_factory, "rerank", fake_rerank)

    compressor = reranker.DashScopeRerank(config=_fake_config(), top_n=2)
    with pytest.raises(CustomException) as excinfo:
        await compressor.acompress_documents(reranker.to_documents(RESULTS), "问题")
    assert excinfo.value.message == "重排接口没有返回结果，请检查重排模型配置"


@pytest.mark.asyncio
async def test_rerank_empty_documents_returns_empty():
    """没有候选文档时不调接口，直接返回空。"""
    compressor = reranker.DashScopeRerank(config=_fake_config(), top_n=3)
    assert await compressor.acompress_documents([], "问题") == []


def test_sync_interface_is_not_supported():
    """同步接口明确报错，避免有人误用同步路径。"""
    compressor = reranker.DashScopeRerank(config=_fake_config(), top_n=3)
    with pytest.raises(NotImplementedError):
        compressor.compress_documents(reranker.to_documents(RESULTS), "问题")
