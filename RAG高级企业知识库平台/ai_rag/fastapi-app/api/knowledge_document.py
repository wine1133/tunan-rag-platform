"""知识文档管理接口。"""

from typing import List

from fastapi import APIRouter, BackgroundTasks, Depends
from pydantic import BaseModel, ConfigDict

from common.auth import get_current_user, require_admin
from common.result import Result
from models import User
from service import document_parse_service, knowledge_document_service

router = APIRouter(prefix="/knowledgeDocument")


class KnowledgeDocumentPayload(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    # 弹窗可能只填了部分字段，全部允许为 None，必填校验在 service 里做
    id: int | None = None
    kb_id: int | None = None
    name: str | None = None
    file_name: str | None = None
    file_url: str | None = None
    file_size: int | None = None


@router.post("/add")
async def add(payload: KnowledgeDocumentPayload, current_user: User = Depends(require_admin)):
    # current_user 要用来记录上传人，所以这里不写成下划线
    await knowledge_document_service.add(current_user, payload.model_dump(exclude_unset=True))
    return Result.success()


@router.put("/update")
async def update(payload: KnowledgeDocumentPayload, _: User = Depends(require_admin)):
    await knowledge_document_service.update(payload.id, payload.model_dump(exclude_unset=True))
    return Result.success()


@router.delete("/delete/{doc_id}")
async def delete(doc_id: int, _: User = Depends(require_admin)):
    await knowledge_document_service.delete(doc_id)
    return Result.success()


@router.delete("/deleteBatch")
async def delete_batch(ids: List[int], _: User = Depends(require_admin)):
    await knowledge_document_service.delete_batch(ids)
    return Result.success()


@router.get("/selectById/{doc_id}")
async def select_one(doc_id: int, _: User = Depends(get_current_user)):
    return Result.success(await knowledge_document_service.select_by_id(doc_id))


@router.post("/parse/{doc_id}")
async def parse(doc_id: int, background_tasks: BackgroundTasks, _: User = Depends(require_admin)):
    """触发文档解析。接口只把状态置为解析中就返回，真正的解析在后台跑。"""
    task_id = await document_parse_service.start_parse(doc_id)
    # add_task 注册的函数会在响应发出之后执行，前端不用等着解析结束
    background_tasks.add_task(document_parse_service.run_parse, doc_id, task_id)
    return Result.success()


@router.get("/parsedText/{doc_id}")
async def parsed_text(doc_id: int, _: User = Depends(require_admin)):
    """查看解析出来的文本，供页面上的查看弹窗使用。"""
    return Result.success(await document_parse_service.select_parsed_text(doc_id))


@router.get("/tasks/{doc_id}")
async def tasks(doc_id: int, _: User = Depends(require_admin)):
    """查某篇文档的处理任务记录。"""
    return Result.success(await document_parse_service.select_tasks(doc_id))


@router.get("/selectPage")
async def select_page(
    kb_id: int | None = None,
    name: str = "",
    parse_status: str = "",
    page_num: int = 1,
    page_size: int = 10,
    _: User = Depends(require_admin),
):
    return Result.success(
        await knowledge_document_service.select_page(kb_id, name, parse_status, page_num, page_size)
    )
