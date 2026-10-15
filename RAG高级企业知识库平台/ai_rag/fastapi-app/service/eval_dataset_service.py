"""评测集管理。

评测用例有三个来源，对应三种真实场景：

    手工录入  业务方最关心的那几个问题，一条条录进来
    文档生成  让模型读文档自动出问答对，快速铺量
    反馈沉淀  第 25 章用户点踩的问题，这些是系统真实答错的地方

三个来源的用例混在同一个评测集里，跑分时一视同仁。
"""

import json
import re
from typing import List

from ai import model_factory, prompt_loader
from common.exception_handler import CustomException
from common.result import PageInfo
from models import (
    ChatMessage,
    EvalCase,
    EvalDataset,
    KnowledgeChunk,
    MessageFeedback,
)

# 一次自动生成最多产出多少条，太多既慢又容易出低质量用例
MAX_GENERATE_COUNT = 20
# 送给模型生成问答对的片段最多多少字
MAX_GENERATE_CHARS = 4000
SOURCES = {"手工录入", "文档生成", "反馈沉淀"}


def dataset_dict(dataset: EvalDataset) -> dict:
    return {
        "id": dataset.id,
        "name": dataset.name,
        "kb_id": dataset.kb_id,
        "description": dataset.description,
        "case_count": dataset.case_count,
        "create_time": dataset.create_time,
        "update_time": dataset.update_time,
    }


def case_dict(case: EvalCase) -> dict:
    return {
        "id": case.id,
        "dataset_id": case.dataset_id,
        "question": case.question,
        "ground_truth": case.ground_truth,
        "reference_chunk_ids": case.reference_chunk_ids,
        "source": case.source,
        "enabled": case.enabled,
        "remark": case.remark,
        "create_time": case.create_time,
    }


async def reference_chunks(case_id: int) -> list[dict]:
    """取一条用例的来源片段原文，用来核对标准答案对不对。

    标准答案是模型照着片段生成的，模型看错段、把相邻条款张冠李戴都有可能，
    人工审核时把问题、标准答案和片段原文摆在一起才判断得了。
    """
    case = await EvalCase.get_or_none(id=case_id)
    if case is None:
        raise CustomException("未找到评测用例")
    ids = [item.strip() for item in (case.reference_chunk_ids or "").split(",") if item.strip().isdigit()]
    if not ids:
        return []
    chunks = await KnowledgeChunk.filter(id__in=[int(item) for item in ids])
    # 按 reference_chunk_ids 里记的顺序返回，和标注顺序一致
    order = {int(item): index for index, item in enumerate(ids)}
    chunks.sort(key=lambda chunk: order.get(chunk.id, 0))
    return [
        {
            "chunk_id": chunk.id,
            "document_id": chunk.document_id,
            "chunk_index": chunk.chunk_index,
            "chunk_type": chunk.chunk_type,
            "page_no": chunk.page_no,
            "content": chunk.content,
        }
        for chunk in chunks
    ]


async def _refresh_case_count(dataset_id: int) -> None:
    """重算评测集的用例数，增删用例后都要调一次。"""
    count = await EvalCase.filter(dataset_id=dataset_id).count()
    await EvalDataset.filter(id=dataset_id).update(case_count=count)


async def add_dataset(payload: dict) -> None:
    if not payload.get("name"):
        raise CustomException("请输入评测集名称")
    if await EvalDataset.get_or_none(name=payload["name"]):
        raise CustomException("评测集名称重复")
    await EvalDataset.create(
        name=payload["name"],
        kb_id=payload.get("kb_id"),
        description=payload.get("description"),
    )


async def update_dataset(dataset_id: int | None, payload: dict) -> None:
    if dataset_id is None:
        raise CustomException("评测集ID不能为空")
    if await EvalDataset.get_or_none(id=dataset_id) is None:
        raise CustomException("未找到评测集")
    if not payload.get("name"):
        raise CustomException("请输入评测集名称")
    if await EvalDataset.filter(name=payload["name"]).exclude(id=dataset_id).exists():
        raise CustomException("评测集名称重复")
    await EvalDataset.filter(id=dataset_id).update(
        name=payload["name"],
        kb_id=payload.get("kb_id"),
        description=payload.get("description"),
    )


async def delete_dataset(dataset_id: int) -> None:
    if await EvalDataset.get_or_none(id=dataset_id) is None:
        raise CustomException("未找到评测集")
    # 用例跟着删，不留孤儿用例
    await EvalCase.filter(dataset_id=dataset_id).delete()
    await EvalDataset.filter(id=dataset_id).delete()


async def select_datasets() -> List[dict]:
    datasets = await EvalDataset.all().order_by("-id")
    return [dataset_dict(item) for item in datasets]


async def select_dataset_page(name: str = "", page_num: int = 1, page_size: int = 10) -> PageInfo:
    query = EvalDataset.filter(name__contains=name)
    items = await query.order_by("-id").offset((page_num - 1) * page_size).limit(page_size)
    total = await query.count()
    return PageInfo(total=total, list=[dataset_dict(item) for item in items])


async def add_case(payload: dict) -> None:
    dataset_id = payload.get("dataset_id")
    if not dataset_id:
        raise CustomException("请选择评测集")
    if await EvalDataset.get_or_none(id=dataset_id) is None:
        raise CustomException("未找到评测集")
    if not payload.get("question"):
        raise CustomException("请输入问题")
    # Context Recall 这个指标必须有标准答案才能算，没有的话这条用例只能算三个指标
    if not payload.get("ground_truth"):
        raise CustomException("请输入标准答案，没有它就算不了上下文召回指标")
    source = payload.get("source") or "手工录入"
    if source not in SOURCES:
        raise CustomException("来源参数错误")
    await EvalCase.create(
        dataset_id=dataset_id,
        question=payload["question"],
        ground_truth=payload["ground_truth"],
        reference_chunk_ids=payload.get("reference_chunk_ids"),
        source=source,
        enabled=payload.get("enabled") or "是",
        remark=payload.get("remark"),
    )
    await _refresh_case_count(dataset_id)


async def update_case(case_id: int | None, payload: dict) -> None:
    if case_id is None:
        raise CustomException("用例ID不能为空")
    case = await EvalCase.get_or_none(id=case_id)
    if case is None:
        raise CustomException("未找到用例")
    if not payload.get("question"):
        raise CustomException("请输入问题")
    if not payload.get("ground_truth"):
        raise CustomException("请输入标准答案，没有它就算不了上下文召回指标")
    await EvalCase.filter(id=case_id).update(
        question=payload["question"],
        ground_truth=payload["ground_truth"],
        reference_chunk_ids=payload.get("reference_chunk_ids"),
        enabled=payload.get("enabled") or "是",
        remark=payload.get("remark"),
    )


async def delete_case(case_id: int) -> None:
    case = await EvalCase.get_or_none(id=case_id)
    if case is None:
        raise CustomException("未找到用例")
    await EvalCase.filter(id=case_id).delete()
    await _refresh_case_count(case.dataset_id)


async def select_case_page(
    dataset_id: int | None = None,
    source: str = "",
    keyword: str = "",
    page_num: int = 1,
    page_size: int = 10,
) -> PageInfo:
    query = EvalCase.all()
    if dataset_id:
        query = query.filter(dataset_id=dataset_id)
    if source:
        query = query.filter(source=source)
    if keyword:
        query = query.filter(question__contains=keyword)
    cases = await query.order_by("-id").offset((page_num - 1) * page_size).limit(page_size)
    total = await query.count()
    return PageInfo(total=total, list=[case_dict(case) for case in cases])


def parse_generated(text: str) -> List[dict]:
    """解析模型生成的问答对。

    模板要求返回 JSON 数组，但模型经常在外面裹一层 ```json 代码块，
    或者前后带一句解释。这里先把 JSON 数组那一段抠出来再解析。

    source_index 是模型标注的来源片段序号，指向 Prompt 里的 [片段N]。
    它决定这条用例的 Context Recall 拿哪几个片段当参照，模型没标或标错时
    留空，让 Context Recall 退回走语义判断那条路。
    """
    matched = re.search(r"\[.*\]", str(text), re.S)
    if not matched:
        return []
    try:
        items = json.loads(matched.group(0))
    except json.JSONDecodeError:
        return []
    pairs = []
    for item in items:
        if not isinstance(item, dict):
            continue
        question = str(item.get("question") or "").strip()
        ground_truth = str(item.get("ground_truth") or "").strip()
        # 两个字段缺一条这个用例就没法用，直接丢掉
        if not question or not ground_truth:
            continue
        # 来源片段序号，模型可能给数字、字符串、或者一个数组
        raw = item.get("source_index")
        indexes = []
        for one in raw if isinstance(raw, list) else [raw]:
            text_one = str(one).strip()
            # 非数字的内容一律不要，序号后面要拿去反查片段 ID
            if text_one.isdigit():
                indexes.append(int(text_one))
        pairs.append(
            {"question": question, "ground_truth": ground_truth, "source_indexes": indexes}
        )
    return pairs


async def generate_from_document(dataset_id: int, document_id: int, count: int) -> int:
    """让模型读文档片段，自动生成问答对。

    生成的用例带上来源片段 ID，Context Recall 有了确定的参照。
    """
    dataset = await EvalDataset.get_or_none(id=dataset_id)
    if dataset is None:
        raise CustomException("未找到评测集")
    count = max(1, min(count, MAX_GENERATE_COUNT))
    chunks = await KnowledgeChunk.filter(document_id=document_id).exclude(chunk_type="父块").order_by("chunk_index")
    if not chunks:
        raise CustomException("该文档还没有片段，请先解析并切分")

    # 片段在 Prompt 里按 [片段1][片段2] 编号，模型要在每条问答对上标出它用了哪一段。
    # 序号和真实 chunk_id 的对应关系记在 id_of_index 里，回写时换回真实 ID
    parts = []
    id_of_index: dict[int, int] = {}
    used = 0
    for chunk in chunks:
        if used + len(chunk.content) > MAX_GENERATE_CHARS:
            break
        index = len(parts) + 1
        parts.append(f"[片段{index}]\n{chunk.content}")
        id_of_index[index] = chunk.id
        used += len(chunk.content)

    prompt = await prompt_loader.render(
        "EVAL_CASE_GEN", count=count, context="\n\n".join(parts)
    )
    config = await model_factory.load_enabled(model_factory.CHAT)
    model = model_factory.build_chat_model(config)
    reply = await model.ainvoke(prompt)
    pairs = parse_generated(reply.content)
    if not pairs:
        raise CustomException("模型没有返回可用的问答对，请重试或调整 EVAL_CASE_GEN 模板")

    for pair in pairs[:count]:
        # 只把这条问答对真正用到的片段记为参照。
        # 记成整篇文档的全部片段会把 Context Recall 的分母撑大：
        # 答案只在一个片段里，却要求把整篇都召回才算满分，分数永远上不去
        reference_ids = [
            str(id_of_index[index]) for index in pair["source_indexes"] if index in id_of_index
        ]
        await EvalCase.create(
            dataset_id=dataset_id,
            question=pair["question"],
            ground_truth=pair["ground_truth"],
            # 模型没标或标出界时留空，Context Recall 退回按语义判断，不用错的参照
            reference_chunk_ids=",".join(reference_ids) if reference_ids else None,
            source="文档生成",
            enabled="是",
        )
    await _refresh_case_count(dataset_id)
    return len(pairs[:count])


async def convert_from_feedback(dataset_id: int, feedback_ids: List[int] | None = None) -> int:
    """把点踩的问题沉淀成评测用例。

    标准答案留空由人工补——系统答错了，正确答案只有人知道。
    补完之后这条用例才算完整，所以沉淀出来的用例默认是停用的。
    """
    dataset = await EvalDataset.get_or_none(id=dataset_id)
    if dataset is None:
        raise CustomException("未找到评测集")
    query = MessageFeedback.filter(feedback_type="点踩", converted="否")
    if feedback_ids:
        query = query.filter(id__in=feedback_ids)
    feedbacks = await query
    if not feedbacks:
        raise CustomException("没有待沉淀的点踩记录")

    message_ids = [item.message_id for item in feedbacks]
    messages = await ChatMessage.filter(id__in=message_ids)
    session_ids = {message.session_id for message in messages}
    # 回答的上一条就是对应的提问，扫一遍配对
    all_messages = await ChatMessage.filter(session_id__in=session_ids).order_by("id")
    question_of: dict[int, str] = {}
    last_user = {}
    for message in all_messages:
        if message.role == "user":
            last_user[message.session_id] = message.content
        else:
            question_of[message.id] = last_user.get(message.session_id, "")

    created = 0
    for feedback in feedbacks:
        question = question_of.get(feedback.message_id)
        if not question:
            continue
        await EvalCase.create(
            dataset_id=dataset_id,
            question=question,
            # 标准答案留空，等人工补；补完再启用
            ground_truth="",
            source="反馈沉淀",
            enabled="否",
            remark=f"来自点踩反馈 #{feedback.id}" + (f"：{feedback.reason}" if feedback.reason else ""),
        )
        await MessageFeedback.filter(id=feedback.id).update(converted="是")
        created += 1
    await _refresh_case_count(dataset_id)
    return created
