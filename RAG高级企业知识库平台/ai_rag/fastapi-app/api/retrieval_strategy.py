"""检索策略管理与召回对比调试台接口。"""

from typing import List

from fastapi import APIRouter, Depends
from pydantic import BaseModel, ConfigDict

from common.auth import require_admin
from common.result import Result
from models import User
from service import retrieval_service, retrieval_strategy_service

router = APIRouter(prefix="/retrievalStrategy")


class RetrievalStrategyPayload(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int | None = None
    name: str | None = None
    vector_enabled: str | None = None
    vector_top_k: int | None = None
    bm25_enabled: str | None = None
    bm25_top_k: int | None = None
    rrf_k: int | None = None
    rerank_enabled: str | None = None
    rerank_model_id: int | None = None
    rerank_top_n: int | None = None
    query_rewrite_enabled: str | None = None
    rewrite_type: str | None = None
    multi_query_count: int | None = None
    parent_recall_enabled: str | None = None
    # 阈值按分数量纲分成两个：向量单路召回比余弦相似度，开了重排比重排相关分
    vector_score_threshold: float | None = None
    rerank_score_threshold: float | None = None
    is_default: str | None = None
    remark: str | None = None


class ComparePayload(BaseModel):
    kb_ids: List[int] = []
    # 要并排对比的策略，页面上最多选四套
    strategy_ids: List[int] = []
    document_ids: List[int] | None = None
    query: str = ""


@router.post("/add")
async def add(payload: RetrievalStrategyPayload, _: User = Depends(require_admin)):
    await retrieval_strategy_service.add(payload.model_dump(exclude_unset=True))
    return Result.success()


@router.put("/update")
async def update(payload: RetrievalStrategyPayload, _: User = Depends(require_admin)):
    await retrieval_strategy_service.update(payload.id, payload.model_dump(exclude_unset=True))
    return Result.success()


@router.post("/scoreScale")
async def score_scale(payload: RetrievalStrategyPayload, _: User = Depends(require_admin)):
    """按当前表单上的开关组合，返回这套策略最终分数的量纲。

    策略弹窗要在保存之前就告诉管理员哪个阈值会生效，而推算规则和检索管线
    是同一套，写在 retrieval_service 里，页面调这个接口取，不在前端重写。
    """
    return Result.success(
        retrieval_service.predict_score_scale(payload.model_dump(exclude_unset=True))
    )


@router.delete("/delete/{strategy_id}")
async def delete(strategy_id: int, _: User = Depends(require_admin)):
    await retrieval_strategy_service.delete(strategy_id)
    return Result.success()


@router.get("/selectPage")
async def select_page(
    name: str = "",
    page_num: int = 1,
    page_size: int = 10,
    _: User = Depends(require_admin),
):
    return Result.success(await retrieval_strategy_service.select_page(name, page_num, page_size))


@router.post("/compare")
async def compare(payload: ComparePayload, current_user: User = Depends(require_admin)):
    """调试台：同一个问题跑多套策略，结果并排返回并存档。"""
    return Result.success(
        await retrieval_strategy_service.compare(
            current_user.id,
            payload.kb_ids,
            payload.query,
            payload.strategy_ids,
            payload.document_ids,
        )
    )


@router.get("/records")
async def records(
    kb_id: int | None = None,
    page_num: int = 1,
    page_size: int = 10,
    _: User = Depends(require_admin),
):
    """调试记录列表。"""
    return Result.success(await retrieval_strategy_service.select_records(kb_id, page_num, page_size))


@router.get("/records/{record_id}")
async def record(record_id: int, _: User = Depends(require_admin)):
    """按 ID 取一条调试记录的完整快照。"""
    return Result.success(await retrieval_strategy_service.select_record(record_id))


@router.get("/chunkTypes/{kb_id}")
async def chunk_types(kb_id: int, _: User = Depends(require_admin)):
    """知识库的片段类型分布，用来提示要不要开父块回填。"""
    return Result.success(await retrieval_strategy_service.kb_chunk_type_summary(kb_id))
