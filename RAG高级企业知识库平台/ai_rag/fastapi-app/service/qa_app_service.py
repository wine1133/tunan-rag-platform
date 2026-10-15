"""问答应用管理业务逻辑。"""

import uuid
from typing import List

from common.exception_handler import CustomException
from common.result import PageInfo
from models import KnowledgeBase, QaApp, QaAppKb, User

STATUSES = {"正常", "停用"}
YES_NO = {"是", "否"}
# 默认兜底话术，管理员没填时用它
DEFAULT_EMPTY_ANSWER = "知识库中未找到相关内容。"


async def app_dict(app: QaApp, with_kbs: bool = False) -> dict:
    data = {
        "id": app.id,
        "name": app.name,
        "app_code": app.app_code,
        "description": app.description,
        "avatar": app.avatar,
        "chat_model_id": app.chat_model_id,
        "retrieval_strategy_id": app.retrieval_strategy_id,
        "prompt_code": app.prompt_code,
        "agent_enabled": app.agent_enabled,
        "max_history": app.max_history,
        "empty_answer": app.empty_answer,
        "share_enabled": app.share_enabled,
        "status": app.status,
        "create_time": app.create_time,
        "update_time": app.update_time,
    }
    if with_kbs:
        relations = await QaAppKb.filter(app_id=app.id)
        kb_ids = [item.kb_id for item in relations]
        data["kb_ids"] = kb_ids
        bases = await KnowledgeBase.filter(id__in=kb_ids)
        # 列表页要显示挂了哪几个库的名称
        data["kb_names"] = [kb.name for kb in bases]
    return data


def _validate(payload: dict) -> None:
    if not payload.get("name"):
        raise CustomException("请输入应用名称")
    if not payload.get("kb_ids"):
        raise CustomException("请至少挂载一个知识库")
    if payload.get("agent_enabled") not in {None} | YES_NO:
        raise CustomException("Agent 开关取值只能是是或否")
    status = payload.get("status")
    if status is not None and status not in STATUSES:
        raise CustomException("状态参数错误")
    max_history = payload.get("max_history")
    if max_history is not None and not 0 <= max_history <= 20:
        raise CustomException("历史消息条数取值范围是 0 到 20")


async def _bind_knowledge_bases(app_id: int, kb_ids: List[int]) -> None:
    """重建应用和知识库的关联。

    先删后插，比逐条比对增删简单，关联表本来就没有别的业务字段。
    """
    await QaAppKb.filter(app_id=app_id).delete()
    for kb_id in kb_ids:
        await QaAppKb.create(app_id=app_id, kb_id=kb_id)


async def add(current_user: User, payload: dict) -> None:
    _validate(payload)
    if await QaApp.get_or_none(name=payload["name"]):
        raise CustomException("应用名称重复")
    app = await QaApp.create(
        name=payload["name"],
        # 分享链接用的编码，自动生成，管理员不用管
        app_code=uuid.uuid4().hex[:16],
        description=payload.get("description"),
        avatar=payload.get("avatar"),
        chat_model_id=payload.get("chat_model_id"),
        retrieval_strategy_id=payload.get("retrieval_strategy_id"),
        prompt_code=payload.get("prompt_code") or "RAG_ANSWER",
        agent_enabled=payload.get("agent_enabled") or "否",
        max_history=payload.get("max_history") if payload.get("max_history") is not None else 6,
        empty_answer=payload.get("empty_answer") or DEFAULT_EMPTY_ANSWER,
        share_enabled=payload.get("share_enabled") or "否",
        status=payload.get("status") or "正常",
        create_user_id=current_user.id,
    )
    await _bind_knowledge_bases(app.id, payload["kb_ids"])


async def update(app_id: int | None, payload: dict) -> None:
    if app_id is None:
        raise CustomException("应用ID不能为空")
    if await QaApp.get_or_none(id=app_id) is None:
        raise CustomException("未找到问答应用")
    _validate(payload)
    if await QaApp.filter(name=payload["name"]).exclude(id=app_id).exists():
        raise CustomException("应用名称重复")
    await QaApp.filter(id=app_id).update(
        name=payload["name"],
        description=payload.get("description"),
        avatar=payload.get("avatar"),
        chat_model_id=payload.get("chat_model_id"),
        retrieval_strategy_id=payload.get("retrieval_strategy_id"),
        prompt_code=payload.get("prompt_code") or "RAG_ANSWER",
        agent_enabled=payload.get("agent_enabled") or "否",
        max_history=payload.get("max_history") if payload.get("max_history") is not None else 6,
        empty_answer=payload.get("empty_answer") or DEFAULT_EMPTY_ANSWER,
        share_enabled=payload.get("share_enabled") or "否",
        status=payload.get("status") or "正常",
    )
    await _bind_knowledge_bases(app_id, payload["kb_ids"])


async def delete(app_id: int) -> None:
    app = await QaApp.get_or_none(id=app_id)
    if app is None:
        raise CustomException("未找到问答应用")
    # 关联表跟着删，不留孤儿关联
    await QaAppKb.filter(app_id=app_id).delete()
    await QaApp.filter(id=app_id).delete()


async def select_by_id(app_id: int) -> dict:
    app = await QaApp.get_or_none(id=app_id)
    if app is None:
        raise CustomException("未找到问答应用")
    return await app_dict(app, with_kbs=True)


async def select_by_code(app_code: str) -> dict:
    """按分享码取应用，用户端问答页用它。"""
    app = await QaApp.get_or_none(app_code=app_code)
    if app is None:
        raise CustomException("未找到问答应用")
    if app.status != "正常":
        raise CustomException("该应用已停用")
    return await app_dict(app, with_kbs=True)


async def select_enabled() -> List[dict]:
    """用户端能看到的应用列表，只返回正常状态的。"""
    apps = await QaApp.filter(status="正常").order_by("-id")
    return [
        {
            "id": app.id,
            "name": app.name,
            "app_code": app.app_code,
            "description": app.description,
            "avatar": app.avatar,
            "agent_enabled": app.agent_enabled,
        }
        for app in apps
    ]


async def select_page(name: str = "", status: str = "", page_num: int = 1, page_size: int = 10) -> PageInfo:
    query = QaApp.filter(name__contains=name)
    if status:
        query = query.filter(status=status)
    apps = await query.order_by("-id").offset((page_num - 1) * page_size).limit(page_size)
    total = await query.count()
    return PageInfo(total=total, list=[await app_dict(app, with_kbs=True) for app in apps])
