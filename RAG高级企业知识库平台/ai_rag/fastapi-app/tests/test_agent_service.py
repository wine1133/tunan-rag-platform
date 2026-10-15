"""Agentic RAG 执行落库测试。

图的分支逻辑在 test_agent_graph.py 里测过了，这里测的是外面这一层：
运行记录、步骤记录、引用来源回查、以及"没检索过就算失败"这条反查。
"""

import pytest

from ai import graph as agent_graph
from ai import model_factory, tools
from common.exception_handler import CustomException
from models import AgentRun, AgentStep, KnowledgeBase, KnowledgeChunk, KnowledgeDocument
from service import agent_service

KB_NAME = "测试Agent库-单元测试专用"


class FakeReply:
    def __init__(self, content):
        self.content = content


class ScriptedModel:
    def __init__(self, script):
        self.script = list(script)

    async def ainvoke(self, prompt):
        return FakeReply(self.script.pop(0) if self.script else "有支撑")


@pytest.fixture()
async def agent_env(monkeypatch, db):
    """建真实的知识库和片段，把模型和检索工具换成假实现。"""
    kb = await KnowledgeBase.create(name=KB_NAME, status="正常")
    doc = await KnowledgeDocument.create(kb_id=kb.id, name="Agent测试文档.txt")
    chunk = await KnowledgeChunk.create(
        kb_id=kb.id,
        document_id=doc.id,
        chunk_index=0,
        chunk_type="普通块",
        content="质保时长为 24 个月。",
        char_count=11,
        page_no=2,
    )
    holder = {"model": None, "results": [{"chunk_id": chunk.id, "document_id": doc.id, "score": 0.9, "content": chunk.content}]}

    async def fake_load_enabled(model_type):
        return object()

    def fake_build(config, temperature=0.0):
        return holder["model"]

    async def fake_invoke(tool_code, params, run_id=None, step_id=None):
        return {"count": len(holder["results"]), "results": holder["results"]}

    monkeypatch.setattr(model_factory, "load_enabled", fake_load_enabled)
    monkeypatch.setattr(model_factory, "build_chat_model", fake_build)
    monkeypatch.setattr(tools, "invoke", fake_invoke)

    def setup(script, results=None):
        holder["model"] = ScriptedModel(script)
        if results is not None:
            holder["results"] = results
        return holder

    yield {"kb": kb, "doc": doc, "chunk": chunk, "setup": setup}

    await AgentStep.filter(run_id__in=[item.id for item in await AgentRun.filter(user_id=-1)]).delete()
    await AgentRun.filter(user_id=-1).delete()
    await KnowledgeChunk.filter(kb_id=kb.id).delete()
    await KnowledgeDocument.filter(id=doc.id).delete()
    await KnowledgeBase.filter(id=kb.id).delete()


async def test_run_writes_run_and_steps(agent_env):
    """跑完一次留下一条运行记录和若干条步骤记录。"""
    agent_env["setup"](["相关", "质保 24 个月。", "有支撑"])

    outcome = await agent_service.run([agent_env["kb"].id], "保修期多久", user_id=-1)

    assert outcome["finish_reason"] == "正常回答"
    assert outcome["retrieve_count"] == 1
    assert outcome["total_step"] == 5

    run_record = await AgentRun.get_or_none(id=outcome["run_id"])
    assert run_record.run_status == "已完成"
    assert run_record.total_step == 5
    assert run_record.retrieve_count == 1
    assert run_record.cost_millis is not None

    steps = await AgentStep.filter(run_id=outcome["run_id"]).order_by("step_index")
    assert [step.node_name for step in steps] == ["rewrite", "retrieve", "grade", "generate", "check"]
    # 步骤序号从 1 开始连续递增，时间线按它排序
    assert [step.step_index for step in steps] == [1, 2, 3, 4, 5]
    # 检索那一步记下了工具编码，能和 tool_call_log 对上
    assert steps[1].tool_code == "search_knowledge"


async def test_references_come_from_database(agent_env):
    """引用来源按 chunk_id 回查数据库，内容以库里的为准。"""
    agent_env["setup"](["相关", "答案", "有支撑"])

    outcome = await agent_service.run([agent_env["kb"].id], "保修期多久", user_id=-1)

    assert len(outcome["references"]) == 1
    reference = outcome["references"][0]
    assert reference["chunk_id"] == agent_env["chunk"].id
    # 正文来自数据库，不是模型说的
    assert reference["content"] == agent_env["chunk"].content
    assert reference["page_no"] == 2
    assert reference["rank_no"] == 1


async def test_deleted_chunk_is_skipped_in_references(agent_env):
    """片段已被删时跳过，不展示一条点不开的来源。"""
    agent_env["setup"](
        ["相关", "答案", "有支撑"],
        results=[{"chunk_id": 999999, "document_id": 1, "score": 0.9, "content": "已经不存在的片段"}],
    )

    outcome = await agent_service.run([agent_env["kb"].id], "保修期多久", user_id=-1)

    assert outcome["references"] == []


async def test_fallback_clears_references(agent_env):
    """走兜底时不挂引用来源。"""
    agent_env["setup"](["不相关"] * 20)

    outcome = await agent_service.run([agent_env["kb"].id], "公司年会在哪办", user_id=-1)

    assert outcome["answer"] == "知识库中未找到相关内容。"
    assert outcome["finish_reason"] == "召回不相关"
    assert outcome["references"] == []
    # 兜底也是正常结束，运行状态是已完成而不是失败
    run_record = await AgentRun.get_or_none(id=outcome["run_id"])
    assert run_record.run_status == "已完成"


async def test_run_without_retrieve_is_marked_failed(agent_env, monkeypatch):
    """一次检索都没发生时判定失败，不把编出来的答案返回给用户。"""
    agent_env["setup"](["相关", "答案", "有支撑"])

    # 把检索节点换成什么都不做，模拟"模型没调工具就直接回答"
    async def no_retrieve(state):
        return {"documents": [{"chunk_id": 1, "content": "凭空来的资料"}]}

    monkeypatch.setattr(agent_graph, "retrieve_node", no_retrieve)

    with pytest.raises(CustomException) as excinfo:
        await agent_service.run([agent_env["kb"].id], "保修期多久", user_id=-1)
    assert "没有发生任何检索" in excinfo.value.message

    # 失败的运行同样留下记录，能查到失败原因
    run_record = await AgentRun.filter(user_id=-1).order_by("-id").first()
    assert run_record.run_status == "运行失败"
    assert "没有发生任何检索" in run_record.error_message


async def test_empty_query_is_rejected(agent_env):
    """问题为空时给出人话提示，不建运行记录。"""
    with pytest.raises(CustomException) as excinfo:
        await agent_service.run([agent_env["kb"].id], "   ", user_id=-1)
    assert excinfo.value.message == "请输入问题"


async def test_select_steps_returns_timeline(agent_env):
    """步骤时间线接口返回运行概况和按序排列的步骤。"""
    agent_env["setup"](["相关", "答案", "有支撑"])
    outcome = await agent_service.run([agent_env["kb"].id], "保修期多久", user_id=-1)

    timeline = await agent_service.select_steps(outcome["run_id"])

    assert timeline["run"]["run_status"] == "已完成"
    assert len(timeline["steps"]) == 5
    assert timeline["steps"][0]["step_name"] == "准备检索问题"
    assert timeline["steps"][-1]["step_name"] == "校验答案是否有资料支撑"
