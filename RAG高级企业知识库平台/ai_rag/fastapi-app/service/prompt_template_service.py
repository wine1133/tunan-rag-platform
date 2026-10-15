"""Prompt 模板管理业务逻辑。"""

from typing import List

from ai import prompt_loader
from common.exception_handler import CustomException
from common.result import PageInfo
from models import PromptTemplate


def template_dict(template: PromptTemplate) -> dict:
    return {
        "id": template.id,
        "code": template.code,
        "name": template.name,
        "scene": template.scene,
        "content": template.content,
        "variables": template.variables,
        "enabled": template.enabled,
        "remark": template.remark,
        "create_time": template.create_time,
        "update_time": template.update_time,
    }


def _validate(payload: dict) -> None:
    if not payload.get("code"):
        raise CustomException("请输入模板编码")
    if not payload.get("name"):
        raise CustomException("请输入模板名称")
    content = payload.get("content")
    if not content or not content.strip():
        raise CustomException("请输入模板内容")


async def add(payload: dict) -> None:
    _validate(payload)
    # 代码按 code 取模板，重复的编码会让取到哪一条变得不确定
    if await PromptTemplate.get_or_none(code=payload["code"]):
        raise CustomException("模板编码重复")
    await PromptTemplate.create(
        code=payload["code"],
        name=payload["name"],
        scene=payload.get("scene"),
        content=payload["content"],
        # 变量清单从内容里自动抽取，不让管理员手工维护，避免和实际内容对不上
        variables=prompt_loader.extract_variables(payload["content"]),
        enabled=payload.get("enabled") or "是",
        remark=payload.get("remark"),
    )


async def update(template_id: int | None, payload: dict) -> None:
    if template_id is None:
        raise CustomException("模板ID不能为空")
    template = await PromptTemplate.get_or_none(id=template_id)
    if template is None:
        raise CustomException("未找到 Prompt 模板")
    _validate(payload)
    if await PromptTemplate.filter(code=payload["code"]).exclude(id=template_id).exists():
        raise CustomException("模板编码重复")
    await PromptTemplate.filter(id=template_id).update(
        code=payload["code"],
        name=payload["name"],
        scene=payload.get("scene"),
        content=payload["content"],
        # 内容改了变量可能也变了，跟着重新抽一次
        variables=prompt_loader.extract_variables(payload["content"]),
        enabled=payload.get("enabled") or "是",
        remark=payload.get("remark"),
    )


async def delete(template_id: int) -> None:
    template = await PromptTemplate.get_or_none(id=template_id)
    if template is None:
        raise CustomException("未找到 Prompt 模板")
    await PromptTemplate.filter(id=template_id).delete()


async def preview(template_id: int, values: dict) -> str:
    """按填入的变量值渲染一遍模板，看看真正发给模型的是什么。"""
    template = await PromptTemplate.get_or_none(id=template_id)
    if template is None:
        raise CustomException("未找到 Prompt 模板")
    return await prompt_loader.render(template.code, **values)


async def select_all() -> List[dict]:
    templates = await PromptTemplate.all().order_by("id")
    return [template_dict(item) for item in templates]


async def select_page(keyword: str = "", scene: str = "", page_num: int = 1, page_size: int = 10) -> PageInfo:
    # keyword 同时匹配名称，页面上一个输入框就够用
    query = PromptTemplate.filter(name__contains=keyword)
    if scene:
        query = query.filter(scene=scene)
    templates = await query.order_by("id").offset((page_num - 1) * page_size).limit(page_size)
    total = await query.count()
    return PageInfo(total=total, list=[template_dict(item) for item in templates])
