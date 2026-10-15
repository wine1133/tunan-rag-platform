"""父块回填与阈值过滤测试。

回填要读 MySQL 里的父块，所以建了真实的知识库、文档和父子片段；
不依赖向量库和模型，回填逻辑本身可以直接测。
"""

import pytest

from models import KnowledgeBase, KnowledgeChunk, KnowledgeDocument
from service import retrieval_service

KB_NAME = "测试回填库-单元测试专用"


@pytest.fixture()
async def parent_child(db):
    """造一篇文档和一组父子片段，用完删掉。"""
    kb = await KnowledgeBase.create(name=KB_NAME, status="正常")
    doc = await KnowledgeDocument.create(kb_id=kb.id, name="回填测试文档.txt")
    parent = await KnowledgeChunk.create(
        kb_id=kb.id,
        document_id=doc.id,
        chunk_index=0,
        chunk_type="父块",
        content="第一条 质保时长为 24 个月。第二条 质保期内非人为损坏免费维修。第三条 超期按次收费。",
        char_count=40,
        page_no=3,
    )
    child_one = await KnowledgeChunk.create(
        kb_id=kb.id,
        document_id=doc.id,
        parent_id=parent.id,
        chunk_index=0,
        chunk_type="子块",
        content="第一条 质保时长为 24 个月。",
        char_count=14,
        page_no=3,
    )
    child_two = await KnowledgeChunk.create(
        kb_id=kb.id,
        document_id=doc.id,
        parent_id=parent.id,
        chunk_index=1,
        chunk_type="子块",
        content="第三条 超期按次收费。",
        char_count=11,
        page_no=3,
    )
    plain = await KnowledgeChunk.create(
        kb_id=kb.id,
        document_id=doc.id,
        chunk_index=0,
        chunk_type="普通块",
        content="退换货政策总则。",
        char_count=8,
    )

    yield {
        "kb": kb,
        "doc": doc,
        "parent": parent,
        "child_one": child_one,
        "child_two": child_two,
        "plain": plain,
    }

    await KnowledgeChunk.filter(kb_id=kb.id).delete()
    await KnowledgeDocument.filter(id=doc.id).delete()
    await KnowledgeBase.filter(id=kb.id).delete()


def _result_of(chunk, score, source="向量检索"):
    return {
        "chunk_id": chunk.id,
        "kb_id": chunk.kb_id,
        "document_id": chunk.document_id,
        "parent_chunk_id": chunk.parent_id,
        "chunk_type": chunk.chunk_type,
        "content": chunk.content,
        "score": score,
        "source": source,
    }


async def test_child_is_replaced_by_parent(parent_child):
    """命中子块后换成父块，内容变成完整的父块正文。"""
    results = [_result_of(parent_child["child_one"], 0.88)]

    merged = await retrieval_service._backfill_parents(results)

    assert len(merged) == 1
    assert merged[0]["chunk_id"] == parent_child["parent"].id
    assert merged[0]["chunk_type"] == "父块"
    assert merged[0]["content"] == parent_child["parent"].content
    # 分数沿用命中的那个子块
    assert merged[0]["score"] == 0.88
    # 来源标出经过了回填，并记下是哪个子块命中的
    assert merged[0]["source"] == "向量检索→父块回填"
    assert merged[0]["matched_chunk_id"] == parent_child["child_one"].id


async def test_two_children_of_same_parent_merge_into_one(parent_child):
    """同一个父块下的两个子块合并成一条，不重复发给模型。"""
    results = [
        _result_of(parent_child["child_one"], 0.88),
        _result_of(parent_child["child_two"], 0.72),
    ]

    merged = await retrieval_service._backfill_parents(results)

    assert len(merged) == 1
    # 保留排名靠前那个子块的分数
    assert merged[0]["score"] == 0.88


async def test_plain_chunk_is_kept_as_is(parent_child):
    """普通块没有父块，原样保留。"""
    results = [_result_of(parent_child["plain"], 0.65)]

    merged = await retrieval_service._backfill_parents(results)

    assert len(merged) == 1
    assert merged[0]["chunk_id"] == parent_child["plain"].id
    assert merged[0]["chunk_type"] == "普通块"
    assert "父块回填" not in merged[0]["source"]


async def test_missing_parent_falls_back_to_child(parent_child):
    """父块被删时退回用子块，这条结果不会凭空消失。"""
    await KnowledgeChunk.filter(id=parent_child["parent"].id).delete()

    results = [_result_of(parent_child["child_one"], 0.88)]
    merged = await retrieval_service._backfill_parents(results)

    assert len(merged) == 1
    assert merged[0]["chunk_id"] == parent_child["child_one"].id
    assert merged[0]["chunk_type"] == "子块"


async def test_no_child_chunk_skips_query(parent_child):
    """结果里一个子块都没有时直接返回，不查数据库。"""
    results = [_result_of(parent_child["plain"], 0.65)]
    merged = await retrieval_service._backfill_parents(results)
    assert merged is results
