"""对话日志与用户反馈。

点踩是这个项目里最有价值的一类数据：用户主动指出"这个答案不对"，
而这些问题正是知识库最该补的地方。第 27 章会把它们沉淀成评测用例。
"""

from typing import List

from common.exception_handler import CustomException
from common.result import PageInfo
from models import ChatMessage, ChatSession, MessageFeedback, QaApp, User

FEEDBACK_TYPES = {"点赞", "点踩"}


async def submit(current_user: User, message_id: int | None, feedback_type: str, reason: str | None) -> None:
    """提交反馈。同一条消息只保留一个人最后一次的反馈。"""
    if message_id is None:
        raise CustomException("消息ID不能为空")
    if feedback_type not in FEEDBACK_TYPES:
        raise CustomException("反馈类型参数错误")
    message = await ChatMessage.get_or_none(id=message_id)
    if message is None:
        raise CustomException("未找到消息")
    # 只允许对助手的回答打分，给自己的提问点赞没有意义
    if message.role != "assistant":
        raise CustomException("只能对回答内容进行反馈")
    # 只能给自己会话里的回答打分。message_id 是自增数字，不校验的话
    # 换个数字就能给别人的对话刷反馈，而反馈数据后面要沉淀成评测用例
    if current_user.role != "ADMIN":
        session = await ChatSession.get_or_none(id=message.session_id)
        if session is None or session.user_id != current_user.id:
            raise CustomException("无权对该回答进行反馈")
    existing = await MessageFeedback.get_or_none(message_id=message_id, user_id=current_user.id)
    if existing is not None:
        # 用户改主意了，覆盖上一次；converted 保持不变，已经沉淀过的不重复沉淀
        await MessageFeedback.filter(id=existing.id).update(
            feedback_type=feedback_type, reason=reason
        )
        return
    await MessageFeedback.create(
        message_id=message_id,
        user_id=current_user.id,
        feedback_type=feedback_type,
        reason=reason,
    )


async def select_by_message(message_ids: List[int], user_id: int | None = None) -> dict:
    """按消息 ID 批量取反馈，页面上给每条回答标出当前的点赞点踩状态。

    user_id 传了的话，每条再多一个 mine 字段，值是这个人自己点的类型。
    用户端翻历史对话时，靠它把自己点过的赞/踩重新高亮出来。
    """
    if not message_ids:
        return {}
    feedbacks = await MessageFeedback.filter(message_id__in=message_ids)
    grouped: dict[int, dict] = {}
    for item in feedbacks:
        stats = grouped.setdefault(item.message_id, {"点赞": 0, "点踩": 0, "mine": ""})
        stats[item.feedback_type] = stats.get(item.feedback_type, 0) + 1
        if user_id is not None and item.user_id == user_id:
            stats["mine"] = item.feedback_type
    return grouped


async def select_page(
    feedback_type: str = "",
    converted: str = "",
    page_num: int = 1,
    page_size: int = 10,
) -> PageInfo:
    """反馈列表。带上对应的问题和回答，管理员不用来回跳会话。"""
    query = MessageFeedback.all()
    if feedback_type:
        query = query.filter(feedback_type=feedback_type)
    if converted:
        query = query.filter(converted=converted)
    feedbacks = await query.order_by("-id").offset((page_num - 1) * page_size).limit(page_size)
    total = await query.count()

    message_ids = [item.message_id for item in feedbacks]
    messages = await ChatMessage.filter(id__in=message_ids)
    message_map = {message.id: message for message in messages}
    # 回答的上一条就是对应的提问，按会话和 id 一次查回来
    session_ids = {message.session_id for message in messages}
    all_messages = await ChatMessage.filter(session_id__in=session_ids).order_by("id")
    previous: dict[int, str] = {}
    last_user_content = {}
    for message in all_messages:
        if message.role == "user":
            last_user_content[message.session_id] = message.content
        else:
            previous[message.id] = last_user_content.get(message.session_id, "")

    return PageInfo(
        total=total,
        list=[
            {
                "id": item.id,
                "message_id": item.message_id,
                "feedback_type": item.feedback_type,
                "reason": item.reason,
                "converted": item.converted,
                "question": previous.get(item.message_id, ""),
                "answer": message_map[item.message_id].content if item.message_id in message_map else "",
                "create_time": item.create_time,
            }
            for item in feedbacks
        ],
    )


async def summary() -> dict:
    """反馈总览，看整体满意度。"""
    liked = await MessageFeedback.filter(feedback_type="点赞").count()
    disliked = await MessageFeedback.filter(feedback_type="点踩").count()
    pending = await MessageFeedback.filter(feedback_type="点踩", converted="否").count()
    total = liked + disliked
    return {
        "liked": liked,
        "disliked": disliked,
        # 还没沉淀成评测用例的点踩数，这是第 27 章要处理的存量
        "pending_convert": pending,
        # 一条反馈都没有时不显示 100%，避免造成误解
        "satisfaction": round(liked / total * 100, 1) if total else None,
    }


async def select_sessions_with_app(
    app_id: int | None = None,
    keyword: str = "",
    page_num: int = 1,
    page_size: int = 10,
) -> PageInfo:
    """对话日志列表。带上应用名称和这次对话的反馈情况。"""
    query = ChatSession.all()
    if app_id:
        query = query.filter(app_id=app_id)
    if keyword:
        query = query.filter(title__contains=keyword)
    sessions = await query.order_by("-id").offset((page_num - 1) * page_size).limit(page_size)
    total = await query.count()

    app_ids = {item.app_id for item in sessions}
    apps = await QaApp.filter(id__in=list(app_ids))
    app_map = {app.id: app.name for app in apps}

    session_ids = [item.id for item in sessions]
    messages = await ChatMessage.filter(session_id__in=session_ids, role="assistant")
    message_ids = [message.id for message in messages]
    feedbacks = await MessageFeedback.filter(message_id__in=message_ids)
    message_session = {message.id: message.session_id for message in messages}
    # 统计每个会话被点了几次赞、几次踩。
    # 点踩多的会话优先看；点赞数一起带上，列表里才能看出这次对话到底有没有人反馈过
    like_count: dict[int, int] = {}
    # 统计每个会话被点了几次踩，点踩多的会话优先看
    dislike_count: dict[int, int] = {}
    for feedback in feedbacks:
        session_id = message_session.get(feedback.message_id)
        if not session_id:
            continue
        if feedback.feedback_type == "点踩":
            dislike_count[session_id] = dislike_count.get(session_id, 0) + 1
        elif feedback.feedback_type == "点赞":
            like_count[session_id] = like_count.get(session_id, 0) + 1

    return PageInfo(
        total=total,
        list=[
            {
                "id": item.id,
                "session_no": item.session_no,
                "app_id": item.app_id,
                "app_name": app_map.get(item.app_id),
                "title": item.title,
                "message_count": item.message_count,
                "source": item.source,
                "like_count": like_count.get(item.id, 0),
                "dislike_count": dislike_count.get(item.id, 0),
                "create_time": item.create_time,
            }
            for item in sessions
        ],
    )
