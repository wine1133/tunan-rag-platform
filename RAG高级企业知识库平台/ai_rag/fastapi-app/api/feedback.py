"""对话日志与用户反馈接口。"""

from typing import List

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from common.auth import get_current_user, require_admin
from common.result import Result
from models import User
from service import feedback_service

router = APIRouter(prefix="/feedback")


class FeedbackPayload(BaseModel):
    message_id: int | None = None
    # 点赞 / 点踩
    feedback_type: str = ""
    reason: str | None = None


class MessageIdsPayload(BaseModel):
    message_ids: List[int] = []


@router.post("/submit")
async def submit(payload: FeedbackPayload, current_user: User = Depends(get_current_user)):
    """提交点赞或点踩。普通用户也能调，所以用 get_current_user。"""
    await feedback_service.submit(
        current_user, payload.message_id, payload.feedback_type, payload.reason
    )
    return Result.success()


@router.post("/byMessages")
async def by_messages(payload: MessageIdsPayload, current_user: User = Depends(get_current_user)):
    """批量取消息的反馈情况，页面上给每条回答标出点赞点踩数。"""
    return Result.success(
        await feedback_service.select_by_message(payload.message_ids, current_user.id)
    )


@router.get("/selectPage")
async def select_page(
    feedback_type: str = "",
    converted: str = "",
    page_num: int = 1,
    page_size: int = 10,
    _: User = Depends(require_admin),
):
    """反馈列表，带上对应的问题和回答。"""
    return Result.success(
        await feedback_service.select_page(feedback_type, converted, page_num, page_size)
    )


@router.get("/summary")
async def summary(_: User = Depends(require_admin)):
    """反馈总览。"""
    return Result.success(await feedback_service.summary())


@router.get("/sessions")
async def sessions(
    app_id: int | None = None,
    keyword: str = "",
    page_num: int = 1,
    page_size: int = 10,
    _: User = Depends(require_admin),
):
    """对话日志列表，带应用名称和点踩次数。"""
    return Result.success(
        await feedback_service.select_sessions_with_app(app_id, keyword, page_num, page_size)
    )
