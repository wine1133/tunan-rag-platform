"""多轮问答。

两种模式共用同一套会话、消息、引用来源的落库逻辑，区别只在中间那一段：

    agent_enabled = 否   走第 15-19 章的直线链路：检索一次 → 流式生成
    agent_enabled = 是   走第 22 章的状态图：模型自己决定要不要重新检索

流式输出用 SSE。前端拿到的事件有四种：
    reference  引用来源，在正文开始前先发过去，页面可以先把来源渲染出来
    progress   状态图的节点进度，只有 Agentic 模式发，页面据此显示当前跑到哪一步
    delta      正文增量，一个字一个字往外吐
    done       结束，带上消息 ID 和耗时，前端拿它去做点赞点踩
"""

import asyncio
import json
import uuid
from typing import AsyncGenerator

from ai import model_factory, prompt_loader
from ai.graph import build_context
from common.exception_handler import CustomException
from common.times import cost_millis, now
from models import (
    ChatMessage,
    ChatSession,
    KnowledgeBase,
    MessageFeedback,
    MessageReference,
    QaApp,
    QaAppKb,
)
from service import agent_service, retrieval_service

ERROR_MAX_LENGTH = 500


def _dump(value) -> str:
    return json.dumps(value, ensure_ascii=False, default=str)


def _event(event_type: str, payload: dict) -> dict:
    """组装一条 SSE 事件。sse-starlette 按 event 和 data 两个键发出去。"""
    return {"event": event_type, "data": _dump(payload)}


async def _load_app(app_id: int) -> tuple[QaApp, list[int]]:
    app = await QaApp.get_or_none(id=app_id)
    if app is None:
        raise CustomException("未找到问答应用")
    if app.status != "正常":
        raise CustomException("该应用已停用")
    relations = await QaAppKb.filter(app_id=app_id)
    kb_ids = [item.kb_id for item in relations]
    if not kb_ids:
        raise CustomException("该应用还没有挂载知识库，请先到问答应用里配置")
    # 停用的知识库不参与检索
    bases = await KnowledgeBase.filter(id__in=kb_ids, status="正常")
    usable = [kb.id for kb in bases]
    if not usable:
        raise CustomException("该应用挂载的知识库都已停用")
    return app, usable


async def open_session(app_id: int, user_id: int | None, source: str = "管理端") -> dict:
    """新建一个会话。前端在用户发第一条消息前调它。"""
    app, _ = await _load_app(app_id)
    session = await ChatSession.create(
        session_no=uuid.uuid4().hex,
        app_id=app.id,
        user_id=user_id,
        source=source,
    )
    return {"session_id": session.id, "session_no": session.session_no, "app_name": app.name}


async def assert_session_access(session_id: int, user) -> ChatSession:
    """取会话并校验访问权限。

    用户端和管理端走的是同一批接口，session_id 只是个自增数字，
    不校验的话把 id 改一改就能读到别人的对话、甚至往别人的会话里提问。
    管理员要在对话日志里看所有人的会话，所以只拦普通用户。
    """
    session = await ChatSession.get_or_none(id=session_id)
    if session is None:
        raise CustomException("未找到会话")
    if user is not None and user.role != "ADMIN" and session.user_id != user.id:
        raise CustomException("无权访问该会话")
    return session


async def _load_history(session_id: int, max_history: int) -> list[dict]:
    """取最近几轮对话，按时间正序返回。

    只取 max_history 条，太多既撑上下文又拖慢速度。
    取的时候按 id 倒序取再反转，才能拿到"最近的几条"而不是"最早的几条"。
    """
    if max_history <= 0:
        return []
    messages = await ChatMessage.filter(session_id=session_id).order_by("-id").limit(max_history)
    return [
        {"role": message.role, "content": message.content or ""}
        for message in reversed(messages)
    ]


async def _save_references(message_id: int, results: list[dict]) -> None:
    """把引用来源写进 message_reference。

    存的是内容快照：片段以后可能被改被删，但用户当时看到的答案是基于那一版生成的。
    """
    for rank, item in enumerate(results, start=1):
        await MessageReference.create(
            message_id=message_id,
            chunk_id=item.get("chunk_id"),
            document_id=item.get("document_id"),
            chunk_content=item.get("content"),
            score=item.get("score"),
            rank_no=rank,
            retrieval_source=item.get("source"),
        )


def _reference_payload(results: list[dict]) -> list[dict]:
    """发给前端的引用来源，正文太长时截断，弹窗里再看全文。"""
    return [
        {
            "rank_no": rank,
            "chunk_id": item.get("chunk_id"),
            "document_id": item.get("document_id"),
            "score": item.get("score"),
            "content": (item.get("content") or "")[:300],
        }
        for rank, item in enumerate(results, start=1)
    ]


async def stream_chat(
    session_id: int,
    question: str,
    user_id: int | None = None,
) -> AsyncGenerator[dict, None]:
    """一次问答的完整流程，边跑边往外吐 SSE 事件。"""
    if not question or not question.strip():
        raise CustomException("请输入问题")
    session = await ChatSession.get_or_none(id=session_id)
    if session is None:
        raise CustomException("未找到会话")
    app, kb_ids = await _load_app(session.app_id)
    started = now()

    # 先落用户这条消息，哪怕后面失败了，提问也留在对话记录里
    user_message = await ChatMessage.create(
        session_id=session_id, role="user", content=question.strip()
    )
    # 会话标题取首条提问，列表页靠它认出这是哪次对话
    if not session.title:
        await ChatSession.filter(id=session_id).update(title=question.strip()[:100])

    history = await _load_history(session_id, app.max_history)
    # 刚落库的这条也在里面，去掉它，它就是当前要回答的问题
    history = [item for item in history if item["content"] != question.strip()]

    assistant_message = await ChatMessage.create(session_id=session_id, role="assistant", content="")
    try:
        if app.agent_enabled == "是":
            async for event in _run_agent(app, kb_ids, question, history, session, assistant_message, user_id):
                yield event
        else:
            async for event in _run_direct(app, kb_ids, question, history, session, assistant_message):
                yield event
        await ChatSession.filter(id=session_id).update(
            message_count=await ChatMessage.filter(session_id=session_id).count()
        )
        yield _event(
            "done",
            {
                "message_id": assistant_message.id,
                "user_message_id": user_message.id,
                "cost_millis": cost_millis(started),
            },
        )
    except Exception as exc:
        message = exc.message if isinstance(exc, CustomException) else f"回答失败：{exc}"
        await ChatMessage.filter(id=assistant_message.id).update(
            error_message=message[:ERROR_MAX_LENGTH],
            cost_millis=cost_millis(started),
        )
        # 失败也要发个事件，否则前端一直转圈
        yield _event("error", {"message": message})


async def _run_direct(
    app: QaApp,
    kb_ids: list[int],
    question: str,
    history: list[dict],
    session: ChatSession,
    assistant_message: ChatMessage,
) -> AsyncGenerator[dict, None]:
    """直线链路：检索一次，流式生成。"""
    started = now()
    strategy = await retrieval_service.load_strategy(app.retrieval_strategy_id)
    outcome = await retrieval_service.retrieve(kb_ids, question, strategy, history=history)
    results = outcome["results"]

    if not results:
        # 检索不到就走兜底话术，不让模型硬编
        answer = app.empty_answer or "知识库中未找到相关内容。"
        await ChatMessage.filter(id=assistant_message.id).update(
            content=answer,
            rewritten_query=outcome["queries"][-1],
            strategy_snapshot=_dump(strategy),
            finish_reason="没有召回",
            cost_millis=cost_millis(started),
        )
        yield _event("delta", {"text": answer})
        return

    await _save_references(assistant_message.id, results)
    # 引用先发过去，页面可以在正文还没生成完时就把来源渲染出来
    yield _event("reference", {"references": _reference_payload(results)})

    prompt = await prompt_loader.render(
        app.prompt_code or "RAG_ANSWER",
        context=build_context(results),
        question=question,
    )
    config = await model_factory.load_enabled(model_factory.CHAT)
    if app.chat_model_id:
        from models import AiModelConfig

        # 应用指定了模型就用指定的，指定的被删了退回默认
        specified = await AiModelConfig.get_or_none(id=app.chat_model_id)
        if specified is not None:
            config = specified
    model = model_factory.build_chat_model(config)

    pieces = []
    async for chunk in model.astream(prompt):
        text = str(chunk.content or "")
        if not text:
            continue
        pieces.append(text)
        yield _event("delta", {"text": text})
    answer = "".join(pieces)
    await ChatMessage.filter(id=assistant_message.id).update(
        content=answer,
        rewritten_query=outcome["queries"][-1],
        strategy_snapshot=_dump(strategy),
        finish_reason="正常回答",
        cost_millis=cost_millis(started),
    )


async def _run_agent(
    app: QaApp,
    kb_ids: list[int],
    question: str,
    history: list[dict],
    session: ChatSession,
    assistant_message: ChatMessage,
    user_id: int | None,
) -> AsyncGenerator[dict, None]:
    """Agentic 链路：跑状态图，跑完一次性把答案发出去。

    状态图中间要反复判断和重试，没法边跑边确定最终答案，
    所以这条路不做逐字流式，跑完整段发出去。

    正文虽然不能流式，但每跑完一个节点会发一条 progress 事件，
    页面靠它显示"正在判断召回是否相关"这类进度，不至于干等十几秒。
    """
    started = now()
    # 状态图在 ainvoke 内部跑，节点回调没法直接 yield 出去，
    # 用一个队列把回调转成事件：回调往里塞，下面的循环取出来发给前端
    progress_queue: asyncio.Queue = asyncio.Queue()

    def on_progress(node: str, name: str, index: int, detail: dict) -> None:
        progress_queue.put_nowait(
            {"node": node, "name": name, "index": index, "detail": detail or {}}
        )

    task = asyncio.create_task(
        agent_service.run(
            kb_ids,
            question,
            user_id=user_id,
            app_id=app.id,
            session_id=session.id,
            history=history,
            on_progress=on_progress,
        )
    )
    # 状态图没跑完之前，把队列里的进度不断发出去
    while not task.done() or not progress_queue.empty():
        try:
            step = await asyncio.wait_for(progress_queue.get(), timeout=0.3)
        except asyncio.TimeoutError:
            continue
        yield _event("progress", step)
    outcome = await task
    references = [
        {
            "chunk_id": item["chunk_id"],
            "document_id": item.get("document_id"),
            "score": item.get("score"),
            "content": item.get("content"),
            "source": "Agentic检索",
        }
        for item in outcome["references"]
    ]
    if references:
        await _save_references(assistant_message.id, references)
        yield _event("reference", {"references": _reference_payload(references)})
    # 把这次跑了几步、检索了几次也发给前端，页面上能显示 Agent 的工作量
    yield _event(
        "agent",
        {
            "run_id": outcome["run_id"],
            "total_step": outcome["total_step"],
            "retrieve_count": outcome["retrieve_count"],
            "retry_count": outcome["retry_count"],
            "finish_reason": outcome["finish_reason"],
        },
    )
    yield _event("delta", {"text": outcome["answer"]})
    await ChatMessage.filter(id=assistant_message.id).update(
        content=outcome["answer"],
        agent_run_id=outcome["run_id"],
        finish_reason=outcome["finish_reason"],
        cost_millis=cost_millis(started),
    )


async def delete_session(session_id: int, user) -> None:
    """删掉一个会话，连同它的消息、引用来源和反馈一起清掉。

    这几张表是靠 session_id / message_id 串起来的，不删干净会留下
    查不到归属的消息和反馈，第 25 章的对话日志和反馈统计都会被它们污染。
    删除顺序要从最里层往外删：引用和反馈挂在消息上，消息挂在会话上。
    """
    await assert_session_access(session_id, user)
    message_ids = [
        message.id for message in await ChatMessage.filter(session_id=session_id).only("id")
    ]
    if message_ids:
        await MessageReference.filter(message_id__in=message_ids).delete()
        await MessageFeedback.filter(message_id__in=message_ids).delete()
        await ChatMessage.filter(session_id=session_id).delete()
    await ChatSession.filter(id=session_id).delete()


async def select_messages(session_id: int) -> list[dict]:
    """一个会话的完整消息列表，含每条回答的引用来源。"""
    messages = await ChatMessage.filter(session_id=session_id).order_by("id")
    message_ids = [message.id for message in messages]
    references = await MessageReference.filter(message_id__in=message_ids).order_by("rank_no")
    grouped: dict[int, list] = {}
    for reference in references:
        grouped.setdefault(reference.message_id, []).append(
            {
                "rank_no": reference.rank_no,
                "chunk_id": reference.chunk_id,
                "document_id": reference.document_id,
                "score": float(reference.score) if reference.score is not None else None,
                "content": reference.chunk_content,
            }
        )
    return [
        {
            "id": message.id,
            "role": message.role,
            "content": message.content,
            "rewritten_query": message.rewritten_query,
            "agent_run_id": message.agent_run_id,
            "finish_reason": message.finish_reason,
            "error_message": message.error_message,
            "cost_millis": message.cost_millis,
            "create_time": message.create_time,
            "references": grouped.get(message.id, []),
        }
        for message in messages
    ]


async def select_sessions(app_id: int | None = None, user_id: int | None = None, page_num: int = 1, page_size: int = 10):
    """会话列表。"""
    from common.result import PageInfo

    query = ChatSession.all()
    if app_id:
        query = query.filter(app_id=app_id)
    if user_id:
        query = query.filter(user_id=user_id)
    sessions = await query.order_by("-id").offset((page_num - 1) * page_size).limit(page_size)
    total = await query.count()
    return PageInfo(
        total=total,
        list=[
            {
                "id": item.id,
                "session_no": item.session_no,
                "app_id": item.app_id,
                "title": item.title,
                "message_count": item.message_count,
                "source": item.source,
                "create_time": item.create_time,
            }
            for item in sessions
        ],
    )
