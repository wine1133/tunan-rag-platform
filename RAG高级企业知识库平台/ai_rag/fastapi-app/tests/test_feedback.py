"""对话日志与用户反馈测试。"""

import pytest

from models import ChatMessage, ChatSession, MessageFeedback, QaApp, QaAppKb, User
from service import feedback_service

APP_NAME = "测试反馈应用-单元测试专用"


@pytest.fixture()
async def feedback_env(db):
    """造一个应用、一个会话、一问一答，用完删掉。"""
    app = await QaApp.create(name=APP_NAME, app_code="unittestfb0001", status="正常")
    session = await ChatSession.create(session_no="unittestfbsession", app_id=app.id, title="保修期多久")
    question = await ChatMessage.create(session_id=session.id, role="user", content="保修期多久")
    answer = await ChatMessage.create(session_id=session.id, role="assistant", content="质保 24 个月。")
    admin = await User.get_or_none(username="admin")

    yield {"app": app, "session": session, "question": question, "answer": answer, "admin": admin}

    await MessageFeedback.filter(message_id__in=[question.id, answer.id]).delete()
    await ChatMessage.filter(session_id=session.id).delete()
    await ChatSession.filter(id=session.id).delete()
    await QaAppKb.filter(app_id=app.id).delete()
    await QaApp.filter(id=app.id).delete()


async def test_submit_creates_feedback(feedback_env):
    """点踩会留下一条反馈记录，默认还没沉淀成评测用例。"""
    await feedback_service.submit(feedback_env["admin"], feedback_env["answer"].id, "点踩", "答非所问")

    record = await MessageFeedback.get_or_none(message_id=feedback_env["answer"].id)
    assert record.feedback_type == "点踩"
    assert record.reason == "答非所问"
    assert record.converted == "否"


async def test_second_submit_overwrites(feedback_env):
    """同一个人改主意时覆盖上一次，不留两条。"""
    await feedback_service.submit(feedback_env["admin"], feedback_env["answer"].id, "点踩", "答非所问")
    await feedback_service.submit(feedback_env["admin"], feedback_env["answer"].id, "点赞", None)

    records = await MessageFeedback.filter(message_id=feedback_env["answer"].id)
    assert len(records) == 1
    assert records[0].feedback_type == "点赞"
    assert records[0].reason is None


async def test_feedback_on_question_is_rejected(feedback_env):
    """只能对回答打分，给自己的提问点赞没有意义。"""
    with pytest.raises(Exception) as excinfo:
        await feedback_service.submit(feedback_env["admin"], feedback_env["question"].id, "点赞", None)
    assert "只能对回答内容进行反馈" in str(excinfo.value)


async def test_invalid_feedback_type_is_rejected(feedback_env):
    """反馈类型只允许点赞和点踩。"""
    with pytest.raises(Exception) as excinfo:
        await feedback_service.submit(feedback_env["admin"], feedback_env["answer"].id, "无所谓", None)
    assert "反馈类型参数错误" in str(excinfo.value)


async def test_select_by_message_groups_counts(feedback_env):
    """按消息批量取反馈，返回每条的点赞点踩数。"""
    await feedback_service.submit(feedback_env["admin"], feedback_env["answer"].id, "点赞", None)

    grouped = await feedback_service.select_by_message([feedback_env["answer"].id])
    assert grouped[feedback_env["answer"].id]["点赞"] == 1
    assert grouped[feedback_env["answer"].id]["点踩"] == 0


async def test_select_page_carries_question_and_answer(feedback_env):
    """反馈列表带上对应的问题和回答，不用来回跳会话。"""
    await feedback_service.submit(feedback_env["admin"], feedback_env["answer"].id, "点踩", "答非所问")

    page = await feedback_service.select_page(feedback_type="点踩", page_num=1, page_size=10)
    target = [item for item in page.list if item["message_id"] == feedback_env["answer"].id][0]
    assert target["question"] == "保修期多久"
    assert target["answer"] == "质保 24 个月。"
    assert target["converted"] == "否"


async def test_summary_counts_pending_convert(feedback_env):
    """总览里统计还没沉淀成评测用例的点踩数。"""
    await feedback_service.submit(feedback_env["admin"], feedback_env["answer"].id, "点踩", None)

    stats = await feedback_service.summary()
    assert stats["disliked"] >= 1
    assert stats["pending_convert"] >= 1
    assert stats["satisfaction"] is not None


async def test_sessions_carry_dislike_count(feedback_env):
    """对话日志列表统计每个会话被点了几次踩。"""
    await feedback_service.submit(feedback_env["admin"], feedback_env["answer"].id, "点踩", None)

    page = await feedback_service.select_sessions_with_app(app_id=feedback_env["app"].id, page_num=1, page_size=10)
    target = [item for item in page.list if item["id"] == feedback_env["session"].id][0]
    assert target["app_name"] == APP_NAME
    assert target["dislike_count"] == 1
    assert target["title"] == "保修期多久"

class FakeUser:
    """只带 id 和 role 的假用户，反馈校验用到的就这两个字段。"""

    def __init__(self, user_id, role="USER"):
        self.id = user_id
        self.role = role


async def test_other_user_cannot_feedback(feedback_env):
    """会话不属于自己时不能打分，反馈数据后面要沉淀成评测用例。"""
    await ChatSession.filter(id=feedback_env["session"].id).update(user_id=1001)

    with pytest.raises(Exception) as excinfo:
        await feedback_service.submit(FakeUser(1002), feedback_env["answer"].id, "点赞", None)
    assert "无权对该回答" in str(excinfo.value)


async def test_select_by_message_marks_my_feedback(feedback_env):
    """传了 user_id 时，mine 带回这个人自己点的类型，用户端翻历史对话靠它回填按钮。"""
    await feedback_service.submit(feedback_env["admin"], feedback_env["answer"].id, "点踩", None)

    grouped = await feedback_service.select_by_message(
        [feedback_env["answer"].id], feedback_env["admin"].id
    )
    assert grouped[feedback_env["answer"].id]["mine"] == "点踩"
