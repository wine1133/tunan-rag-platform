"""知识片段业务逻辑。

包含两部分：把文档切成片段（写），以及片段的查询和维护（读改删）。
"""

import asyncio
from typing import List

from ai import splitter, vector_store
from common.exception_handler import CustomException
from common.result import PageInfo
from common.times import cost_millis, now
from models import (
    ChunkStrategy,
    DocumentProcessTask,
    KnowledgeBase,
    KnowledgeChunk,
    KnowledgeDocument,
)
from service import chunk_strategy_service

ERROR_MAX_LENGTH = 500


def chunk_dict(chunk: KnowledgeChunk) -> dict:
    return {
        "id": chunk.id,
        "kb_id": chunk.kb_id,
        "document_id": chunk.document_id,
        "parent_id": chunk.parent_id,
        "chunk_index": chunk.chunk_index,
        "chunk_type": chunk.chunk_type,
        "content": chunk.content,
        "char_count": chunk.char_count,
        "page_no": chunk.page_no,
        "title_path": chunk.title_path,
        "vector_status": chunk.vector_status,
        "create_time": chunk.create_time,
        "update_time": chunk.update_time,
    }


async def _refresh_counts(document_id: int, kb_id: int) -> None:
    """重算文档和知识库上的片段数。

    父块只是给生成用的上下文容器，不参与检索，统计片段数时不计入，
    这样列表页上的片段数和实际会被检索到的片段数是一致的。
    """
    doc_count = await KnowledgeChunk.filter(document_id=document_id).exclude(chunk_type="父块").count()
    await KnowledgeDocument.filter(id=document_id).update(chunk_count=doc_count)
    kb_count = await KnowledgeChunk.filter(kb_id=kb_id).exclude(chunk_type="父块").count()
    await KnowledgeBase.filter(id=kb_id).update(chunk_count=kb_count)


async def _resolve_strategy(kb_id: int, strategy_id: int | None) -> dict:
    """定下这次切分用哪套策略。

    优先级：页面上临时选的 > 知识库自己绑定的 > 全局默认策略。
    """
    if strategy_id:
        strategy = await ChunkStrategy.get_or_none(id=strategy_id)
        if strategy is None:
            raise CustomException("未找到切分策略")
        return chunk_strategy_service.strategy_dict(strategy)
    kb = await KnowledgeBase.get_or_none(id=kb_id)
    if kb is not None and kb.chunk_strategy_id:
        strategy = await ChunkStrategy.get_or_none(id=kb.chunk_strategy_id)
        if strategy is not None:
            return chunk_strategy_service.strategy_dict(strategy)
    return await chunk_strategy_service.select_default()


async def start_split(doc_id: int, strategy_id: int | None) -> tuple[int, dict]:
    """校验并建任务，返回任务 ID 和这次要用的策略。"""
    doc = await KnowledgeDocument.get_or_none(id=doc_id)
    if doc is None:
        raise CustomException("未找到文档")
    if doc.parse_status != "解析完成":
        raise CustomException("请先解析文档，解析完成后才能切分")
    if not doc.parsed_text:
        raise CustomException("该文档没有解析文本，请重新解析")
    strategy = await _resolve_strategy(doc.kb_id, strategy_id)
    task = await DocumentProcessTask.create(
        kb_id=doc.kb_id,
        document_id=doc.id,
        task_type="文本切分",
        task_status="处理中",
        total_count=1,
        start_time=now(),
    )
    return task.id, strategy


async def run_split(doc_id: int, task_id: int, strategy: dict) -> None:
    """后台任务：切分并写入片段。"""
    doc = await KnowledgeDocument.get_or_none(id=doc_id)
    if doc is None:
        return
    started = now()
    try:
        # 切分是纯 CPU 操作，丢到线程里执行，不阻塞事件循环
        chunks = await asyncio.to_thread(splitter.split, doc.parsed_text, strategy)
        if not chunks:
            raise CustomException("没有切分出任何片段，请检查切分参数")
        # 重新切分前先清掉这篇文档的旧片段，避免新旧片段混在一起；
        # 旧片段对应的向量也要一起清，否则向量库里会留下指向已删片段的孤儿向量
        if doc.vector_status in {"已完成", "失败", "向量化中"}:
            await vector_store.delete_by_document(doc_id)
        # 重新切分前先清掉这篇文档的旧片段，避免新旧片段混在一起
        await KnowledgeChunk.filter(document_id=doc_id).delete()
        # created_ids 按返回列表的下标记录已入库片段的真实 id，
        # 子块要靠它把 parent_index 换算成数据库里的 parent_id
        created_ids: list[int] = []
        for chunk in chunks:
            parent_id = None
            if chunk.parent_index is not None:
                parent_id = created_ids[chunk.parent_index]
            created = await KnowledgeChunk.create(
                kb_id=doc.kb_id,
                document_id=doc.id,
                parent_id=parent_id,
                chunk_index=chunk.chunk_index,
                chunk_type=chunk.chunk_type,
                content=chunk.content,
                char_count=len(chunk.content),
                page_no=chunk.page_no,
            )
            created_ids.append(created.id)
        # 片段变了，之前写进向量库的向量全部作废
        await KnowledgeDocument.filter(id=doc_id).update(vector_status="待向量化")
        await _refresh_counts(doc_id, doc.kb_id)
        await DocumentProcessTask.filter(id=task_id).update(
            task_status="已完成",
            success_count=len(chunks),
            total_count=len(chunks),
            end_time=now(),
            cost_millis=cost_millis(started),
        )
    except Exception as exc:
        message = exc.message if isinstance(exc, CustomException) else f"切分失败：{exc}"
        await DocumentProcessTask.filter(id=task_id).update(
            task_status="失败",
            fail_count=1,
            error_message=message[:ERROR_MAX_LENGTH],
            end_time=now(),
            cost_millis=cost_millis(started),
        )


async def update_content(chunk_id: int | None, content: str | None) -> None:
    """人工修正片段内容。"""
    if chunk_id is None:
        raise CustomException("片段ID不能为空")
    if not content or not content.strip():
        raise CustomException("片段内容不能为空")
    chunk = await KnowledgeChunk.get_or_none(id=chunk_id)
    if chunk is None:
        raise CustomException("未找到片段")
    text = content.strip()
    await KnowledgeChunk.filter(id=chunk_id).update(
        content=text,
        char_count=len(text),
        # 内容改了，之前那条向量对应的是旧文本，要重新向量化
        vector_status="待向量化",
    )
    await KnowledgeDocument.filter(id=chunk.document_id).update(vector_status="待向量化")


async def delete(chunk_id: int) -> None:
    chunk = await KnowledgeChunk.get_or_none(id=chunk_id)
    if chunk is None:
        raise CustomException("未找到片段")
    # 删父块会让它的子块失去回填目标，检索命中子块后取不到完整上下文
    if chunk.chunk_type == "父块":
        raise CustomException("父块不能单独删除，请重新切分整篇文档")
    # 片段没了，它在向量库里那条向量也要删掉，否则检索还能命中一段已经不存在的内容
    if chunk.vector_status == "已完成":
        await vector_store.delete_by_chunk_ids([chunk_id])
    await KnowledgeChunk.filter(id=chunk_id).delete()
    await _refresh_counts(chunk.document_id, chunk.kb_id)


async def delete_batch(ids: List[int]) -> None:
    chunks = await KnowledgeChunk.filter(id__in=ids)
    if any(chunk.chunk_type == "父块" for chunk in chunks):
        raise CustomException("勾选里包含父块，父块不能单独删除")
    scopes = {(chunk.document_id, chunk.kb_id) for chunk in chunks}
    # 只清理确实写过向量的那些片段，没向量化过的不用连向量库
    vectorized = [chunk.id for chunk in chunks if chunk.vector_status == "已完成"]
    if vectorized:
        await vector_store.delete_by_chunk_ids(vectorized)
    await KnowledgeChunk.filter(id__in=ids).delete()
    for document_id, kb_id in scopes:
        await _refresh_counts(document_id, kb_id)


async def select_by_id(chunk_id: int) -> dict:
    chunk = await KnowledgeChunk.get_or_none(id=chunk_id)
    if chunk is None:
        raise CustomException("未找到片段")
    return chunk_dict(chunk)


async def select_page(
    document_id: int | None = None,
    kb_id: int | None = None,
    chunk_type: str = "",
    keyword: str = "",
    page_num: int = 1,
    page_size: int = 10,
) -> PageInfo:
    query = KnowledgeChunk.all()
    # document_id 来自页面顶部文档下拉框，是最常用的筛选维度
    if document_id:
        query = query.filter(document_id=document_id)
    if kb_id:
        query = query.filter(kb_id=kb_id)
    # chunk_type 来自片段类型下拉框，父子分块时用来只看子块或只看父块
    if chunk_type:
        query = query.filter(chunk_type=chunk_type)
    # keyword 在片段正文里模糊匹配，用来快速定位某句话被切到了哪一段
    if keyword:
        query = query.filter(content__contains=keyword)
    # 按文档内顺序号正序排，页面上看到的片段顺序和原文一致
    chunks = await query.order_by("chunk_type", "chunk_index").offset((page_num - 1) * page_size).limit(page_size)
    total = await query.count()
    return PageInfo(total=total, list=[chunk_dict(chunk) for chunk in chunks])
