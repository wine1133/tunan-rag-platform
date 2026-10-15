"""知识库管理业务逻辑。"""

from typing import List

from common.exception_handler import CustomException
from common.result import PageInfo
from models import KnowledgeBase, User

# 知识库只有正常和停用两种状态，停用的库不参与问答检索
STATUSES = {"正常", "停用"}


def knowledge_base_dict(kb: KnowledgeBase) -> dict:
    # 表格每一列取的都是这里的字段
    return {
        "id": kb.id,
        "name": kb.name,
        "description": kb.description,
        "embedding_model_id": kb.embedding_model_id,
        "chunk_strategy_id": kb.chunk_strategy_id,
        "document_count": kb.document_count,
        "chunk_count": kb.chunk_count,
        "status": kb.status,
        "create_user_id": kb.create_user_id,
        "create_time": kb.create_time,
        "update_time": kb.update_time,
    }


async def add(current_user: User, payload: dict) -> None:
    name = payload.get("name")
    if not name:
        raise CustomException("请输入知识库名称")
    # 同名知识库会让管理员在文档上传时选错库，这里按名称查重
    if await KnowledgeBase.get_or_none(name=name):
        raise CustomException("知识库名称重复")
    status = payload.get("status") or "正常"
    if status not in STATUSES:
        raise CustomException("状态参数错误")
    await KnowledgeBase.create(
        name=name,
        description=payload.get("description"),
        status=status,
        # 记录创建人，列表页展示"谁建的"，也便于后续按人筛选
        create_user_id=current_user.id,
    )


async def update(kb_id: int | None, payload: dict) -> None:
    if kb_id is None:
        raise CustomException("知识库ID不能为空")
    kb = await KnowledgeBase.get_or_none(id=kb_id)
    if kb is None:
        raise CustomException("未找到知识库")
    name = payload.get("name")
    if not name:
        raise CustomException("请输入知识库名称")
    # 改名时排除自己，否则保存原名会被自己拦下来
    duplicated = await KnowledgeBase.filter(name=name).exclude(id=kb_id).exists()
    if duplicated:
        raise CustomException("知识库名称重复")
    status = payload.get("status") or kb.status
    if status not in STATUSES:
        raise CustomException("状态参数错误")
    await KnowledgeBase.filter(id=kb_id).update(
        name=name,
        description=payload.get("description"),
        status=status,
    )


async def delete(kb_id: int) -> None:
    kb = await KnowledgeBase.get_or_none(id=kb_id)
    if kb is None:
        raise CustomException("未找到知识库")
    # 库里还有文档时不允许删，避免文档和片段变成找不到归属的孤儿数据
    if kb.document_count > 0:
        raise CustomException("该知识库下还有文档，请先删除文档")
    await KnowledgeBase.filter(id=kb_id).delete()


async def delete_batch(ids: List[int]) -> None:
    # 只要有一个库还挂着文档，整批都不删，避免用户以为全删了、实际漏了几条
    blocked = await KnowledgeBase.filter(id__in=ids, document_count__gt=0).first()
    if blocked is not None:
        raise CustomException(f"知识库【{blocked.name}】下还有文档，请先删除文档")
    await KnowledgeBase.filter(id__in=ids).delete()


async def select_by_id(kb_id: int) -> dict:
    kb = await KnowledgeBase.get_or_none(id=kb_id)
    if kb is None:
        raise CustomException("未找到知识库")
    return knowledge_base_dict(kb)


async def select_all() -> List[dict]:
    # 供第 06 章的文档管理页面做知识库下拉框使用，只返回正常状态的库
    bases = await KnowledgeBase.filter(status="正常").order_by("-id")
    return [knowledge_base_dict(kb) for kb in bases]


async def select_page(name: str = "", status: str = "", page_num: int = 1, page_size: int = 10) -> PageInfo:
    # name 来自页面顶部名称输入框，空字符串时等于不加这个条件
    query = KnowledgeBase.filter(name__contains=name)
    # status 来自状态下拉框，选了才追加精确匹配
    if status:
        query = query.filter(status=status)
    bases = await query.order_by("-id").offset((page_num - 1) * page_size).limit(page_size)
    total = await query.count()
    return PageInfo(total=total, list=[knowledge_base_dict(kb) for kb in bases])
