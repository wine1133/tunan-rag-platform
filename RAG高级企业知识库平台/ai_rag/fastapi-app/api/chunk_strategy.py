"""切分策略管理接口。"""

from fastapi import APIRouter, Depends
from pydantic import BaseModel, ConfigDict

from common.auth import get_current_user, require_admin
from common.result import Result
from models import User
from service import chunk_strategy_service

router = APIRouter(prefix="/chunkStrategy")


class ChunkStrategyPayload(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int | None = None
    name: str | None = None
    strategy_type: str | None = None
    chunk_size: int | None = None
    chunk_overlap: int | None = None
    parent_chunk_size: int | None = None
    separators: str | None = None
    is_default: str | None = None
    remark: str | None = None


@router.post("/add")
async def add(payload: ChunkStrategyPayload, _: User = Depends(require_admin)):
    await chunk_strategy_service.add(payload.model_dump(exclude_unset=True))
    return Result.success()


@router.put("/update")
async def update(payload: ChunkStrategyPayload, _: User = Depends(require_admin)):
    await chunk_strategy_service.update(payload.id, payload.model_dump(exclude_unset=True))
    return Result.success()


@router.delete("/delete/{strategy_id}")
async def delete(strategy_id: int, _: User = Depends(require_admin)):
    await chunk_strategy_service.delete(strategy_id)
    return Result.success()


@router.get("/selectAll")
async def select_all(_: User = Depends(get_current_user)):
    # 供文档切分时的策略下拉框使用
    return Result.success(await chunk_strategy_service.select_all())


@router.get("/selectPage")
async def select_page(
    name: str = "",
    strategy_type: str = "",
    page_num: int = 1,
    page_size: int = 10,
    _: User = Depends(require_admin),
):
    return Result.success(
        await chunk_strategy_service.select_page(name, strategy_type, page_num, page_size)
    )
