"""Prompt 模板接口。"""

from fastapi import APIRouter, Depends
from pydantic import BaseModel, ConfigDict

from common.auth import require_admin
from common.result import Result
from models import User
from service import prompt_template_service

router = APIRouter(prefix="/promptTemplate")


class PromptTemplatePayload(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int | None = None
    code: str | None = None
    name: str | None = None
    scene: str | None = None
    content: str | None = None
    enabled: str | None = None
    remark: str | None = None


class PreviewPayload(BaseModel):
    # 模板 id 加一组变量值，用来预览真正发给模型的文本
    id: int
    values: dict = {}


@router.post("/add")
async def add(payload: PromptTemplatePayload, _: User = Depends(require_admin)):
    await prompt_template_service.add(payload.model_dump(exclude_unset=True))
    return Result.success()


@router.put("/update")
async def update(payload: PromptTemplatePayload, _: User = Depends(require_admin)):
    await prompt_template_service.update(payload.id, payload.model_dump(exclude_unset=True))
    return Result.success()


@router.delete("/delete/{template_id}")
async def delete(template_id: int, _: User = Depends(require_admin)):
    await prompt_template_service.delete(template_id)
    return Result.success()


@router.post("/preview")
async def preview(payload: PreviewPayload, _: User = Depends(require_admin)):
    """把变量值填进模板，返回真正会发给模型的完整文本。"""
    return Result.success(await prompt_template_service.preview(payload.id, payload.values))


@router.get("/selectAll")
async def select_all(_: User = Depends(require_admin)):
    return Result.success(await prompt_template_service.select_all())


@router.get("/selectPage")
async def select_page(
    keyword: str = "",
    scene: str = "",
    page_num: int = 1,
    page_size: int = 10,
    _: User = Depends(require_admin),
):
    return Result.success(
        await prompt_template_service.select_page(keyword, scene, page_num, page_size)
    )
