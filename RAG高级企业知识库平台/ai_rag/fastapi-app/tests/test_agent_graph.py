"""Agentic RAG 状态图测试。

图本身不碰数据库，节点里调模型和工具的地方全部换成假实现，
验证的是分支走向、防失控上限、兜底出口这些流程逻辑。
"""

import pytest

from ai import graph as agent_graph
from ai import model_factory, tools

DOCS = [
    {"chunk_id": 1, "document_id": 1, "score": 0.88, "content": "质保时长为 24 个月。"},
    {"chunk_id": 2, "document_id": 1, "score": 0.71, "content": "质保期内非人为损坏免费维修。"},
]


class FakeReply:
    def __init__(self, content):
        self.content = content


class ScriptedModel:
    """按脚本依次返回内容的假模型，用来编排各节点的判断结果。"""

    def __init__(self, script):
        self.script = list(script)
        self.prompts = []

    async def ainvoke(self, prompt):
        self.prompts.append(prompt)
        # 脚本用完之后重复最后一条，避免测试因为轮数多一次就崩
        content = self.script.pop(0) if self.script else "有支撑"
        return FakeReply(content)


@pytest.fixture()
def fake_env(monkeypatch, db):
    """把模型和检索工具都换成假实现，返回一个可配置的环境。"""
    holder = {"model": None, "documents": DOCS, "invoked": []}

    async def fake_load_enabled(model_type):
        return object()

    def fake_build(config, temperature=0.0):
        return holder["model"]

    async def fake_invoke(tool_code, params, run_id=None, step_id=None):
        holder["invoked"].append((tool_code, params))
        return {"count": len(holder["documents"]), "results": holder["documents"]}

    monkeypatch.setattr(model_factory, "load_enabled", fake_load_enabled)
    monkeypatch.setattr(model_factory, "build_chat_model", fake_build)
    monkeypatch.setattr(tools, "invoke", fake_invoke)

    def setup(script, documents=None):
        holder["model"] = ScriptedModel(script)
        if documents is not None:
            holder["documents"] = documents
        return holder

    return setup


async def _run(script, documents=None, fake_env=None, query="保修期多久"):
    env = fake_env(script, documents)
    steps = []

    async def on_step(node, name, request, response):
        steps.append({"node": node, "name": name, "request": request, "response": response})

    compiled = agent_graph.build_graph()
    state = await compiled.ainvoke(
        {
            "original_query": query,
            "query": query,
            "kb_ids": [1],
            "history": [],
            "retry_count": 0,
            "regenerate_count": 0,
            "retrieve_count": 0,
            "on_step": on_step,
        },
        {"recursion_limit": agent_graph.MAX_GRAPH_STEPS * 3},
    )
    return state, steps, env


def test_build_context_truncates_long_documents():
    """拼上下文时超过长度上限就截断，不让请求因为超长失败。"""
    long_docs = [{"content": "字" * 5000} for _ in range(3)]
    context = agent_graph.build_context(long_docs)
    assert len(context) <= agent_graph.MAX_CONTEXT_CHARS + 100


def test_build_context_numbers_each_document():
    """每段资料带上编号，模型引用时能对上位置。"""
    context = agent_graph.build_context(DOCS)
    assert "[资料1]" in context
    assert "[资料2]" in context


async def test_happy_path_answers_in_one_round(fake_env):
    """一次命中：相关 → 生成 → 有支撑，走完就结束。"""
    state, steps, _ = await _run(["相关", "质保时长为 24 个月。", "有支撑"], fake_env=fake_env)

    assert state["finish_reason"] == "正常回答"
    assert state["retrieve_count"] == 1
    assert state["retry_count"] == 0
    # 五步：准备检索问题、检索、判断相关、生成、校验
    assert [item["node"] for item in steps] == ["rewrite", "retrieve", "grade", "generate", "check"]


async def test_irrelevant_result_triggers_rewrite_and_retry(fake_env):
    """判定不相关时回到改写节点，再检索一次。"""
    state, steps, _ = await _run(
        # 第一次不相关 → 改写 → 第二次相关 → 生成 → 有支撑
        ["不相关", "换个说法的问题", "相关", "答案", "有支撑"],
        fake_env=fake_env,
    )

    assert state["finish_reason"] == "正常回答"
    # 检索发生了两次
    assert state["retrieve_count"] == 2
    assert state["retry_count"] == 1
    nodes = [item["node"] for item in steps]
    assert nodes.count("retrieve") == 2
    assert nodes.count("rewrite") == 2


async def test_retry_limit_falls_back(fake_env):
    """一直判定不相关，重试到上限后走兜底。"""
    state, steps, _ = await _run(["不相关"] * 20, fake_env=fake_env)

    assert state["answer"] == "知识库中未找到相关内容。"
    assert state["finish_reason"] == "召回不相关"
    # 重试次数被卡在上限
    assert state["retry_count"] == agent_graph.MAX_RETRIEVE_RETRY
    assert steps[-1]["node"] == "fallback"
    # 兜底时清空引用，页面上不会挂无关来源
    assert state["documents"] == []


async def test_empty_recall_counts_as_irrelevant(fake_env):
    """一条都没召回时直接判定不相关，不浪费一次模型调用。"""
    state, steps, _ = await _run(["不相关"] * 20, documents=[], fake_env=fake_env)

    assert state["finish_reason"] == "召回不相关"
    grade_steps = [item for item in steps if item["node"] == "grade"]
    assert grade_steps[0]["response"]["relevant"] is False
    # 没有资料时不该出现 verdict，说明没调模型
    assert "verdict" not in grade_steps[0]["response"]


async def test_ungrounded_answer_triggers_regenerate(fake_env):
    """答案被判无支撑时回到生成节点重写一次。"""
    state, steps, _ = await _run(
        ["相关", "第一版答案", "无支撑", "第二版答案", "有支撑"],
        fake_env=fake_env,
    )

    assert state["finish_reason"] == "正常回答"
    assert state["answer"] == "第二版答案"
    nodes = [item["node"] for item in steps]
    assert nodes.count("generate") == 2
    assert nodes.count("check") == 2
    # 重新生成没有再检索一次
    assert state["retrieve_count"] == 1


async def test_regenerate_limit_falls_back(fake_env):
    """一直判无支撑，重生成到上限后走兜底。"""
    state, steps, _ = await _run(
        ["相关"] + ["答案", "无支撑"] * 10,
        fake_env=fake_env,
    )

    assert state["answer"] == "知识库中未找到相关内容。"
    assert state["regenerate_count"] == agent_graph.MAX_REGENERATE
    assert steps[-1]["node"] == "fallback"


async def test_verdict_tolerates_extra_words(fake_env):
    """模型多说两个字也能正确解析判断结论。"""
    state, _, _ = await _run(
        ["这段资料相关", "答案", "这个回答有支撑"],
        fake_env=fake_env,
    )
    assert state["finish_reason"] == "正常回答"


async def test_first_round_uses_original_query(fake_env):
    """第一轮不改写，直接用用户的原始问题去检索。"""
    _, _, holder = await _run(["相关", "答案", "有支撑"], fake_env=fake_env)
    # 第一次调检索工具时，query 就是用户输入的原始问题
    assert holder["invoked"][0][1]["query"] == "保修期多久"


async def test_retry_uses_rewritten_query(fake_env):
    """重试时换成改写后的问题去检索，不再用原问题。"""
    _, _, holder = await _run(
        ["不相关", "换个说法的问题", "相关", "答案", "有支撑"],
        fake_env=fake_env,
    )
    assert holder["invoked"][0][1]["query"] == "保修期多久"
    # 第二次检索用的是改写结果
    assert holder["invoked"][1][1]["query"] == "换个说法的问题"
