"""Agentic RAG 状态图。

第 20 章画的那张图在这里落地：

    改写查询 ─→ 检索 ─→ 相关性评分 ─┬─相关──→ 生成 ─→ 幻觉校验 ─┬─有支撑─→ 结束
                    ↑              ├─不相关─→ 回到改写         ├─无支撑─→ 回到生成
                    └──────────────┘                          └─超上限─→ 兜底
                                   └─超上限─→ 兜底

和第 15 到 19 章的直线链路的区别只有一个：跑几轮由模型的判断决定，不由配置决定。
retrieve 节点内部调的还是 retrieval_service 那条完整检索链路，一行没改。

四个防失控上限写死在本模块里，不放进配置，避免被改成一个危险的值。
"""

from typing import Annotated, Any, Callable, TypedDict

from langgraph.graph import END, START, StateGraph

from ai import model_factory, prompt_loader, query_rewriter

# 状态图最多允许走多少个节点。LangGraph 自己也有 recursion_limit，这里是业务侧的上限
MAX_GRAPH_STEPS = 10
# 召回被判定为不相关时，最多改写重检索几次
MAX_RETRIEVE_RETRY = 3
# 答案被判定为无资料支撑时，最多重新生成几次
# 答案被判定为无支撑时，最多重新生成几次
MAX_REGENERATE = 2
# 拼进 Prompt 的资料最多多少字，防止上下文被撑爆
MAX_CONTEXT_CHARS = 6000


class AgentState(TypedDict, total=False):
    """状态从头传到尾，每个节点只返回自己改了的字段，框架负责合并。"""

    # 用户原始问题，全程不变，兜底和落库时要用它
    original_query: str
    # 当前这一轮实际拿去检索的问题，改写节点会改它
    query: str
    kb_ids: list[int]
    # 多轮对话历史，指代消解要用
    history: list[dict]
    # 当前召回的片段
    documents: list[dict]
    # 生成的答案
    answer: str
    # 已经改写重检索了几次
    retry_count: int
    # 已经重新生成了几次
    regenerate_count: int
    # 实际发生过几次检索，执行完要反查它
    retrieve_count: int
    # 最近一次相关性评分和幻觉校验的结论
    is_relevant: bool
    is_grounded: bool
    # 结束原因：正常回答 / 召回不相关 / 答案无支撑 / 步数超限
    finish_reason: str
    # 记录每个节点执行情况的回调，由 service 层注入
    on_step: Any


def build_context(documents: list[dict]) -> str:
    """把召回的片段拼成发给模型的资料段。

    超过长度上限就截断，宁可少给几段，也不能让请求因为超长直接失败。
    """
    parts = []
    used = 0
    for index, item in enumerate(documents, start=1):
        content = item.get("content", "")
        if used + len(content) > MAX_CONTEXT_CHARS:
            break
        parts.append(f"[资料{index}] {content}")
        used += len(content)
    return "\n\n".join(parts)


async def _chat(prompt: str) -> str:
    """调一次对话模型并取出文本内容。"""
    config = await model_factory.load_enabled(model_factory.CHAT)
    model = model_factory.build_chat_model(config)
    reply = await model.ainvoke(prompt)
    return str(reply.content).strip()


async def _emit(state: AgentState, node: str, name: str, request: dict, response: dict) -> None:
    """把这一步交给 service 层落库。

    图本身不碰数据库，由外面注入的回调决定怎么记，
    这样图可以脱离数据库单独测试。
    """
    callback: Callable | None = state.get("on_step")
    if callback is not None:
        await callback(node, name, request, response)


async def rewrite_node(state: AgentState) -> AgentState:
    """改写查询。

    第一轮直接用原问题，只有被判定为不相关、回到这个节点重试时才真正改写——
    第一轮就改写等于放弃用户原本的表达，反而可能把方向带偏。
    """
    retry = state.get("retry_count", 0)
    if retry == 0:
        history = state.get("history") or []
        # 多轮对话第一轮就要做指代消解，否则"那它呢"根本没法检索
        query = (
            await query_rewriter.resolve_coreference(state["original_query"], history)
            if history
            else state["original_query"]
        )
        await _emit(state, "rewrite", "准备检索问题", {"retry": retry}, {"query": query})
        return {"query": query}
    queries = await query_rewriter.multi_query(state["original_query"], 2)
    # 换一个说法重试，取改写结果里的最后一条，避开上一轮已经用过的
    query = queries[-1]
    await _emit(state, "rewrite", f"第 {retry} 次改写查询", {"retry": retry}, {"query": query})
    return {"query": query}


async def retrieve_node(state: AgentState) -> AgentState:
    """检索知识库。内部走的是第 15 到 19 章那条完整链路。"""
    from ai import tools

    kb_id = state["kb_ids"][0]
    result = await tools.invoke(
        "search_knowledge",
        {"query": state["query"], "kb_id": kb_id, "top_k": 5},
    )
    documents = result.get("results", [])
    await _emit(
        state,
        "retrieve",
        "检索知识库",
        {"query": state["query"], "kb_id": kb_id},
        {"count": len(documents)},
    )
    return {
        "documents": documents,
        "retrieve_count": state.get("retrieve_count", 0) + 1,
    }


async def grade_node(state: AgentState) -> AgentState:
    """相关性评分：让模型判断这批资料能不能回答问题。"""
    documents = state.get("documents") or []
    if not documents:
        await _emit(state, "grade", "判断召回是否相关", {"count": 0}, {"relevant": False})
        return {"is_relevant": False, "retry_count": state.get("retry_count", 0) + 1}
    prompt = await prompt_loader.render(
        "CONTEXT_GRADE",
        context=build_context(documents),
        question=state["original_query"],
    )
    verdict = await _chat(prompt)
    # 模板要求只回"相关"或"不相关"，这里按包含关系判断，容忍模型多说两个字
    relevant = "不相关" not in verdict and "相关" in verdict
    await _emit(
        state,
        "grade",
        "判断召回是否相关",
        {"count": len(documents)},
        {"verdict": verdict, "relevant": relevant},
    )
    if relevant:
        return {"is_relevant": True}
    return {"is_relevant": False, "retry_count": state.get("retry_count", 0) + 1}


async def generate_node(state: AgentState) -> AgentState:
    """根据资料生成答案。"""
    prompt = await prompt_loader.render(
        "RAG_ANSWER",
        context=build_context(state.get("documents") or []),
        question=state["original_query"],
    )
    answer = await _chat(prompt)
    await _emit(
        state,
        "generate",
        "生成答案",
        {"regenerate": state.get("regenerate_count", 0)},
        {"length": len(answer)},
    )
    return {"answer": answer}


async def check_node(state: AgentState) -> AgentState:
    """幻觉校验：判断答案是不是完全由资料支撑。"""
    prompt = await prompt_loader.render(
        "HALLUCINATION_CHECK",
        context=build_context(state.get("documents") or []),
        answer=state.get("answer", ""),
    )
    verdict = await _chat(prompt)
    grounded = "无支撑" not in verdict and "有支撑" in verdict
    await _emit(
        state,
        "check",
        "校验答案是否有资料支撑",
        {"answer_length": len(state.get("answer", ""))},
        {"verdict": verdict, "grounded": grounded},
    )
    if grounded:
        return {"is_grounded": True, "finish_reason": "正常回答"}
    return {
        "is_grounded": False,
        "regenerate_count": state.get("regenerate_count", 0) + 1,
    }


async def fallback_node(state: AgentState) -> AgentState:
    """兜底：超过上限或确实找不到资料时，明确告诉用户没找到。"""
    reason = state.get("finish_reason") or "召回不相关"
    await _emit(state, "fallback", "走兜底话术", {"reason": reason}, {})
    return {
        "answer": "知识库中未找到相关内容。",
        "finish_reason": reason,
        # 兜底时清空引用，避免页面上挂着一堆和答案无关的来源
        "documents": [],
    }


def route_after_grade(state: AgentState) -> str:
    """相关性评分之后往哪走。"""
    if state.get("is_relevant"):
        return "generate"
    if state.get("retry_count", 0) >= MAX_RETRIEVE_RETRY:
        # 改写重试到上限还是不相关，说明知识库里大概率真没有
        return "fallback"
    return "rewrite"


def route_after_check(state: AgentState) -> str:
    """幻觉校验之后往哪走。"""
    if state.get("is_grounded"):
        return END
    if state.get("regenerate_count", 0) >= MAX_REGENERATE:
        return "fallback"
    return "generate"


def build_graph():
    """把节点和边组装成状态图。

    流程写在边上、业务写在节点里、状态写在一个地方，
    看这个函数就是一张流程图，不用去模拟执行。
    """
    graph = StateGraph(AgentState)
    graph.add_node("rewrite", rewrite_node)
    graph.add_node("retrieve", retrieve_node)
    graph.add_node("grade", grade_node)
    graph.add_node("generate", generate_node)
    graph.add_node("check", check_node)
    graph.add_node("fallback", fallback_node)

    graph.add_edge(START, "rewrite")
    graph.add_edge("rewrite", "retrieve")
    graph.add_edge("retrieve", "grade")
    # 条件边：下一个去哪由 route_after_grade 读状态决定
    graph.add_conditional_edges(
        "grade",
        route_after_grade,
        {"generate": "generate", "rewrite": "rewrite", "fallback": "fallback"},
    )
    graph.add_edge("generate", "check")
    graph.add_conditional_edges(
        "check",
        route_after_check,
        {END: END, "generate": "generate", "fallback": "fallback"},
    )
    graph.add_edge("fallback", END)
    return graph.compile()
