"""Agentic RAG 执行接口。"""

from typing import List

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from common.auth import require_admin
from common.result import Result
from models import User
from service import agent_service

router = APIRouter(prefix="/agent")


class RunPayload(BaseModel):
    kb_ids: List[int] = []
    query: str = ""
    # 多轮对话历史，第一轮不传
    history: List[dict] | None = None


@router.post("/run")
async def run(payload: RunPayload, current_user: User = Depends(require_admin)):
    """跑一次 Agentic 问答，返回答案、引用来源和这次跑了几步。"""
    return Result.success(
        await agent_service.run(
            payload.kb_ids,
            payload.query,
            user_id=current_user.id,
            history=payload.history,
        )
    )


@router.get("/runs")
async def runs(
    run_status: str = "",
    session_id: int | None = None,
    page_num: int = 1,
    page_size: int = 10,
    _: User = Depends(require_admin),
):
    """运行记录列表。"""
    return Result.success(
        await agent_service.select_runs(run_status, session_id, page_num, page_size)
    )


@router.get("/steps/{run_id}")
async def steps(run_id: int, _: User = Depends(require_admin)):
    """一次运行的完整步骤时间线。"""
    return Result.success(await agent_service.select_steps(run_id))
