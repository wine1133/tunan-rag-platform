"""批量评测。

对整个评测集逐条跑一遍问答，再用 LLM-as-judge 算出四个指标，汇总成报告。

一条用例的完整流程：

    按策略检索 → 生成答案 → 算四个指标 → 落 eval_case_result

跑完把所有用例的分数取平均，连同策略快照一起存进 eval_report，
第 29 章的看板拿多份报告做横向对比。
"""

import json
import uuid

from ai import evaluator, model_factory, prompt_loader
from ai.graph import build_context
from common.exception_handler import CustomException
from common.result import PageInfo
from common.times import cost_millis, now
from models import (
    EvalCase,
    EvalCaseResult,
    EvalDataset,
    EvalReport,
    EvalTask,
    RetrievalStrategy,
)
from service import retrieval_service

ERROR_MAX_LENGTH = 500
# 四个指标的完整定义：测什么、测哪一段、达标线多少、低了该调哪一环。
# 结论文案和页面上的指标卡片都读这一份，不在前端另写一套阈值和说明文案。
#
# stage 把指标归到 RAG 的两段上：检索段负责"把该给的资料找出来"，
# 生成段负责"根据资料写出答案"。分数低的时候先看它属于哪一段，
# 就知道该去调检索策略还是调 Prompt。
METRICS = [
    {
        "field": "context_recall",
        "label": "上下文召回",
        "en": "Context Recall",
        "stage": "找资料",
        # 页面卡片上直接显示这句，学的人不用记住指标名也知道它在测什么
        "plain": "标准答案里说的东西，检索找回来了吗",
        "threshold": 0.7,
        "advice": "该找的资料没找回来，建议开混合检索或查询改写",
    },
    {
        "field": "context_precision",
        "label": "上下文精度",
        "en": "Context Precision",
        "stage": "找资料",
        "plain": "找回来的资料里，有用的排在前面吗",
        "threshold": 0.6,
        "advice": "有用的资料排在后面，建议开重排",
    },
    {
        "field": "faithfulness",
        "label": "忠实度",
        "en": "Faithfulness",
        "stage": "写答案",
        "plain": "答案里每句话，在资料里有出处吗（有没有编）",
        "threshold": 0.8,
        "advice": "答案里有内容找不到出处，建议加强 RAG_ANSWER 模板的约束",
    },
    {
        "field": "answer_relevancy",
        "label": "答案相关性",
        "en": "Answer Relevancy",
        "stage": "写答案",
        "plain": "答案是在回答这个问题吗（有没有跑题）",
        "threshold": 0.7,
        "advice": "回答没有针对问题，建议调整生成 Prompt",
    },
]
# 一次评测最多跑多少条。第 26 章说过评测成本主要在输入 token，
# 20 条已经是一轮几十万 token 的量级，默认卡在这里
MAX_CASE_COUNT = 20


def _dump(value) -> str:
    return json.dumps(value, ensure_ascii=False, default=str)


async def start(
    dataset_id: int,
    strategy_id: int | None,
    user_id: int | None,
    prompt_code: str = "RAG_ANSWER",
) -> tuple[int, dict]:
    """校验并建任务。"""
    dataset = await EvalDataset.get_or_none(id=dataset_id)
    if dataset is None:
        raise CustomException("未找到评测集")
    cases = await EvalCase.filter(dataset_id=dataset_id, enabled="是")
    if not cases:
        raise CustomException("该评测集里没有启用的用例，请先补充标准答案并启用")
    if len(cases) > MAX_CASE_COUNT:
        raise CustomException(
            f"一次最多评测 {MAX_CASE_COUNT} 条用例，当前有 {len(cases)} 条，"
            "请先停用一部分或拆成多个评测集"
        )
    strategy = await retrieval_service.load_strategy(strategy_id)
    # 裁判模型和问答用的是同一条对话模型配置，先确认它可用
    judge_config = await model_factory.load_enabled(model_factory.CHAT)
    task = await EvalTask.create(
        task_no=uuid.uuid4().hex,
        dataset_id=dataset_id,
        retrieval_strategy_id=strategy["id"],
        # 报告放一周后再看，要知道当时开了哪些开关，对比才有意义
        strategy_snapshot=_dump(strategy),
        judge_model_id=judge_config.id,
        task_status="评测中",
        total_count=len(cases),
        start_time=now(),
        create_user_id=user_id,
    )
    return task.id, {"strategy": strategy, "prompt_code": prompt_code}


async def run(task_id: int, context: dict) -> None:
    """后台任务：逐条跑问答并打分。"""
    task = await EvalTask.get_or_none(id=task_id)
    if task is None:
        return
    started = now()
    strategy = context["strategy"]
    prompt_code = context["prompt_code"]
    success = 0
    failed = 0
    try:
        dataset = await EvalDataset.get_or_none(id=task.dataset_id)
        cases = await EvalCase.filter(dataset_id=task.dataset_id, enabled="是").order_by("id")
        kb_ids = [dataset.kb_id] if dataset and dataset.kb_id else []
        if not kb_ids:
            raise CustomException("评测集没有关联知识库，请先在评测集上设置")

        for case in cases:
            case_started = now()
            try:
                outcome = await retrieval_service.retrieve(kb_ids, case.question, strategy)
                results = outcome["results"]
                contents = [item["content"] for item in results]
                retrieved_ids = [item["chunk_id"] for item in results if item.get("chunk_id")]

                answer = await _generate(prompt_code, contents, case.question)
                reference_ids = _parse_ids(case.reference_chunk_ids)
                scores = await evaluator.evaluate_case(
                    case.question,
                    case.ground_truth or "",
                    answer,
                    contents,
                    retrieved_ids,
                    reference_ids,
                )
                await EvalCaseResult.create(
                    task_id=task_id,
                    case_id=case.id,
                    answer=answer,
                    retrieved_chunk_ids=",".join(str(item) for item in retrieved_ids),
                    cost_millis=cost_millis(case_started),
                    **scores,
                )
                success += 1
            except Exception as exc:
                # 单条失败不影响整批，把失败原因记在这条结果上继续往下跑
                message = exc.message if isinstance(exc, CustomException) else str(exc)
                await EvalCaseResult.create(
                    task_id=task_id,
                    case_id=case.id,
                    error_message=message[:ERROR_MAX_LENGTH],
                    cost_millis=cost_millis(case_started),
                )
                failed += 1
            # 每条跑完更新一次进度，页面刷新能看到跑到哪了
            await EvalTask.filter(id=task_id).update(success_count=success, fail_count=failed)

        await _build_report(task_id, strategy)
        await EvalTask.filter(id=task_id).update(
            task_status="已完成" if failed == 0 else "失败",
            success_count=success,
            fail_count=failed,
            end_time=now(),
            cost_millis=cost_millis(started),
        )
    except Exception as exc:
        message = exc.message if isinstance(exc, CustomException) else f"评测失败：{exc}"
        await EvalTask.filter(id=task_id).update(
            task_status="失败",
            success_count=success,
            fail_count=failed,
            error_message=message[:ERROR_MAX_LENGTH],
            end_time=now(),
            cost_millis=cost_millis(started),
        )


def _parse_ids(raw: str | None) -> list[int]:
    if not raw:
        return []
    ids = []
    for item in raw.split(","):
        item = item.strip()
        if item.isdigit():
            ids.append(int(item))
    return ids


async def _generate(prompt_code: str, contents: list[str], question: str) -> str:
    """按被评测的 Prompt 生成答案。"""
    prompt = await prompt_loader.render(
        prompt_code,
        context=build_context([{"content": item} for item in contents]),
        question=question,
    )
    config = await model_factory.load_enabled(model_factory.CHAT)
    model = model_factory.build_chat_model(config)
    reply = await model.ainvoke(prompt)
    return str(reply.content).strip()


def _average(values: list) -> float | None:
    """算平均分。一条成功的都没有时返回空，不返回 0 造成误解。"""
    numbers = [float(item) for item in values if item is not None]
    if not numbers:
        return None
    return round(sum(numbers) / len(numbers), 4)


async def _build_report(task_id: int, strategy: dict) -> None:
    """把这次任务的所有用例结果汇总成一份报告。"""
    results = await EvalCaseResult.filter(task_id=task_id, error_message=None)
    recall = _average([item.context_recall for item in results])
    precision = _average([item.context_precision for item in results])
    faithful = _average([item.faithfulness for item in results])
    relevancy = _average([item.answer_relevancy for item in results])
    overall = _average([value for value in (recall, precision, faithful, relevancy) if value is not None])
    await EvalReport.create(
        report_no=uuid.uuid4().hex,
        task_id=task_id,
        strategy_name=strategy["name"],
        strategy_snapshot=_dump(strategy),
        case_count=len(results),
        context_recall_avg=recall,
        context_precision_avg=precision,
        faithfulness_avg=faithful,
        answer_relevancy_avg=relevancy,
        overall_score=overall,
        conclusion=_conclusion(recall, precision, faithful, relevancy),
    )


def _conclusion(recall, precision, faithful, relevancy) -> str:
    """按第 26 章那张对照表，把低分指标翻译成该去调哪一环。"""
    values = {
        "context_recall": recall,
        "context_precision": precision,
        "faithfulness": faithful,
        "answer_relevancy": relevancy,
    }
    advices = [
        f"{item['label']}偏低，{item['advice']}"
        for item in METRICS
        if values[item["field"]] is not None and values[item["field"]] < item["threshold"]
    ]
    if not advices:
        return "四项指标都在合理区间。"
    return "；".join(advices) + "。"


def metric_cards(report) -> list[dict]:
    """页面上四张指标卡片的数据。

    指标说明、达标线和低分时的建议都来自 METRICS，和结论文案同一个来源。
    页面据此把偏低的那张标红，不用自己判断多少算低，也不用另写一份说明文案。
    """
    cards = []
    for item in METRICS:
        raw = getattr(report, f"{item['field']}_avg", None)
        value = float(raw) if raw is not None else None
        cards.append(
            {
                **item,
                "value": value,
                # 没跑出分数时不判达标也不判偏低，页面显示为 —
                "ok": None if value is None else value >= item["threshold"],
            }
        )
    return cards


async def select_tasks(dataset_id: int | None = None, page_num: int = 1, page_size: int = 10) -> PageInfo:
    query = EvalTask.all()
    if dataset_id:
        query = query.filter(dataset_id=dataset_id)
    tasks = await query.order_by("-id").offset((page_num - 1) * page_size).limit(page_size)
    total = await query.count()
    # 列表上要显示"这次评的是哪套题、用的哪套策略"，两个名字各查一次批量回填
    # 列表上要显示"这次评的是哪套题、用的哪套策略"
    datasets = await EvalDataset.filter(id__in=[item.dataset_id for item in tasks])
    dataset_names = {item.id: item.name for item in datasets}
    # 策略名从任务自己的 strategy_snapshot 里取，不从报告取：
    # 报告要跑完才生成，正在评测中的任务这一列会是空的，
    # 而 snapshot 在建任务时就写好了，从头到尾都有
    strategy_names = {}
    for item in tasks:
        try:
            strategy_names[item.id] = json.loads(item.strategy_snapshot or "{}").get("name")
        except json.JSONDecodeError:
            strategy_names[item.id] = None
    return PageInfo(
        total=total,
        list=[
            {
                "id": item.id,
                "task_no": item.task_no,
                "dataset_id": item.dataset_id,
                "dataset_name": dataset_names.get(item.dataset_id),
                "strategy_name": strategy_names.get(item.id),
                "retrieval_strategy_id": item.retrieval_strategy_id,
                "task_status": item.task_status,
                "total_count": item.total_count,
                "success_count": item.success_count,
                "fail_count": item.fail_count,
                "error_message": item.error_message,
                "cost_millis": item.cost_millis,
                "create_time": item.create_time,
            }
            for item in tasks
        ],
    )


async def delete(task_id: int) -> None:
    """删除一次评测任务，连同它的用例结果和报告一起删。

    三张表是一次评测的完整记录，留下任何一张都会变成对不上号的孤儿数据：
    报告没了任务不知道是谁跑的，结果没了报告点进去是空的。
    """
    task = await EvalTask.get_or_none(id=task_id)
    if task is None:
        raise CustomException("未找到评测任务")
    if task.task_status == "评测中":
        raise CustomException("这次评测还在跑，等它结束再删")
    await EvalCaseResult.filter(task_id=task_id).delete()
    await EvalReport.filter(task_id=task_id).delete()
    await EvalTask.filter(id=task_id).delete()


async def select_results(task_id: int) -> dict:
    """一次评测的详细结果，含每条用例的四个指标。"""
    task = await EvalTask.get_or_none(id=task_id)
    if task is None:
        raise CustomException("未找到评测任务")
    report = await EvalReport.get_or_none(task_id=task_id)
    dataset = await EvalDataset.get_or_none(id=task.dataset_id)
    dataset_name = dataset.name if dataset else None
    results = await EvalCaseResult.filter(task_id=task_id).order_by("id")
    case_ids = [item.case_id for item in results]
    cases = await EvalCase.filter(id__in=case_ids)
    case_map = {case.id: case for case in cases}
    return {
        "task": {
            "id": task.id,
            "task_status": task.task_status,
            "total_count": task.total_count,
            "success_count": task.success_count,
            "fail_count": task.fail_count,
            "cost_millis": task.cost_millis,
            "strategy_snapshot": task.strategy_snapshot,
        },
        "report": {
            "strategy_name": report.strategy_name,
            # 报告标题上要写清这次评的是哪套题，不然几份报告摆一起分不出来
            "dataset_name": dataset_name,
            "case_count": report.case_count,
            "context_recall_avg": float(report.context_recall_avg) if report.context_recall_avg is not None else None,
            "context_precision_avg": float(report.context_precision_avg) if report.context_precision_avg is not None else None,
            "faithfulness_avg": float(report.faithfulness_avg) if report.faithfulness_avg is not None else None,
            "answer_relevancy_avg": float(report.answer_relevancy_avg) if report.answer_relevancy_avg is not None else None,
            "overall_score": float(report.overall_score) if report.overall_score is not None else None,
            "conclusion": report.conclusion,
            # 每张卡片带上达标线和是否达标，页面不用自己判断多少算低
            "metrics": metric_cards(report),
        }
        if report
        else None,
        "results": [
            {
                "id": item.id,
                "case_id": item.case_id,
                "question": case_map[item.case_id].question if item.case_id in case_map else "",
                "ground_truth": case_map[item.case_id].ground_truth if item.case_id in case_map else "",
                "answer": item.answer,
                "context_recall": float(item.context_recall) if item.context_recall is not None else None,
                "context_precision": float(item.context_precision) if item.context_precision is not None else None,
                "faithfulness": float(item.faithfulness) if item.faithfulness is not None else None,
                "answer_relevancy": float(item.answer_relevancy) if item.answer_relevancy is not None else None,
                "avg_score": float(item.avg_score) if item.avg_score is not None else None,
                "error_message": item.error_message,
                "cost_millis": item.cost_millis,
            }
            for item in results
        ],
    }
