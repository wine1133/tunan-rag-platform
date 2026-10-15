"""向量化接口。"""

from fastapi import APIRouter, BackgroundTasks, Depends

from common.auth import require_admin
from common.result import Result
from models import User
from service import vectorize_service

router = APIRouter(prefix="/vectorize")


@router.post("/document/{doc_id}")
async def vectorize_document(
    doc_id: int,
    background_tasks: BackgroundTasks,
    _: User = Depends(require_admin),
):
    """触发一篇文档的向量化。接口只建任务就返回，真正的调用在后台跑。"""
    task_id, context = await vectorize_service.start_vectorize(doc_id)
    background_tasks.add_task(vectorize_service.run_vectorize, doc_id, task_id, context)
    return Result.success()


@router.delete("/document/{doc_id}")
async def clear_document(doc_id: int, _: User = Depends(require_admin)):
    """清掉一篇文档的向量。"""
    deleted = await vectorize_service.clear_document_vectors(doc_id)
    return Result.success(f"已清除 {deleted} 条向量")


@router.delete("/knowledgeBase/{kb_id}")
async def clear_knowledge_base(kb_id: int, _: User = Depends(require_admin)):
    """清掉整个知识库的向量并解除模型绑定，用于更换向量模型。"""
    deleted = await vectorize_service.clear_kb_vectors(kb_id)
    return Result.success(f"已清除 {deleted} 条向量，可以改用其他向量模型重新向量化")


@router.get("/status/{kb_id}")
async def status(kb_id: int, _: User = Depends(require_admin)):
    """知识库的向量化概况。"""
    return Result.success(await vectorize_service.kb_vector_status(kb_id))


@router.get("/health")
async def health(_: User = Depends(require_admin)):
    """向量库连通性自检。"""
    return Result.success(await vectorize_service.health_check())
