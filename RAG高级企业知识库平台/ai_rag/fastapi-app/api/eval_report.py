"""评测报告对比与链路追踪接口。"""

from typing import List

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from common.auth import require_admin
from common.result import Result
from models import User
from service import eval_report_service

router = APIRouter(prefix="/evalReport")


class ComparePayload(BaseModel):
    # 至少两份才谈得上对比
    report_ids: List[int] = []


@router.get("/selectAll")
async def select_all(dataset_id: int | None = None, _: User = Depends(require_admin)):
    """报告列表，带四个指标、综合得分和耗时。"""
    return Result.success(await eval_report_service.select_reports(dataset_id))


@router.post("/compare")
async def compare(payload: ComparePayload, _: User = Depends(require_admin)):
    """把几份报告组装成图表能直接用的结构。"""
    return Result.success(await eval_report_service.compare(payload.report_ids))

