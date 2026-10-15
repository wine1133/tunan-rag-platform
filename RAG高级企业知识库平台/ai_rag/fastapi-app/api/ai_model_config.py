"""AI 模型配置接口。"""

from fastapi import APIRouter, Depends
from pydantic import BaseModel, ConfigDict

from common.result import Result
from common.auth import require_admin
from models import User
from service import ai_model_config_service

router = APIRouter(prefix="/aiModelConfig")


class AiModelConfigPayload(BaseModel):
    # Pydantic 默认把 model_ 开头的字段名当成保留前缀会告警，
    # 本表的 model_type 和 model_name 是业务字段，这里关掉这个保护
    model_config = ConfigDict(from_attributes=True, protected_namespaces=())

    id: int | None = None
    name: str | None = None
    model_type: str | None = None
    provider: str | None = None
    protocol: str | None = None
    base_url: str | None = None
    api_key: str | None = None
    model_name: str | None = None
    dimension: int | None = None
    enabled: str | None = None
    remark: str | None = None


@router.post("/add")
async def add(payload: AiModelConfigPayload, _: User = Depends(require_admin)):
    await ai_model_config_service.add(payload.model_dump(exclude_unset=True))
    return Result.success()


@router.put("/update")
async def update(payload: AiModelConfigPayload, _: User = Depends(require_admin)):
    await ai_model_config_service.update(payload.id, payload.model_dump(exclude_unset=True))
    return Result.success()


@router.delete("/delete/{config_id}")
async def delete(config_id: int, _: User = Depends(require_admin)):
    await ai_model_config_service.delete(config_id)
    return Result.success()


@router.post("/test/{config_id}")
async def test(config_id: int, _: User = Depends(require_admin)):
    """连通性测试，用库里的配置真实调一次模型。"""
    return Result.success(await ai_model_config_service.test_connection(config_id))


@router.get("/selectAll")
async def select_all(model_type: str = "", _: User = Depends(require_admin)):
    return Result.success(await ai_model_config_service.select_all(model_type))


@router.get("/selectPage")
async def select_page(
    name: str = "",
    model_type: str = "",
    page_num: int = 1,
    page_size: int = 10,
    _: User = Depends(require_admin),
):
    return Result.success(
        await ai_model_config_service.select_page(name, model_type, page_num, page_size)
    )
