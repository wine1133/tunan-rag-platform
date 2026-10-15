"""工具中心接口。"""

from fastapi import APIRouter, Depends
from pydantic import BaseModel, ConfigDict

from common.auth import require_admin
from common.result import Result
from models import User
from service import function_tool_service

router = APIRouter(prefix="/functionTool")


class FunctionToolPayload(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int | None = None
    tool_code: str | None = None
    tool_name: str | None = None
    description: str | None = None
    input_schema: str | None = None
    enabled: str | None = None
    sort: int | None = None


@router.post("/add")
async def add(payload: FunctionToolPayload, _: User = Depends(require_admin)):
    await function_tool_service.add(payload.model_dump(exclude_unset=True))
    return Result.success()


@router.put("/update")
async def update(payload: FunctionToolPayload, _: User = Depends(require_admin)):
    await function_tool_service.update(payload.id, payload.model_dump(exclude_unset=True))
    return Result.success()


@router.put("/toggle/{tool_id}")
async def toggle(tool_id: int, enabled: str, _: User = Depends(require_admin)):
    """启用开关。改完模型下一次执行就拿不到这个工具。"""
    await function_tool_service.toggle(tool_id, enabled)
    return Result.success()


@router.delete("/delete/{tool_id}")
async def delete(tool_id: int, _: User = Depends(require_admin)):
    await function_tool_service.delete(tool_id)
    return Result.success()


@router.get("/selectPage")
async def select_page(
    keyword: str = "",
    enabled: str = "",
    page_num: int = 1,
    page_size: int = 10,
    _: User = Depends(require_admin),
):
    return Result.success(
        await function_tool_service.select_page(keyword, enabled, page_num, page_size)
    )


@router.get("/definitions")
async def definitions(_: User = Depends(require_admin)):
    """预览真正会发给模型的工具定义。"""
    return Result.success(await function_tool_service.preview_definitions())


@router.get("/logs")
async def logs(
    tool_code: str = "",
    call_status: str = "",
    run_id: int | None = None,
    page_num: int = 1,
    page_size: int = 10,
    _: User = Depends(require_admin),
):
    """工具调用日志。"""
    return Result.success(
        await function_tool_service.select_logs(tool_code, call_status, run_id, page_num, page_size)
    )


@router.get("/logSummary")
async def log_summary(_: User = Depends(require_admin)):
    """按工具统计调用次数和成功率。"""
    return Result.success(await function_tool_service.log_summary())
