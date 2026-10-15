"""测试公共夹具。

登录一次拿到管理员 token，后面各章节的测试都靠它调受保护接口。

运行前提：MySQL 已启动，且已执行过 ai_rag.sql。

测试直接跑在开发库上，建的知识库、评测集、问答应用都会留在库里，
不清理的话跑几轮下来，页面上真实数据里混着几十条"测试XX-单元测试专用"。
所以本文件最后有一个跑完自动清扫的夹具，按名字后缀统一回收。
"""

import asyncio
import sys

import pytest
from fastapi.testclient import TestClient
from tortoise import Tortoise

from main import app
from settings import TORTOISE_ORM

# 测试数据的统一后缀。新写测试时，凡是会落库的名字都带上它，
# 跑完就会被下面的夹具自动清掉
TEST_MARK = "单元测试专用"


@pytest.fixture()
async def db():
    """给异步测试用的数据库连接。

    走接口的测试由 TestClient 负责建连接；
    直接调 service 或 ai 层函数的异步测试没有走接口，要自己初始化一次 Tortoise。
    """
    await Tortoise.init(config=TORTOISE_ORM)
    yield
    await Tortoise.close_connections()


@pytest.fixture()
def client():
    """带生命周期的测试客户端，进入时连数据库，退出时释放连接。"""
    with TestClient(app) as test_client:
        yield test_client


@pytest.fixture()
def admin_headers(client):
    """用初始化数据里的管理员账号登录，返回带 token 的请求头。"""
    response = client.post("/login", json={"username": "admin", "password": "123456"})
    body = response.json()
    assert body["code"] == "200", "管理员登录失败，请确认已执行 ai_rag.sql 且密码未被改过"
    return {"token": body["data"]["token"]}


async def _sweep() -> dict:
    """按名字后缀回收测试数据，返回各表删了多少条。

    删除顺序是从属表在前、主表在后：先删片段再删文档最后删知识库，
    反过来的话主表没了，从属表就成了查不到出处的孤儿数据。
    """
    await Tortoise.init(config=TORTOISE_ORM)
    from models import (
        AiModelConfig,
        ChatMessage,
        ChatSession,
        ChunkStrategy,
        EvalCase,
        EvalCaseResult,
        EvalDataset,
        EvalReport,
        EvalTask,
        FunctionTool,
        KnowledgeBase,
        KnowledgeChunk,
        KnowledgeDocument,
        MessageFeedback,
        MessageReference,
        PromptTemplate,
        QaApp,
        QaAppKb,
        RetrievalStrategy,
    )

    removed: dict[str, int] = {}

    async def drop(model, **filters):
        count = await model.filter(**filters).count()
        if count:
            await model.filter(**filters).delete()
            removed[model.__name__] = removed.get(model.__name__, 0) + count

    # 知识库：先片段、再文档、最后库本身
    kb_ids = [item.id for item in await KnowledgeBase.filter(name__contains=TEST_MARK)]
    if kb_ids:
        await drop(KnowledgeChunk, kb_id__in=kb_ids)
        await drop(KnowledgeDocument, kb_id__in=kb_ids)
        await drop(QaAppKb, kb_id__in=kb_ids)
        await drop(KnowledgeBase, id__in=kb_ids)

    # 评测集：用例、任务、任务下的结果和报告，最后是评测集
    dataset_ids = [item.id for item in await EvalDataset.filter(name__contains=TEST_MARK)]
    if dataset_ids:
        task_ids = [item.id for item in await EvalTask.filter(dataset_id__in=dataset_ids)]
        if task_ids:
            await drop(EvalCaseResult, task_id__in=task_ids)
            await drop(EvalReport, task_id__in=task_ids)
            await drop(EvalTask, id__in=task_ids)
        await drop(EvalCase, dataset_id__in=dataset_ids)
        await drop(EvalDataset, id__in=dataset_ids)

    # 问答应用：会话、消息、引用、反馈，最后是应用
    app_ids = [item.id for item in await QaApp.filter(name__contains=TEST_MARK)]
    if app_ids:
        session_ids = [item.id for item in await ChatSession.filter(app_id__in=app_ids)]
        if session_ids:
            message_ids = [item.id for item in await ChatMessage.filter(session_id__in=session_ids)]
            if message_ids:
                await drop(MessageReference, message_id__in=message_ids)
                await drop(MessageFeedback, message_id__in=message_ids)
                await drop(ChatMessage, id__in=message_ids)
            await drop(ChatSession, id__in=session_ids)
        await drop(QaAppKb, app_id__in=app_ids)
        await drop(QaApp, id__in=app_ids)

    # 剩下这些没有从属数据，按名字直接删
    for model in (ChunkStrategy, RetrievalStrategy, AiModelConfig, PromptTemplate):
        await drop(model, name__contains=TEST_MARK)
    # 工具表的名字列叫 tool_name，不是 name
    await drop(FunctionTool, tool_name__contains=TEST_MARK)
    # 文档可能不挂在测试库下（比如测试只建了文档没建库）
    await drop(KnowledgeDocument, name__contains=TEST_MARK)

    await Tortoise.close_connections()
    return removed


@pytest.fixture(scope="session", autouse=True)
def sweep_test_data():
    """整批测试跑完后，把测试数据从开发库里清掉。

    autouse 表示不用任何测试显式引用它，整个 session 自动生效；
    yield 之前什么都不做，之后才清扫，所以不影响测试本身的执行。
    """
    yield
    # Windows 默认的 ProactorEventLoop 关闭时 aiomysql 会报 Event loop is closed，
    # 和 main.py 里的处理一致，换成 SelectorEventLoop
    loop_factory = asyncio.SelectorEventLoop if sys.platform == "win32" else None
    removed = asyncio.run(_sweep(), loop_factory=loop_factory)
    if removed:
        detail = "、".join(f"{name} {count} 条" for name, count in removed.items())
        print(f"\n[测试数据清扫] {detail}")
