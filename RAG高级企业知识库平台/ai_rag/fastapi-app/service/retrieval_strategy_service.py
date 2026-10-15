"""检索策略管理业务逻辑。"""

import json
from decimal import Decimal
from typing import List

from common.exception_handler import CustomException
from common.result import PageInfo
from common.times import cost_millis, now
from models import KnowledgeChunk, RetrievalStrategy
from models.process import RetrievalDebugRecord
from service import retrieval_service

REWRITE_TYPES = {"多查询扩展", "指代消解", "HyDE"}
YES_NO = {"是", "否"}
# 一次调试台对比最多允许几套策略。每多一套就多跑一遍完整检索，
# 开了改写和重排时耗时会明显叠加
MAX_COMPARE_STRATEGIES = 4


def _validate(payload: dict) -> None:
    if not payload.get("name"):
        raise CustomException("请输入策略名称")
    for field in ("vector_enabled", "bm25_enabled", "rerank_enabled", "query_rewrite_enabled", "parent_recall_enabled"):
        value = payload.get(field)
        if value is not None and value not in YES_NO:
            raise CustomException("开关取值只能是是或否")
    # 两路都关掉的话这套策略没法执行任何检索
    if payload.get("vector_enabled") != "是" and payload.get("bm25_enabled") != "是":
        raise CustomException("向量检索和 BM25 检索至少要启用一个")
    if payload.get("query_rewrite_enabled") == "是" and payload.get("rewrite_type") not in REWRITE_TYPES:
        raise CustomException("启用查询改写时必须选择改写方式")
    for field, label in (("vector_top_k", "向量召回条数"), ("bm25_top_k", "BM25召回条数")):
        value = payload.get(field)
        if value is not None and value < 0:
            raise CustomException(f"{label}不能为负数")
    if payload.get("rerank_enabled") == "是":
        top_n = payload.get("rerank_top_n") or 0
        if top_n <= 0:
            raise CustomException("启用重排时保留条数必须大于 0")
    # 两个阈值分别对应两种分数量纲，取值范围都是 0 到 1，但含义不同，分别校验
    for field, label in (
        ("vector_score_threshold", "余弦相似度阈值"),
        ("rerank_score_threshold", "重排相关分阈值"),
    ):
        threshold = payload.get(field)
        if threshold is not None and not 0 <= float(threshold) <= 1:
            raise CustomException(f"{label}取值范围是 0 到 1")


async def _clear_other_defaults(keep_id: int | None = None) -> None:
    """全表只允许一条默认策略。"""
    query = RetrievalStrategy.filter(is_default="是")
    if keep_id is not None:
        query = query.exclude(id=keep_id)
    await query.update(is_default="否")


def _fields(payload: dict) -> dict:
    """把请求体整理成可以直接写库的字段字典。"""
    def threshold_of(field: str) -> Decimal | None:
        value = payload.get(field)
        if value is None:
            return None
        # 列类型是 decimal(5,3)，多余小数位会被数据库截断并告警，这里先按三位取整
        return Decimal(str(value)).quantize(Decimal("0.001"))

    return {
        "name": payload["name"],
        "vector_enabled": payload.get("vector_enabled") or "否",
        "vector_top_k": payload.get("vector_top_k") or 0,
        "bm25_enabled": payload.get("bm25_enabled") or "否",
        "bm25_top_k": payload.get("bm25_top_k") or 0,
        "rrf_k": payload.get("rrf_k") or 60,
        "rerank_enabled": payload.get("rerank_enabled") or "否",
        "rerank_model_id": payload.get("rerank_model_id"),
        "rerank_top_n": payload.get("rerank_top_n") or 3,
        "query_rewrite_enabled": payload.get("query_rewrite_enabled") or "否",
        # 关掉改写时把改写方式一起清掉，避免留下不生效的残值
        "rewrite_type": payload.get("rewrite_type") if payload.get("query_rewrite_enabled") == "是" else None,
        "multi_query_count": payload.get("multi_query_count") or 3,
        "parent_recall_enabled": payload.get("parent_recall_enabled") or "否",
        # 向量阈值只在最终分数是余弦相似度时生效，重排阈值只在开了重排时生效。
        # 两个都原样存下来，页面上哪个生效由当前策略的开关组合决定
        "vector_score_threshold": threshold_of("vector_score_threshold"),
        "rerank_score_threshold": threshold_of("rerank_score_threshold"),
        "remark": payload.get("remark"),
    }


async def add(payload: dict) -> None:
    _validate(payload)
    if await RetrievalStrategy.get_or_none(name=payload["name"]):
        raise CustomException("策略名称重复")
    is_default = payload.get("is_default") or "否"
    if is_default == "是":
        await _clear_other_defaults()
    await RetrievalStrategy.create(is_default=is_default, **_fields(payload))


async def update(strategy_id: int | None, payload: dict) -> None:
    if strategy_id is None:
        raise CustomException("策略ID不能为空")
    if await RetrievalStrategy.get_or_none(id=strategy_id) is None:
        raise CustomException("未找到检索策略")
    _validate(payload)
    if await RetrievalStrategy.filter(name=payload["name"]).exclude(id=strategy_id).exists():
        raise CustomException("策略名称重复")
    is_default = payload.get("is_default") or "否"
    if is_default == "是":
        await _clear_other_defaults(keep_id=strategy_id)
    await RetrievalStrategy.filter(id=strategy_id).update(is_default=is_default, **_fields(payload))


async def delete(strategy_id: int) -> None:
    strategy = await RetrievalStrategy.get_or_none(id=strategy_id)
    if strategy is None:
        raise CustomException("未找到检索策略")
    # 默认策略是问答应用没配策略时的兜底，删掉之后问答会失去默认值
    if strategy.is_default == "是":
        raise CustomException("默认策略不能删除，请先把其他策略设为默认")
    await RetrievalStrategy.filter(id=strategy_id).delete()


async def select_page(name: str = "", page_num: int = 1, page_size: int = 10) -> PageInfo:
    query = RetrievalStrategy.filter(name__contains=name)
    items = await query.order_by("-is_default", "id").offset((page_num - 1) * page_size).limit(page_size)
    total = await query.count()
    return PageInfo(total=total, list=[retrieval_service.strategy_dict(item) for item in items])


async def compare(
    user_id: int,
    kb_ids: List[int],
    query: str,
    strategy_ids: List[int],
    document_ids: List[int] | None = None,
) -> dict:
    """调试台：同一个问题跑多套策略，把结果并排返回并存档。"""
    if not strategy_ids:
        raise CustomException("请至少选择一套检索策略")
    if len(strategy_ids) > MAX_COMPARE_STRATEGIES:
        raise CustomException(f"一次最多对比 {MAX_COMPARE_STRATEGIES} 套策略")
    started = now()
    columns = []
    for strategy_id in strategy_ids:
        strategy = await retrieval_service.load_strategy(strategy_id)
        try:
            outcome = await retrieval_service.retrieve(kb_ids, query, strategy, document_ids)
            await retrieval_service._fill_document_name(outcome["results"])
            columns.append(outcome)
        except CustomException as exc:
            # 某一套策略跑失败不影响其他几套，把失败原因放在这一列里
            columns.append(
                {
                    "strategy_id": strategy_id,
                    "strategy_name": strategy["name"],
                    "results": [],
                    "stages": [],
                    "queries": [query],
                    "cost_millis": 0,
                    "error": exc.message,
                }
            )
    total_cost = cost_millis(started)
    # 存档，便于回头对照当时的召回情况
    await RetrievalDebugRecord.create(
        kb_id=kb_ids[0] if kb_ids else 0,
        query=query,
        strategy_ids=",".join(str(item) for item in strategy_ids),
        result_snapshot=json.dumps(columns, ensure_ascii=False, default=str),
        cost_millis=total_cost,
        create_user_id=user_id,
    )
    return {"query": query, "columns": columns, "cost_millis": total_cost}


async def select_records(kb_id: int | None = None, page_num: int = 1, page_size: int = 10) -> PageInfo:
    """调试记录列表，不返回快照正文，避免列表返回体过大。"""
    query = RetrievalDebugRecord.all()
    if kb_id:
        query = query.filter(kb_id=kb_id)
    records = await query.order_by("-id").offset((page_num - 1) * page_size).limit(page_size)
    total = await query.count()
    return PageInfo(
        total=total,
        list=[
            {
                "id": record.id,
                "kb_id": record.kb_id,
                "query": record.query,
                "strategy_ids": record.strategy_ids,
                "cost_millis": record.cost_millis,
                "create_time": record.create_time,
            }
            for record in records
        ],
    )


async def select_record(record_id: int) -> dict:
    """按 ID 取一条调试记录的完整快照。"""
    record = await RetrievalDebugRecord.get_or_none(id=record_id)
    if record is None:
        raise CustomException("未找到调试记录")
    return {
        "id": record.id,
        "query": record.query,
        "cost_millis": record.cost_millis,
        "create_time": record.create_time,
        "columns": json.loads(record.result_snapshot) if record.result_snapshot else [],
    }


async def kb_chunk_type_summary(kb_id: int) -> dict:
    """这个库的片段类型分布，页面上提示要不要开父块回填。"""
    plain = await KnowledgeChunk.filter(kb_id=kb_id, chunk_type="普通块").count()
    child = await KnowledgeChunk.filter(kb_id=kb_id, chunk_type="子块").count()
    parent = await KnowledgeChunk.filter(kb_id=kb_id, chunk_type="父块").count()
    return {"plain": plain, "child": child, "parent": parent}
