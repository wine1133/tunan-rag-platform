"""知识库管理接口。"""

from typing import List

from fastapi import APIRouter, Depends
from pydantic import BaseModel, ConfigDict

from common.auth import get_current_user, require_admin
from common.result import Result
from models import User
from service import knowledge_base_service

router = APIRouter(prefix="/knowledgeBase")


class KnowledgeBasePayload(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    # 弹窗可能只填了部分字段，全部允许为 None，必填校验在 service 里做
    id: int | None = None
    name: str | None = None
    description: str | None = None
    status: str | None = None


@router.post("/add")
async def add(payload: KnowledgeBasePayload, current_user: User = Depends(require_admin)):
    # current_user 要用来记录创建人，所以这里不写成下划线
    await knowledge_base_service.add(current_user, payload.model_dump(exclude_unset=True))
    return Result.success()


@router.put("/update")
async def update(payload: KnowledgeBasePayload, _: User = Depends(require_admin)):
    # 文档数、片段数、绑定的模型这些字段不由本接口维护，只更新弹窗里能改的三项
    await knowledge_base_service.update(payload.id, payload.model_dump(exclude_unset=True))
    return Result.success()


@router.delete("/delete/{kb_id}")
async def delete(kb_id: int, _: User = Depends(require_admin)):
    await knowledge_base_service.delete(kb_id)
    return Result.success()


@router.delete("/deleteBatch")
async def delete_batch(ids: List[int], _: User = Depends(require_admin)):
    await knowledge_base_service.delete_batch(ids)
    return Result.success()


@router.get("/selectById/{kb_id}")
async def select_one(kb_id: int, _: User = Depends(get_current_user)):
    return Result.success(await knowledge_base_service.select_by_id(kb_id))


@router.get("/selectAll")
async def select_all(_: User = Depends(get_current_user)):
    # 供第 06 章文档管理页面的知识库下拉框使用
    return Result.success(await knowledge_base_service.select_all())


@router.get("/selectPage")
async def select_page(
    name: str = "",
    status: str = "",
    page_num: int = 1,
    page_size: int = 10,
    # 知识库是管理端资产，列表页要求管理员身份
    _: User = Depends(require_admin),
):
    return Result.success(await knowledge_base_service.select_page(name, status, page_num, page_size))
