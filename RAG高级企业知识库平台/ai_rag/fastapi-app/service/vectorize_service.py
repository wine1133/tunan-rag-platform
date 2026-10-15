"""向量化业务逻辑。

把知识片段送进向量模型，把得到的向量写进 PGVector。

只有会被检索到的片段才需要向量：普通块和子块要，父块不要。
父块的作用是在命中子块之后回填完整上下文，它自己不参与相似度比对。
"""

import asyncio

from ai import model_factory, vector_store
from common.exception_handler import CustomException
from common.times import cost_millis, now
from models import (
    AiModelConfig,
    DocumentProcessTask,
    KnowledgeBase,
    KnowledgeChunk,
    KnowledgeDocument,
)

ERROR_MAX_LENGTH = 500
# 一次请求送多少条文本给向量模型。百炼的 text-embedding-v4 单次最多收 10 条，
# 超过会返回 "batch size is invalid, it should not be larger than 10"，
# 所以这里取 10：既是接口上限，也避免请求次数过多拖慢整体速度
BATCH_SIZE = 10
# 只有这两类片段需要向量，父块不参与检索
SEARCHABLE_TYPES = ["普通块", "子块"]


def _truncate(message: str) -> str:
    return message[:ERROR_MAX_LENGTH]


async def _bind_embedding_model(kb: KnowledgeBase, config: AiModelConfig) -> None:
    """把知识库和向量模型绑定起来，并挡住中途换模型。

    库里已有的向量是用绑定的那个模型生成的，换一个模型之后，
    新问题编码出来的向量和库里的旧向量不在同一个语义空间，算出来的相似度没有意义。
    所以绑定之后不允许直接换，必须先清空这个库的向量。
    """
    if kb.embedding_model_id is None:
        await KnowledgeBase.filter(id=kb.id).update(embedding_model_id=config.id)
        return
    if kb.embedding_model_id != config.id:
        raise CustomException(
            "该知识库已绑定另一个向量模型，直接换模型会让新旧向量对不上，"
            "请先在知识库上执行清空向量再重新向量化"
        )


async def start_vectorize(doc_id: int) -> tuple[int, dict]:
    """校验并建任务，返回任务 ID 和这次要用的向量模型配置。"""
    doc = await KnowledgeDocument.get_or_none(id=doc_id)
    if doc is None:
        raise CustomException("未找到文档")
    if doc.vector_status == "向量化中":
        raise CustomException("该文档正在向量化中，请稍候")
    total = await KnowledgeChunk.filter(document_id=doc_id, chunk_type__in=SEARCHABLE_TYPES).count()
    if total == 0:
        raise CustomException("该文档还没有可向量化的片段，请先切分")
    kb = await KnowledgeBase.get_or_none(id=doc.kb_id)
    if kb is None:
        raise CustomException("未找到知识库")
    # 取启用的向量模型，没配 Key 或没启用时这一步就会给出人话提示
    config = await model_factory.load_enabled(model_factory.EMBEDDING)
    await _bind_embedding_model(kb, config)
    task = await DocumentProcessTask.create(
        kb_id=doc.kb_id,
        document_id=doc.id,
        task_type="向量化",
        task_status="处理中",
        total_count=total,
        start_time=now(),
    )
    await KnowledgeDocument.filter(id=doc_id).update(vector_status="向量化中")
    return task.id, {"config_id": config.id, "total": total}


async def run_vectorize(doc_id: int, task_id: int, context: dict) -> None:
    """后台任务：分批调用向量模型并写入向量库。"""
    doc = await KnowledgeDocument.get_or_none(id=doc_id)
    if doc is None:
        return
    started = now()
    success = 0
    failed = 0
    try:
        config = await AiModelConfig.get_or_none(id=context["config_id"])
        if config is None:
            raise CustomException("向量模型配置已被删除，请重新配置后再试")
        embeddings = model_factory.build_embeddings(config)
        chunks = await KnowledgeChunk.filter(
            document_id=doc_id, chunk_type__in=SEARCHABLE_TYPES
        ).order_by("id")
        # 分批送，每批一次网络请求
        for start in range(0, len(chunks), BATCH_SIZE):
            batch = chunks[start : start + BATCH_SIZE]
            texts = [chunk.content for chunk in batch]
            try:
                vectors = await embeddings.aembed_documents(texts)
            except Exception as exc:
                # 一批失败不影响其他批次，把这一批标成失败继续往下跑
                failed += len(batch)
                await KnowledgeChunk.filter(id__in=[chunk.id for chunk in batch]).update(
                    vector_status="失败"
                )
                await DocumentProcessTask.filter(id=task_id).update(
                    error_message=_truncate(model_factory.translate_exception(exc))
                )
                continue
            rows = [
                {
                    "chunk_id": chunk.id,
                    "kb_id": chunk.kb_id,
                    "document_id": chunk.document_id,
                    "parent_chunk_id": chunk.parent_id,
                    "chunk_type": chunk.chunk_type,
                    "title_path": chunk.title_path,
                    "content": chunk.content,
                    "embedding": vector,
                }
                for chunk, vector in zip(batch, vectors)
            ]
            await vector_store.upsert(rows)
            await KnowledgeChunk.filter(id__in=[chunk.id for chunk in batch]).update(
                vector_status="已完成"
            )
            success += len(batch)
            # 每批写完就更新一次进度，页面刷新能看到跑到哪了
            await DocumentProcessTask.filter(id=task_id).update(
                success_count=success, fail_count=failed
            )
        # 有任何一批失败，文档整体标失败，管理员能一眼看出这篇没做完
        status = "已完成" if failed == 0 else "失败"
        await KnowledgeDocument.filter(id=doc_id).update(vector_status=status)
        await DocumentProcessTask.filter(id=task_id).update(
            task_status="已完成" if failed == 0 else "失败",
            success_count=success,
            fail_count=failed,
            end_time=now(),
            cost_millis=cost_millis(started),
        )
    except Exception as exc:
        message = exc.message if isinstance(exc, CustomException) else f"向量化失败：{exc}"
        await KnowledgeDocument.filter(id=doc_id).update(vector_status="失败")
        await DocumentProcessTask.filter(id=task_id).update(
            task_status="失败",
            success_count=success,
            fail_count=failed,
            error_message=_truncate(message),
            end_time=now(),
            cost_millis=cost_millis(started),
        )


async def clear_document_vectors(doc_id: int) -> int:
    """清掉一篇文档的向量，并把状态改回待向量化。"""
    doc = await KnowledgeDocument.get_or_none(id=doc_id)
    if doc is None:
        raise CustomException("未找到文档")
    deleted = await vector_store.delete_by_document(doc_id)
    await KnowledgeChunk.filter(document_id=doc_id).update(vector_status="待向量化")
    await KnowledgeDocument.filter(id=doc_id).update(vector_status="待向量化")
    return deleted


async def clear_kb_vectors(kb_id: int) -> int:
    """清掉整个知识库的向量，同时解除向量模型绑定。

    清空之后这个库可以改用别的向量模型重新做一遍。
    """
    kb = await KnowledgeBase.get_or_none(id=kb_id)
    if kb is None:
        raise CustomException("未找到知识库")
    deleted = await vector_store.delete_by_kb(kb_id)
    await KnowledgeChunk.filter(kb_id=kb_id).update(vector_status="待向量化")
    await KnowledgeDocument.filter(kb_id=kb_id).update(vector_status="待向量化")
    # 解绑之后下次向量化会重新绑定当前启用的模型
    await KnowledgeBase.filter(id=kb_id).update(embedding_model_id=None)
    return deleted


async def kb_vector_status(kb_id: int) -> dict:
    """知识库的向量化概况，页面上用来判断这个库能不能开始问答。"""
    kb = await KnowledgeBase.get_or_none(id=kb_id)
    if kb is None:
        raise CustomException("未找到知识库")
    total = await KnowledgeChunk.filter(kb_id=kb_id, chunk_type__in=SEARCHABLE_TYPES).count()
    done = await KnowledgeChunk.filter(
        kb_id=kb_id, chunk_type__in=SEARCHABLE_TYPES, vector_status="已完成"
    ).count()
    vector_count = await vector_store.count_by_kb(kb_id)
    model_name = None
    if kb.embedding_model_id:
        config = await AiModelConfig.get_or_none(id=kb.embedding_model_id)
        model_name = config.model_name if config else None
    return {
        "kb_id": kb_id,
        "kb_name": kb.name,
        # 应该有向量的片段数
        "searchable_count": total,
        # 片段表里标记为已完成的数量
        "done_count": done,
        # 向量库里实际存在的向量条数，和上面对不上说明两边不同步
        "vector_count": vector_count,
        "embedding_model": model_name,
    }


async def health_check() -> str:
    """向量库连通性自检。"""
    return await vector_store.health_check()
