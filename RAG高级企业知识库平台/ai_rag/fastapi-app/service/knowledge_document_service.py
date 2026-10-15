"""知识文档管理业务逻辑。"""

import os
from typing import List

from ai import vector_store
from common.exception_handler import CustomException
from common.result import PageInfo
from models import KnowledgeBase, KnowledgeChunk, KnowledgeDocument, User

# 支持的文件类型。key 是文件后缀，value 是存进 file_type 列的类型名，
# 第 07 章按 file_type 决定用哪个解析器
FILE_TYPES = {
    ".pdf": "PDF",
    ".docx": "WORD",
    ".doc": "WORD",
    ".xlsx": "EXCEL",
    ".xls": "EXCEL",
    ".md": "MARKDOWN",
    ".txt": "TXT",
}


def resolve_file_type(file_name: str | None) -> str:
    """按文件后缀推断文件类型，不支持的类型直接拦住。"""
    if not file_name:
        raise CustomException("请先上传文件")
    # splitext 取出带点的后缀，统一转小写，兼容 .PDF 这种大写写法
    suffix = os.path.splitext(file_name)[1].lower()
    file_type = FILE_TYPES.get(suffix)
    if file_type is None:
        raise CustomException("暂不支持该文件类型，请上传 PDF、Word、Excel、Markdown 或 TXT")
    return file_type


def document_dict(doc: KnowledgeDocument, kb_name: str | None = None) -> dict:
    return {
        "id": doc.id,
        "kb_id": doc.kb_id,
        # 列表页要显示"这篇文档属于哪个库"，由调用方查好库名传进来
        "kb_name": kb_name,
        "name": doc.name,
        "file_name": doc.file_name,
        "file_url": doc.file_url,
        "file_type": doc.file_type,
        "file_size": doc.file_size,
        "parse_status": doc.parse_status,
        "parse_error": doc.parse_error,
        "has_table": doc.has_table,
        "has_ocr": doc.has_ocr,
        "char_count": doc.char_count,
        "chunk_count": doc.chunk_count,
        "vector_status": doc.vector_status,
        "upload_user_id": doc.upload_user_id,
        "create_time": doc.create_time,
        "update_time": doc.update_time,
    }


async def _kb_name_map(docs: List[KnowledgeDocument]) -> dict:
    """一次性查出这批文档涉及的知识库名称，避免逐条查库。"""
    kb_ids = {doc.kb_id for doc in docs}
    if not kb_ids:
        return {}
    bases = await KnowledgeBase.filter(id__in=list(kb_ids))
    return {kb.id: kb.name for kb in bases}


async def _refresh_document_count(kb_id: int) -> None:
    """重算并回写知识库的文档数，增删文档后都要调一次。"""
    count = await KnowledgeDocument.filter(kb_id=kb_id).count()
    await KnowledgeBase.filter(id=kb_id).update(document_count=count)


async def _refresh_chunk_count(kb_id: int) -> None:
    """重算并回写知识库的片段数。删文档会连带删掉它的片段，所以要跟着重算。

    父块只做上下文回填不参与检索，统计时不计入，口径和第 09 章保持一致。
    """
    count = await KnowledgeChunk.filter(kb_id=kb_id).exclude(chunk_type="父块").count()
    await KnowledgeBase.filter(id=kb_id).update(chunk_count=count)


async def add(current_user: User, payload: dict) -> None:
    kb_id = payload.get("kb_id")
    if not kb_id:
        raise CustomException("请选择所属知识库")
    kb = await KnowledgeBase.get_or_none(id=kb_id)
    if kb is None:
        raise CustomException("未找到知识库")
    # 停用的库不该再进新资料，前端下拉框已经过滤过，后端再拦一次
    if kb.status != "正常":
        raise CustomException("该知识库已停用，不能上传文档")
    file_url = payload.get("file_url")
    if not file_url:
        raise CustomException("请先上传文件")
    # 文档名不填就用上传的文件名顶上，保证列表页名称列不为空
    file_name = payload.get("file_name")
    name = payload.get("name") or file_name
    if not name:
        raise CustomException("请输入文档名称")
    file_type = resolve_file_type(file_name)
    await KnowledgeDocument.create(
        kb_id=kb_id,
        name=name,
        file_name=file_name,
        file_url=file_url,
        file_type=file_type,
        file_size=payload.get("file_size") or 0,
        upload_user_id=current_user.id,
    )
    # 文档数是知识库列表页直接展示的冗余列，新增后立刻同步
    await _refresh_document_count(kb_id)


async def update(doc_id: int | None, payload: dict) -> None:
    if doc_id is None:
        raise CustomException("文档ID不能为空")
    doc = await KnowledgeDocument.get_or_none(id=doc_id)
    if doc is None:
        raise CustomException("未找到文档")
    name = payload.get("name")
    if not name:
        raise CustomException("请输入文档名称")
    file_url = payload.get("file_url")
    if not file_url:
        raise CustomException("请先上传文件")
    file_name = payload.get("file_name")
    file_type = resolve_file_type(file_name)
    update_data = {
        "name": name,
        "file_name": file_name,
        "file_url": file_url,
        "file_type": file_type,
        "file_size": payload.get("file_size") or 0,
    }
    # 换了文件，之前解析出来的字数、片段数、解析状态全部作废，回到初始状态，
    # 需要重新解析和重新向量化
    if file_url != doc.file_url:
        update_data.update(
            parse_status="待解析",
            parse_error=None,
            has_table="否",
            has_ocr="否",
            char_count=0,
            chunk_count=0,
            vector_status="待向量化",
        )
    await KnowledgeDocument.filter(id=doc_id).update(**update_data)


async def _clear_vectors(doc: KnowledgeDocument) -> None:
    """删文档前顺带清掉它在向量库里的向量，避免留下查得到却没有出处的孤儿向量。

    只有向量化过的文档才需要连向量库，没做过向量化的直接跳过，
    这样没装 PGVector 时也能正常删文档。
    """
    if doc.vector_status in {"已完成", "失败", "向量化中"}:
        await vector_store.delete_by_document(doc.id)


async def delete(doc_id: int) -> None:
    doc = await KnowledgeDocument.get_or_none(id=doc_id)
    if doc is None:
        raise CustomException("未找到文档")
    kb_id = doc.kb_id
    await _clear_vectors(doc)
    # 片段挂在文档下，文档没了片段也要一起清掉
    await KnowledgeChunk.filter(document_id=doc_id).delete()
    await KnowledgeDocument.filter(id=doc_id).delete()
    # 删完文档要把知识库上的文档数减下来
    await _refresh_document_count(kb_id)
    await _refresh_chunk_count(kb_id)


async def delete_batch(ids: List[int]) -> None:
    # 先记下这批文档涉及哪些知识库，删完后逐个重算文档数
    docs = await KnowledgeDocument.filter(id__in=ids)
    kb_ids = {doc.kb_id for doc in docs}
    for doc in docs:
        await _clear_vectors(doc)
    await KnowledgeChunk.filter(document_id__in=ids).delete()
    await KnowledgeDocument.filter(id__in=ids).delete()
    for kb_id in kb_ids:
        await _refresh_document_count(kb_id)
        await _refresh_chunk_count(kb_id)


async def select_by_id(doc_id: int) -> dict:
    doc = await KnowledgeDocument.get_or_none(id=doc_id)
    if doc is None:
        raise CustomException("未找到文档")
    kb = await KnowledgeBase.get_or_none(id=doc.kb_id)
    return document_dict(doc, kb.name if kb else None)


async def select_page(
    kb_id: int | None = None,
    name: str = "",
    parse_status: str = "",
    page_num: int = 1,
    page_size: int = 10,
) -> PageInfo:
    # name 来自页面顶部文档名称输入框，空字符串时等于不加这个条件
    query = KnowledgeDocument.filter(name__contains=name)
    # kb_id 来自知识库下拉框，不选表示查所有库的文档
    if kb_id:
        query = query.filter(kb_id=kb_id)
    # parse_status 来自解析状态下拉框
    if parse_status:
        query = query.filter(parse_status=parse_status)
    docs = await query.order_by("-id").offset((page_num - 1) * page_size).limit(page_size)
    total = await query.count()
    kb_names = await _kb_name_map(docs)
    return PageInfo(total=total, list=[document_dict(doc, kb_names.get(doc.kb_id)) for doc in docs])
