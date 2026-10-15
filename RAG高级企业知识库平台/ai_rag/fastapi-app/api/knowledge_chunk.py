"""知识片段接口。"""

from typing import List

from fastapi import APIRouter, BackgroundTasks, Depends
from pydantic import BaseModel, ConfigDict

from common.auth import get_current_user, require_admin
from common.result import Result
from models import User
from service import knowledge_chunk_service

router = APIRouter(prefix="/knowledgeChunk")


class ChunkPayload(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    # 片段只允许改正文，其他字段由切分产生，页面改不到
    id: int | None = None
    content: str | None = None


@router.post("/split/{doc_id}")
async def split(
    doc_id: int,
    background_tasks: BackgroundTasks,
    strategy_id: int | None = None,
    _: User = Depends(require_admin),
):
    """触发文档切分。接口只建任务就返回，真正的切分在后台跑。"""
    task_id, strategy = await knowledge_chunk_service.start_split(doc_id, strategy_id)
    # 策略在接口里就解析好，后台任务直接用，避免后台再查一次库
    background_tasks.add_task(knowledge_chunk_service.run_split, doc_id, task_id, strategy)
    return Result.success()


@router.put("/update")
async def update(payload: ChunkPayload, _: User = Depends(require_admin)):
    await knowledge_chunk_service.update_content(payload.id, payload.content)
    return Result.success()


@router.delete("/delete/{chunk_id}")
async def delete(chunk_id: int, _: User = Depends(require_admin)):
    await knowledge_chunk_service.delete(chunk_id)
    return Result.success()


@router.delete("/deleteBatch")
async def delete_batch(ids: List[int], _: User = Depends(require_admin)):
    await knowledge_chunk_service.delete_batch(ids)
    return Result.success()


@router.get("/selectById/{chunk_id}")
async def select_one(chunk_id: int, _: User = Depends(get_current_user)):
    return Result.success(await knowledge_chunk_service.select_by_id(chunk_id))


@router.get("/selectPage")
async def select_page(
    document_id: int | None = None,
    kb_id: int | None = None,
    chunk_type: str = "",
    keyword: str = "",
    page_num: int = 1,
    page_size: int = 10,
    _: User = Depends(require_admin),
):
    return Result.success(
        await knowledge_chunk_service.select_page(
            document_id, kb_id, chunk_type, keyword, page_num, page_size
        )
    )
