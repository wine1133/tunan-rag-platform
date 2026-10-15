"""AI 模型配置管理业务逻辑。"""

from typing import List

from ai import model_factory
from common.exception_handler import CustomException
from common.result import PageInfo
from models import AiModelConfig

MODEL_TYPES = {model_factory.CHAT, model_factory.EMBEDDING, model_factory.RERANK}
PROTOCOLS = {"OpenAI兼容", "DashScope原生"}


def config_dict(config: AiModelConfig, mask_key: bool = True) -> dict:
    return {
        "id": config.id,
        "name": config.name,
        "model_type": config.model_type,
        "provider": config.provider,
        "protocol": config.protocol,
        "base_url": config.base_url,
        # 列表页只显示密钥的头尾，避免整串密钥出现在页面和浏览器缓存里
        "api_key": _mask(config.api_key) if mask_key else config.api_key,
        "model_name": config.model_name,
        "dimension": config.dimension,
        "enabled": config.enabled,
        "remark": config.remark,
        "create_time": config.create_time,
        "update_time": config.update_time,
    }


def _mask(api_key: str | None) -> str:
    """密钥脱敏，只保留前 4 位和后 4 位。"""
    if not api_key:
        return ""
    if len(api_key) <= 8:
        return "*" * len(api_key)
    return api_key[:4] + "*" * 8 + api_key[-4:]


def _validate(payload: dict) -> None:
    if not payload.get("name"):
        raise CustomException("请输入配置名称")
    if payload.get("model_type") not in MODEL_TYPES:
        raise CustomException("模型类型参数错误")
    if payload.get("protocol") not in PROTOCOLS:
        raise CustomException("接口协议参数错误")
    if not payload.get("base_url"):
        raise CustomException("请输入接口地址")
    if not payload.get("model_name"):
        raise CustomException("请输入模型名称")
    # 向量维度决定 PGVector 建表时的 vector(N)，向量模型必须填
    if payload.get("model_type") == model_factory.EMBEDDING and not payload.get("dimension"):
        raise CustomException("向量模型必须填写向量维度")


async def _clear_other_enabled(model_type: str, keep_id: int | None = None) -> None:
    """同一类型下只允许一条启用，把其他条停掉。"""
    query = AiModelConfig.filter(model_type=model_type, enabled="是")
    if keep_id is not None:
        query = query.exclude(id=keep_id)
    await query.update(enabled="否")


async def add(payload: dict) -> None:
    _validate(payload)
    if await AiModelConfig.get_or_none(name=payload["name"]):
        raise CustomException("配置名称重复")
    enabled = payload.get("enabled") or "否"
    if enabled == "是":
        await _clear_other_enabled(payload["model_type"])
    await AiModelConfig.create(
        name=payload["name"],
        model_type=payload["model_type"],
        provider=payload.get("provider"),
        protocol=payload["protocol"],
        base_url=payload["base_url"],
        api_key=payload.get("api_key"),
        model_name=payload["model_name"],
        # 只有向量模型需要维度，其他类型存空值
        dimension=payload.get("dimension") if payload["model_type"] == model_factory.EMBEDDING else None,
        enabled=enabled,
        remark=payload.get("remark"),
    )


async def update(config_id: int | None, payload: dict) -> None:
    if config_id is None:
        raise CustomException("配置ID不能为空")
    config = await AiModelConfig.get_or_none(id=config_id)
    if config is None:
        raise CustomException("未找到模型配置")
    _validate(payload)
    if await AiModelConfig.filter(name=payload["name"]).exclude(id=config_id).exists():
        raise CustomException("配置名称重复")
    enabled = payload.get("enabled") or "否"
    if enabled == "是":
        await _clear_other_enabled(payload["model_type"], keep_id=config_id)
    api_key = payload.get("api_key")
    update_data = {
        "name": payload["name"],
        "model_type": payload["model_type"],
        "provider": payload.get("provider"),
        "protocol": payload["protocol"],
        "base_url": payload["base_url"],
        "model_name": payload["model_name"],
        "dimension": payload.get("dimension") if payload["model_type"] == model_factory.EMBEDDING else None,
        "enabled": enabled,
        "remark": payload.get("remark"),
    }
    # 页面上密钥是脱敏显示的，用户没重新输入时不能拿脱敏串把真密钥覆盖掉
    if api_key and "*" not in api_key:
        update_data["api_key"] = api_key
    await AiModelConfig.filter(id=config_id).update(**update_data)


async def delete(config_id: int) -> None:
    config = await AiModelConfig.get_or_none(id=config_id)
    if config is None:
        raise CustomException("未找到模型配置")
    # 启用中的配置正被问答和向量化链路使用，删掉会让功能直接不可用
    if config.enabled == "是":
        raise CustomException("启用中的配置不能删除，请先启用同类型的另一条")
    await AiModelConfig.filter(id=config_id).delete()


async def test_connection(config_id: int) -> str:
    """连通性测试，用库里保存的配置真实调一次模型。"""
    config = await AiModelConfig.get_or_none(id=config_id)
    if config is None:
        raise CustomException("未找到模型配置")
    return await model_factory.test_connection(config)


async def select_all(model_type: str = "") -> List[dict]:
    query = AiModelConfig.all()
    if model_type:
        query = query.filter(model_type=model_type)
    configs = await query.order_by("model_type", "-enabled", "id")
    return [config_dict(config) for config in configs]


async def select_page(name: str = "", model_type: str = "", page_num: int = 1, page_size: int = 10) -> PageInfo:
    query = AiModelConfig.filter(name__contains=name)
    if model_type:
        query = query.filter(model_type=model_type)
    configs = await query.order_by("model_type", "id").offset((page_num - 1) * page_size).limit(page_size)
    total = await query.count()
    return PageInfo(total=total, list=[config_dict(config) for config in configs])
