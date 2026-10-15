"""切分策略管理业务逻辑。"""

from typing import List

from common.exception_handler import CustomException
from common.result import PageInfo
from models import ChunkStrategy

# 目前实现了两种切分方式，第 09 章的 ai/splitter.py 里各有一个对应的函数
STRATEGY_TYPES = {"递归分块", "父子分块"}


def strategy_dict(strategy: ChunkStrategy) -> dict:
    return {
        "id": strategy.id,
        "name": strategy.name,
        "strategy_type": strategy.strategy_type,
        "chunk_size": strategy.chunk_size,
        "chunk_overlap": strategy.chunk_overlap,
        "parent_chunk_size": strategy.parent_chunk_size,
        "separators": strategy.separators,
        "is_default": strategy.is_default,
        "remark": strategy.remark,
        "create_time": strategy.create_time,
        "update_time": strategy.update_time,
    }


def _validate(payload: dict) -> None:
    """新增和编辑共用的参数校验。"""
    if not payload.get("name"):
        raise CustomException("请输入策略名称")
    strategy_type = payload.get("strategy_type")
    if strategy_type not in STRATEGY_TYPES:
        raise CustomException("策略类型参数错误")
    chunk_size = payload.get("chunk_size") or 0
    if chunk_size <= 0:
        raise CustomException("片段长度必须大于 0")
    chunk_overlap = payload.get("chunk_overlap") or 0
    # 重叠比片段本身还长会让切分陷入死循环，切不出新内容
    if chunk_overlap >= chunk_size:
        raise CustomException("重叠字符数必须小于片段长度")
    if strategy_type == "父子分块":
        parent_chunk_size = payload.get("parent_chunk_size") or 0
        # 父块要装得下子块，否则父子分块退化成普通分块
        if parent_chunk_size <= chunk_size:
            raise CustomException("父块长度必须大于片段长度")


async def _clear_other_defaults(keep_id: int | None = None) -> None:
    """把其他策略的默认标记清掉，保证全表只有一条默认。"""
    query = ChunkStrategy.filter(is_default="是")
    if keep_id is not None:
        query = query.exclude(id=keep_id)
    await query.update(is_default="否")


async def add(payload: dict) -> None:
    _validate(payload)
    if await ChunkStrategy.get_or_none(name=payload["name"]):
        raise CustomException("策略名称重复")
    is_default = payload.get("is_default") or "否"
    if is_default == "是":
        await _clear_other_defaults()
    await ChunkStrategy.create(
        name=payload["name"],
        strategy_type=payload["strategy_type"],
        chunk_size=payload["chunk_size"],
        chunk_overlap=payload.get("chunk_overlap") or 0,
        # 递归分块用不到父块长度，存空值而不是存一个没意义的数字
        parent_chunk_size=payload.get("parent_chunk_size") if payload["strategy_type"] == "父子分块" else None,
        separators=payload.get("separators"),
        is_default=is_default,
        remark=payload.get("remark"),
    )


async def update(strategy_id: int | None, payload: dict) -> None:
    if strategy_id is None:
        raise CustomException("策略ID不能为空")
    strategy = await ChunkStrategy.get_or_none(id=strategy_id)
    if strategy is None:
        raise CustomException("未找到切分策略")
    _validate(payload)
    # 改名时排除自己，否则保存原名会被自己拦下来
    if await ChunkStrategy.filter(name=payload["name"]).exclude(id=strategy_id).exists():
        raise CustomException("策略名称重复")
    is_default = payload.get("is_default") or "否"
    if is_default == "是":
        await _clear_other_defaults(keep_id=strategy_id)
    await ChunkStrategy.filter(id=strategy_id).update(
        name=payload["name"],
        strategy_type=payload["strategy_type"],
        chunk_size=payload["chunk_size"],
        chunk_overlap=payload.get("chunk_overlap") or 0,
        parent_chunk_size=payload.get("parent_chunk_size") if payload["strategy_type"] == "父子分块" else None,
        separators=payload.get("separators"),
        is_default=is_default,
        remark=payload.get("remark"),
    )


async def delete(strategy_id: int) -> None:
    strategy = await ChunkStrategy.get_or_none(id=strategy_id)
    if strategy is None:
        raise CustomException("未找到切分策略")
    # 默认策略是知识库没配策略时的兜底，删掉之后切分会失去默认值
    if strategy.is_default == "是":
        raise CustomException("默认策略不能删除，请先把其他策略设为默认")
    await ChunkStrategy.filter(id=strategy_id).delete()


async def select_all() -> List[dict]:
    strategies = await ChunkStrategy.all().order_by("-is_default", "id")
    return [strategy_dict(item) for item in strategies]


async def select_default() -> dict:
    """取默认策略，知识库没有单独配置时用它。"""
    strategy = await ChunkStrategy.get_or_none(is_default="是")
    if strategy is None:
        raise CustomException("没有设置默认切分策略，请先在切分策略里设置一条")
    return strategy_dict(strategy)


async def select_page(name: str = "", strategy_type: str = "", page_num: int = 1, page_size: int = 10) -> PageInfo:
    query = ChunkStrategy.filter(name__contains=name)
    if strategy_type:
        query = query.filter(strategy_type=strategy_type)
    strategies = await query.order_by("-id").offset((page_num - 1) * page_size).limit(page_size)
    total = await query.count()
    return PageInfo(total=total, list=[strategy_dict(item) for item in strategies])
