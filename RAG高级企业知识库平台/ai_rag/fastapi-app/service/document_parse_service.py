"""文档解析业务逻辑。

解析可能要跑 OCR，耗时从几百毫秒到几十秒不等，接口不能同步等着，
所以接口只负责建任务、把状态改成"解析中"就返回，真正的解析在后台任务里跑。
页面刷新列表就能看到最新状态。
"""

import asyncio
import os

from ai import loader
from common.exception_handler import CustomException
from common.times import cost_millis, now
from models import DocumentProcessTask, KnowledgeDocument
from service.file_service import UPLOAD_DIR

# 写进 error_message 列的长度上限，第三方库抛出的异常信息经常上千字
ERROR_MAX_LENGTH = 500


def _truncate(message: str) -> str:
    return message[:ERROR_MAX_LENGTH]


def _local_path(doc: KnowledgeDocument) -> str:
    """由磁盘文件名拼出本地路径，文件不在了就没法解析。"""
    if not doc.file_name:
        raise CustomException("该文档没有关联文件，请重新上传")
    file_path = os.path.join(UPLOAD_DIR, doc.file_name)
    if not os.path.exists(file_path):
        raise CustomException("原始文件不存在，请重新上传")
    return file_path


async def start_parse(doc_id: int) -> int:
    """校验并把文档置为解析中，返回新建的任务 ID。"""
    doc = await KnowledgeDocument.get_or_none(id=doc_id)
    if doc is None:
        raise CustomException("未找到文档")
    if doc.parse_status == "解析中":
        raise CustomException("该文档正在解析中，请稍候")
    # 先确认文件还在磁盘上，避免建了任务才发现没文件可解析
    _local_path(doc)
    task = await DocumentProcessTask.create(
        kb_id=doc.kb_id,
        document_id=doc.id,
        task_type="文档解析",
        task_status="处理中",
        total_count=1,
        start_time=now(),
    )
    # 状态先置为解析中，页面刷新时能看到它在跑，也挡住重复点击
    await KnowledgeDocument.filter(id=doc_id).update(parse_status="解析中", parse_error=None)
    return task.id


async def run_parse(doc_id: int, task_id: int) -> None:
    """后台任务：真正读文件、写解析结果。"""
    doc = await KnowledgeDocument.get_or_none(id=doc_id)
    if doc is None:
        return
    started = now()
    try:
        file_path = _local_path(doc)
        # 解析是纯 CPU 的同步操作，丢到线程里执行，不阻塞事件循环上的其他请求
        outcome = await asyncio.to_thread(loader.parse, file_path, doc.file_type)
        text = outcome.text.strip()
        if not text:
            raise CustomException("没有解析出任何文本，请确认文件内容不是空的")
        await KnowledgeDocument.filter(id=doc_id).update(
            parse_status="解析完成",
            parse_error=None,
            parsed_text=text,
            # 字符数是切分前的体量参考，第 09 章按它估算能切出多少片段
            char_count=len(text),
            has_table="是" if outcome.has_table else "否",
            has_ocr="是" if outcome.has_ocr else "否",
            # 重新解析后原有片段和向量都作废，向量化状态回到初始值
            vector_status="待向量化",
            chunk_count=0,
        )
        await DocumentProcessTask.filter(id=task_id).update(
            task_status="已完成",
            success_count=1,
            end_time=now(),
            cost_millis=cost_millis(started),
        )
    except Exception as exc:
        # 失败原因既要写到文档上让列表页能看到，也要写进任务记录留档
        message = exc.message if isinstance(exc, CustomException) else f"解析失败：{exc}"
        await KnowledgeDocument.filter(id=doc_id).update(
            parse_status="解析失败",
            parse_error=_truncate(message),
        )
        await DocumentProcessTask.filter(id=task_id).update(
            task_status="失败",
            fail_count=1,
            error_message=_truncate(message),
            end_time=now(),
            cost_millis=cost_millis(started),
        )


async def select_parsed_text(doc_id: int) -> dict:
    """查看解析结果，供页面上的"查看解析文本"弹窗使用。"""
    doc = await KnowledgeDocument.get_or_none(id=doc_id)
    if doc is None:
        raise CustomException("未找到文档")
    return {
        "id": doc.id,
        "name": doc.name,
        "parse_status": doc.parse_status,
        "parse_error": doc.parse_error,
        "char_count": doc.char_count,
        "has_table": doc.has_table,
        "has_ocr": doc.has_ocr,
        "parsed_text": doc.parsed_text,
    }


async def select_tasks(document_id: int) -> list[dict]:
    """查某篇文档的处理任务记录，按时间倒序。"""
    tasks = await DocumentProcessTask.filter(document_id=document_id).order_by("-id").limit(20)
    return [
        {
            "id": task.id,
            "task_type": task.task_type,
            "task_status": task.task_status,
            "success_count": task.success_count,
            "fail_count": task.fail_count,
            "error_message": task.error_message,
            "start_time": task.start_time,
            "end_time": task.end_time,
            "cost_millis": task.cost_millis,
        }
        for task in tasks
    ]
