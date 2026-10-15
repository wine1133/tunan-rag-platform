"""Agentic RAG 执行。

负责三件事：跑状态图、把每一步写进 agent_run 和 agent_step、执行完反查数据库。

图本身不碰数据库，落库通过注入 on_step 回调完成——
这样 ai/graph.py 可以脱离数据库单独测试。
"""

import json
import uuid

from ai import graph as agent_graph
from common.exception_handler import CustomException
from common.times import cost_millis, now
from models import AgentRun, AgentStep, KnowledgeChunk

ERROR_MAX_LENGTH = 500
# 写进 agent_step 的入参和返回最多留多少字，防止一条记录撑到几十 KB
STEP_PAYLOAD_MAX = 4000


def _dump(value) -> str:
    return json.dumps(value, ensure_ascii=False, default=str)[:STEP_PAYLOAD_MAX]


class StepRecorder:
    """把状态图每个节点的执行情况写进 agent_step。

    做成一个类是因为要跨节点累计步数——每记一步 index 加一，
    第 23 章的时间线按这个顺序展示。
    """

    def __init__(self, run_id: int, on_progress=None):
        self.run_id = run_id
        self.index = 0
        # 调用方传进来的进度回调。落库是给第 23 章的时间线看的，
        # 这个回调是实时推给页面的，让用户在等待时知道跑到哪一步了
        self.on_progress = on_progress

    async def __call__(self, node: str, name: str, request: dict, response: dict) -> None:
        self.index += 1
        await AgentStep.create(
            run_id=self.run_id,
            step_index=self.index,
            step_name=name,
            node_name=node,
            # 检索节点用到了工具，记下工具编码，能和 tool_call_log 对上
            tool_code="search_knowledge" if node == "retrieve" else None,
            request_params=_dump(request),
            response_result=_dump(response),
            step_status="已完成",
            start_time=now(),
            end_time=now(),
            cost_millis=0,
        )
        if self.on_progress is not None:
            # response 里带着这一步的判定结论（相不相关、有没有支撑），
            # 页面靠它说清楚这次为什么要改写重试，而不只是干等。
            # 回调只负责往外发进度，失败了不能影响状态图本身继续跑
            try:
                self.on_progress(node, name, self.index, response)
            except Exception:
                pass


async def _fill_references(documents: list[dict]) -> list[dict]:
    """按 chunk_id 回查数据库，组装引用来源。

    第 20 章那条规则：引用一律用工具真实返回的 chunk_id 回查，
    不采信模型在答案里写的"依据第 3 条"——那个编号是它编的。
    """
    chunk_ids = [item["chunk_id"] for item in documents if item.get("chunk_id")]
    if not chunk_ids:
        return []
    chunks = await KnowledgeChunk.filter(id__in=chunk_ids)
    chunk_map = {chunk.id: chunk for chunk in chunks}
    references = []
    for rank, item in enumerate(documents, start=1):
        chunk = chunk_map.get(item.get("chunk_id"))
        # 片段已经被删掉时跳过，不展示一条点不开的来源
        if chunk is None:
            continue
        references.append(
            {
                "chunk_id": chunk.id,
                "document_id": chunk.document_id,
                "content": chunk.content,
                "page_no": chunk.page_no,
                "score": item.get("score"),
                "rank_no": rank,
            }
        )
    return references


async def run(
    kb_ids: list[int],
    query: str,
    user_id: int | None = None,
    app_id: int | None = None,
    session_id: int | None = None,
    history: list[dict] | None = None,
    on_progress=None,
) -> dict:
    """执行一次 Agentic 问答。

    on_progress 每跑完一个节点回调一次，参数是 (节点名, 步骤名, 第几步, 这一步的结论)。
    第 24 章的问答接口拿它往 SSE 里发 progress 事件，页面据此显示当前进度。
    """
    if not query or not query.strip():
        raise CustomException("请输入问题")
    if not kb_ids:
        raise CustomException("请选择知识库")
    started = now()
    run_record = await AgentRun.create(
        run_no=uuid.uuid4().hex,
        app_id=app_id,
        session_id=session_id,
        user_id=user_id,
        run_type="Agentic问答",
        run_status="运行中",
        input_snapshot=_dump({"query": query, "kb_ids": kb_ids}),
        start_time=started,
    )
    recorder = StepRecorder(run_record.id, on_progress=on_progress)
    try:
        compiled = agent_graph.build_graph()
        final_state = await compiled.ainvoke(
            {
                "original_query": query,
                "query": query,
                "kb_ids": kb_ids,
                "history": history or [],
                "retry_count": 0,
                "regenerate_count": 0,
                "retrieve_count": 0,
                "on_step": recorder,
            },
            # LangGraph 自己的递归上限，和业务侧的上限双保险
            {"recursion_limit": agent_graph.MAX_GRAPH_STEPS * 3},
        )
        retrieve_count = final_state.get("retrieve_count", 0)
        # 反查：模型可能一次检索都没发生就编出一段答案，这种运行不能算成功
        if retrieve_count == 0:
            raise CustomException(
                "本次运行没有发生任何检索，答案不可信。"
                "请检查知识库是否已向量化、检索工具是否被停用"
            )
        answer = final_state.get("answer") or ""
        references = await _fill_references(final_state.get("documents") or [])
        await AgentRun.filter(id=run_record.id).update(
            run_status="已完成",
            current_step=recorder.index,
            total_step=recorder.index,
            retrieve_count=retrieve_count,
            rewrite_count=final_state.get("retry_count", 0),
            output_summary=answer[:5000],
            end_time=now(),
            cost_millis=cost_millis(started),
        )
        return {
            "run_id": run_record.id,
            "run_no": run_record.run_no,
            "answer": answer,
            "references": references,
            "finish_reason": final_state.get("finish_reason") or "正常回答",
            "retrieve_count": retrieve_count,
            "retry_count": final_state.get("retry_count", 0),
            "total_step": recorder.index,
            "cost_millis": cost_millis(started),
        }
    except Exception as exc:
        message = exc.message if isinstance(exc, CustomException) else f"执行失败：{exc}"
        await AgentRun.filter(id=run_record.id).update(
            run_status="运行失败",
            current_step=recorder.index,
            total_step=recorder.index,
            error_message=message[:ERROR_MAX_LENGTH],
            end_time=now(),
            cost_millis=cost_millis(started),
        )
        raise CustomException(message)


async def select_runs(
    run_status: str = "",
    session_id: int | None = None,
    page_num: int = 1,
    page_size: int = 10,
):
    """运行记录列表。"""
    from common.result import PageInfo

    query = AgentRun.all()
    if run_status:
        query = query.filter(run_status=run_status)
    if session_id:
        query = query.filter(session_id=session_id)
    runs = await query.order_by("-id").offset((page_num - 1) * page_size).limit(page_size)
    total = await query.count()
    return PageInfo(
        total=total,
        list=[
            {
                "id": item.id,
                "run_no": item.run_no,
                "run_type": item.run_type,
                "run_status": item.run_status,
                "total_step": item.total_step,
                "retrieve_count": item.retrieve_count,
                "rewrite_count": item.rewrite_count,
                "output_summary": item.output_summary,
                "error_message": item.error_message,
                "cost_millis": item.cost_millis,
                "create_time": item.create_time,
            }
            for item in runs
        ],
    )


async def select_steps(run_id: int) -> dict:
    """一次运行的完整步骤时间线，供第 23 章的页面使用。"""
    run_record = await AgentRun.get_or_none(id=run_id)
    if run_record is None:
        raise CustomException("未找到运行记录")
    steps = await AgentStep.filter(run_id=run_id).order_by("step_index")
    return {
        "run": {
            "id": run_record.id,
            "run_no": run_record.run_no,
            "run_status": run_record.run_status,
            "total_step": run_record.total_step,
            "retrieve_count": run_record.retrieve_count,
            "rewrite_count": run_record.rewrite_count,
            "input_snapshot": run_record.input_snapshot,
            "output_summary": run_record.output_summary,
            "error_message": run_record.error_message,
            "cost_millis": run_record.cost_millis,
            "create_time": run_record.create_time,
        },
        "steps": [
            {
                "id": step.id,
                "step_index": step.step_index,
                "step_name": step.step_name,
                "node_name": step.node_name,
                "tool_code": step.tool_code,
                "request_params": step.request_params,
                "response_result": step.response_result,
                "step_status": step.step_status,
                "error_message": step.error_message,
                "cost_millis": step.cost_millis,
            }
            for step in steps
        ],
    }
