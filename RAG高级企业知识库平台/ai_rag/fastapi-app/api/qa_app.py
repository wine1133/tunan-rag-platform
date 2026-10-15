"""问答应用管理与多轮问答接口。"""

from typing import List

from fastapi import APIRouter, Depends
from pydantic import BaseModel, ConfigDict
from sse_starlette.sse import EventSourceResponse

from common.auth import get_current_user, require_admin
from common.result import Result
from models import User
from service import chat_service, qa_app_service

router = APIRouter(prefix="/qaApp")


class QaAppPayload(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int | None = None
    name: str | None = None
    description: str | None = None
    avatar: str | None = None
    # 挂载的知识库，至少一个
    kb_ids: List[int] = []
    chat_model_id: int | None = None
    retrieval_strategy_id: int | None = None
    prompt_code: str | None = None
    agent_enabled: str | None = None
    max_history: int | None = None
    empty_answer: str | None = None
    share_enabled: str | None = None
    status: str | None = None


class SessionPayload(BaseModel):
    app_id: int
    # 管理端测试和用户端问答用同一套接口，靠这个字段区分来源
    source: str = "管理端"


class AskPayload(BaseModel):
    session_id: int
    question: str = ""


@router.post("/add")
async def add(payload: QaAppPayload, current_user: User = Depends(require_admin)):
    await qa_app_service.add(current_user, payload.model_dump(exclude_unset=True))
    return Result.success()


@router.put("/update")
async def update(payload: QaAppPayload, _: User = Depends(require_admin)):
    await qa_app_service.update(payload.id, payload.model_dump(exclude_unset=True))
    return Result.success()


@router.delete("/delete/{app_id}")
async def delete(app_id: int, _: User = Depends(require_admin)):
    await qa_app_service.delete(app_id)
    return Result.success()


@router.get("/selectById/{app_id}")
async def select_one(app_id: int, _: User = Depends(get_current_user)):
    return Result.success(await qa_app_service.select_by_id(app_id))


@router.get("/selectEnabled")
async def select_enabled(_: User = Depends(get_current_user)):
    """用户端能看到的应用列表。"""
    return Result.success(await qa_app_service.select_enabled())


@router.get("/selectPage")
async def select_page(
    name: str = "",
    status: str = "",
    page_num: int = 1,
    page_size: int = 10,
    _: User = Depends(require_admin),
):
    return Result.success(await qa_app_service.select_page(name, status, page_num, page_size))


@router.post("/session")
async def open_session(payload: SessionPayload, current_user: User = Depends(get_current_user)):
    """新建会话。前端发第一条消息前先调它拿 session_id。"""
    return Result.success(
        await chat_service.open_session(payload.app_id, current_user.id, payload.source)
    )


@router.post("/ask")
async def ask(payload: AskPayload, current_user: User = Depends(get_current_user)):
    """流式问答。

    返回的是 SSE 流而不是 Result，前端用 EventSource 或 fetch 流式读取。
    事件类型：reference 引用来源、progress 状态图节点进度（仅 Agentic 模式）、
    agent Agent 执行概况、delta 正文增量、done 结束、error 失败。
    """
    # 会话归属校验放在开流之前，越权的请求直接被异常处理器拦掉，
    # 不会先返回 200 再在流里报错
    await chat_service.assert_session_access(payload.session_id, current_user)
    return EventSourceResponse(
        chat_service.stream_chat(payload.session_id, payload.question, current_user.id)
    )


@router.get("/messages/{session_id}")
async def messages(session_id: int, current_user: User = Depends(get_current_user)):
    """一个会话的完整消息列表，含引用来源。"""
    await chat_service.assert_session_access(session_id, current_user)
    return Result.success(await chat_service.select_messages(session_id))


@router.delete("/session/{session_id}")
async def delete_session(session_id: int, current_user: User = Depends(get_current_user)):
    """删除一个会话。

    普通用户只删得掉自己的会话，归属校验在 service 里和 /ask、/messages 共用同一段。
    """
    await chat_service.delete_session(session_id, current_user)
    return Result.success()


@router.get("/mySessions")
async def my_sessions(
    page_num: int = 1,
    page_size: int = 10,
    current_user: User = Depends(get_current_user),
):
    """当前登录用户自己的会话列表，用户端左侧的历史对话靠它。

    和下面管理端的 /sessions 用的是同一个查询，区别只在于这里的
    user_id 是从 token 里取的，前端传不了别人的。
    """
    return Result.success(
        await chat_service.select_sessions(None, current_user.id, page_num, page_size)
    )


@router.get("/sessions")
async def sessions(
    app_id: int | None = None,
    page_num: int = 1,
    page_size: int = 10,
    _: User = Depends(require_admin),
):
    """会话列表。"""
    return Result.success(await chat_service.select_sessions(app_id, None, page_num, page_size))
