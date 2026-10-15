"""检索接口。"""

from typing import List

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from common.auth import require_admin
from common.result import Result
from models import User
from service import retrieval_service

router = APIRouter(prefix="/retrieval")


class SearchPayload(BaseModel):
    # 在哪些知识库里检索，页面上至少要选一个
    kb_ids: List[int] = []
    # 用哪套检索策略，不传时用默认策略
    strategy_id: int | None = None
    # 限定只在某几篇文档里检索，不传表示整个知识库
    document_ids: List[int] | None = None
    query: str = ""
    # 最近几轮对话，指代消解那种改写方式要用它把当前问题补全
    history: List[dict] | None = None


@router.post("/search")
async def search(payload: SearchPayload, _: User = Depends(require_admin)):
    """按指定策略执行一次检索，返回结果、各阶段耗时和总耗时。"""
    return Result.success(
        await retrieval_service.retrieve_by_strategy(
            payload.kb_ids,
            payload.query,
            payload.strategy_id,
            payload.document_ids,
            payload.history,
        )
    )


@router.get("/strategies")
async def strategies(_: User = Depends(require_admin)):
    """检索策略下拉数据。"""
    from models import RetrievalStrategy

    items = await RetrievalStrategy.all().order_by("-is_default", "id")
    return Result.success([retrieval_service.strategy_dict(item) for item in items])


@router.get("/knowledgeBases")
async def knowledge_bases(_: User = Depends(require_admin)):
    """检索测试页面的知识库下拉数据，带片段数。"""
    return Result.success(await retrieval_service.kb_options_with_chunks())
