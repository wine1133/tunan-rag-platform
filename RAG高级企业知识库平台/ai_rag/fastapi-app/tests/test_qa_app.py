"""问答应用与多轮问答测试。

应用配置的 CRUD 全部可以直接测；流式问答里的检索和模型调用换成假实现，
验证的是会话、消息、引用来源的落库和兜底分支。
"""

import json

import pytest

from ai import model_factory
from models import ChatMessage, ChatSession, KnowledgeBase, MessageReference, QaApp, QaAppKb
from service import chat_service, retrieval_service

APP_NAME = "测试问答应用-单元测试专用"
KB_NAME = "测试问答库-单元测试专用"


@pytest.fixture()
async def qa_env(db):
    """建一个知识库和一个挂着它的问答应用。"""
    kb = await KnowledgeBase.create(name=KB_NAME, status="正常")
    app = await QaApp.create(
        name=APP_NAME,
        app_code="unittestcode01",
        prompt_code="RAG_ANSWER",
        agent_enabled="否",
        max_history=4,
        empty_answer="知识库中未找到相关内容。",
        status="正常",
    )
    await QaAppKb.create(app_id=app.id, kb_id=kb.id)

    yield {"kb": kb, "app": app}

    sessions = await ChatSession.filter(app_id=app.id)
    session_ids = [item.id for item in sessions]
    messages = await ChatMessage.filter(session_id__in=session_ids)
    await MessageReference.filter(message_id__in=[item.id for item in messages]).delete()
    await ChatMessage.filter(session_id__in=session_ids).delete()
    await ChatSession.filter(app_id=app.id).delete()
    await QaAppKb.filter(app_id=app.id).delete()
    await QaApp.filter(id=app.id).delete()
    await KnowledgeBase.filter(id=kb.id).delete()


class FakeChunk:
    def __init__(self, content):
        self.content = content


class FakeStreamModel:
    """把一句话按字吐出来的假模型，用来验证流式分片。"""

    def __init__(self, text):
        self.text = text

    async def astream(self, prompt):
        for char in self.text:
            yield FakeChunk(char)


@pytest.fixture()
def fake_chain(monkeypatch):
    """把检索和对话模型都换成假实现。"""
    holder = {"results": [], "answer": "质保时长为 24 个月。"}

    async def fake_retrieve(kb_ids, query, strategy, document_ids=None, history=None):
        return {
            "query": query,
            "queries": [query],
            "strategy_id": strategy["id"],
            "strategy_name": strategy["name"],
            "results": holder["results"],
            "stages": [],
            "cost_millis": 1,
        }

    async def fake_load_enabled(model_type):
        return object()

    def fake_build(config, temperature=0.0):
        return FakeStreamModel(holder["answer"])

    monkeypatch.setattr(retrieval_service, "retrieve", fake_retrieve)
    monkeypatch.setattr(model_factory, "load_enabled", fake_load_enabled)
    monkeypatch.setattr(model_factory, "build_chat_model", fake_build)

    def setup(results=None, answer=None):
        if results is not None:
            holder["results"] = results
        if answer is not None:
            holder["answer"] = answer
        return holder

    return setup


async def _collect(session_id, question):
    events = []
    async for event in chat_service.stream_chat(session_id, question, user_id=-1):
        events.append({"event": event["event"], "data": json.loads(event["data"])})
    return events


def test_app_requires_knowledge_base(client, admin_headers):
    """应用必须挂载至少一个知识库。"""
    body = client.post(
        "/qaApp/add",
        json={"name": "没挂库的应用", "kb_ids": []},
        headers=admin_headers,
    ).json()
    assert body["code"] == "500"
    assert body["msg"] == "请至少挂载一个知识库"


def test_max_history_range_is_checked(client, admin_headers):
    """历史消息条数有取值范围。"""
    body = client.post(
        "/qaApp/add",
        json={"name": "历史超范围", "kb_ids": [1], "max_history": 50},
        headers=admin_headers,
    ).json()
    assert body["code"] == "500"
    assert body["msg"] == "历史消息条数取值范围是 0 到 20"


async def test_open_session_creates_record(qa_env):
    """开会话时建一条记录，标题这时还是空的。"""
    outcome = await chat_service.open_session(qa_env["app"].id, user_id=-1)

    session = await ChatSession.get_or_none(id=outcome["session_id"])
    assert session is not None
    assert session.title is None
    assert outcome["app_name"] == APP_NAME


async def test_stream_chat_emits_reference_delta_done(qa_env, fake_chain):
    """一次正常问答依次发出引用、正文增量、结束三类事件。"""
    fake_chain(results=[{"chunk_id": 1, "document_id": 1, "score": 0.9, "content": "质保时长为 24 个月。", "source": "向量检索"}])
    session = await chat_service.open_session(qa_env["app"].id, user_id=-1)

    events = await _collect(session["session_id"], "保修期多久")

    kinds = [item["event"] for item in events]
    assert kinds[0] == "reference"
    assert "delta" in kinds
    assert kinds[-1] == "done"
    # 正文被拆成了很多个 delta，拼起来是完整答案
    answer = "".join(item["data"]["text"] for item in events if item["event"] == "delta")
    assert answer == "质保时长为 24 个月。"


async def test_messages_and_references_are_saved(qa_env, fake_chain):
    """提问和回答各落一条消息，引用来源存的是内容快照。"""
    fake_chain(results=[{"chunk_id": 7, "document_id": 3, "score": 0.88, "content": "质保 24 个月。", "source": "向量检索"}])
    session = await chat_service.open_session(qa_env["app"].id, user_id=-1)

    await _collect(session["session_id"], "保修期多久")

    messages = await chat_service.select_messages(session["session_id"])
    assert [item["role"] for item in messages] == ["user", "assistant"]
    assert messages[0]["content"] == "保修期多久"
    assert messages[1]["content"] == "质保时长为 24 个月。"
    assert messages[1]["finish_reason"] == "正常回答"
    # 引用来源挂在回答那条消息上
    assert len(messages[1]["references"]) == 1
    assert messages[1]["references"][0]["chunk_id"] == 7
    assert messages[1]["references"][0]["content"] == "质保 24 个月。"


async def test_session_title_comes_from_first_question(qa_env, fake_chain):
    """会话标题取首条提问。"""
    fake_chain(results=[{"chunk_id": 1, "content": "内容", "source": "向量检索"}])
    session = await chat_service.open_session(qa_env["app"].id, user_id=-1)

    await _collect(session["session_id"], "第一个问题")
    await _collect(session["session_id"], "第二个问题")

    record = await ChatSession.get_or_none(id=session["session_id"])
    assert record.title == "第一个问题"
    # 四条消息：两问两答
    assert record.message_count == 4


async def test_empty_recall_uses_fallback_answer(qa_env, fake_chain):
    """检索不到资料时走应用配置的兜底话术，不让模型硬编。"""
    fake_chain(results=[])
    session = await chat_service.open_session(qa_env["app"].id, user_id=-1)

    events = await _collect(session["session_id"], "公司年会在哪办")

    kinds = [item["event"] for item in events]
    # 没有引用事件
    assert "reference" not in kinds
    answer = "".join(item["data"]["text"] for item in events if item["event"] == "delta")
    assert answer == "知识库中未找到相关内容。"

    messages = await chat_service.select_messages(session["session_id"])
    assert messages[1]["finish_reason"] == "没有召回"
    assert messages[1]["references"] == []


async def test_disabled_app_is_rejected(qa_env, fake_chain):
    """应用停用后不能再开会话。"""
    await QaApp.filter(id=qa_env["app"].id).update(status="停用")
    with pytest.raises(Exception) as excinfo:
        await chat_service.open_session(qa_env["app"].id, user_id=-1)
    assert "已停用" in str(excinfo.value)


async def test_app_without_usable_kb_is_rejected(qa_env, fake_chain):
    """挂载的知识库全部停用时给出人话提示。"""
    await KnowledgeBase.filter(id=qa_env["kb"].id).update(status="停用")
    with pytest.raises(Exception) as excinfo:
        await chat_service.open_session(qa_env["app"].id, user_id=-1)
    assert "都已停用" in str(excinfo.value)


async def test_empty_question_is_rejected(qa_env, fake_chain):
    """问题为空时给出人话提示。"""
    session = await chat_service.open_session(qa_env["app"].id, user_id=-1)
    with pytest.raises(Exception) as excinfo:
        await _collect(session["session_id"], "   ")
    assert "请输入问题" in str(excinfo.value)


async def test_history_is_limited(qa_env, fake_chain):
    """带进模型的历史消息条数受 max_history 限制。"""
    fake_chain(results=[{"chunk_id": 1, "content": "内容", "source": "向量检索"}])
    session = await chat_service.open_session(qa_env["app"].id, user_id=-1)
    for index in range(5):
        await _collect(session["session_id"], f"第 {index} 个问题")

    history = await chat_service._load_history(session["session_id"], qa_env["app"].max_history)
    assert len(history) == qa_env["app"].max_history
    # 取到的是最近的几条而不是最早的几条
    assert history[-1]["content"] == "质保时长为 24 个月。"

class FakeUser:
    """只带 id 和 role 两个字段的假用户，够 assert_session_access 判断了。"""

    def __init__(self, user_id, role="USER"):
        self.id = user_id
        self.role = role


async def test_other_user_cannot_access_session(qa_env):
    """普通用户拿不到别人的会话，用户端和管理端共用接口，这里是唯一的拦截点。"""
    session = await chat_service.open_session(qa_env["app"].id, user_id=1001, source="用户端")

    with pytest.raises(Exception) as excinfo:
        await chat_service.assert_session_access(session["session_id"], FakeUser(1002))
    assert "无权访问" in str(excinfo.value)


async def test_owner_and_admin_can_access_session(qa_env):
    """会话本人能访问，管理员看对话日志也要能访问所有人的会话。"""
    session = await chat_service.open_session(qa_env["app"].id, user_id=1001, source="用户端")

    owner_view = await chat_service.assert_session_access(session["session_id"], FakeUser(1001))
    admin_view = await chat_service.assert_session_access(
        session["session_id"], FakeUser(9999, role="ADMIN")
    )
    assert owner_view.id == session["session_id"]
    assert admin_view.id == session["session_id"]


async def test_delete_session_removes_messages_and_references(qa_env, fake_chain):
    """删会话时消息和引用来源一起清掉，不留查不到归属的脏数据。"""
    fake_chain(results=[{"chunk_id": 1, "content": "内容", "source": "向量检索"}])
    session = await chat_service.open_session(qa_env["app"].id, user_id=1001, source="用户端")
    session_id = session["session_id"]
    await _collect(session_id, "质保多久")
    message_ids = [item.id for item in await ChatMessage.filter(session_id=session_id)]
    assert message_ids
    assert await MessageReference.filter(message_id__in=message_ids).count() > 0

    await chat_service.delete_session(session_id, FakeUser(1001))

    assert await ChatSession.filter(id=session_id).count() == 0
    assert await ChatMessage.filter(session_id=session_id).count() == 0
    assert await MessageReference.filter(message_id__in=message_ids).count() == 0


async def test_delete_session_rejects_other_user(qa_env):
    """别人的会话删不掉，归属校验和读消息共用同一段。"""
    session = await chat_service.open_session(qa_env["app"].id, user_id=1001, source="用户端")

    with pytest.raises(Exception) as excinfo:
        await chat_service.delete_session(session["session_id"], FakeUser(1002))
    assert "无权访问" in str(excinfo.value)

