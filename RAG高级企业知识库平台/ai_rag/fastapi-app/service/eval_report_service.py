"""评测报告对比与链路追踪状态。

第 26 章要的那张对比表在这里生成：多份报告并排，四个指标加耗时。
"""

import json

from common.exception_handler import CustomException
from models import EvalDataset, EvalReport, EvalTask

# 四个指标的字段名和中文名，页面和图表共用这一份定义
METRICS = [
    ("context_recall_avg", "上下文召回"),
    ("context_precision_avg", "上下文精度"),
    ("faithfulness_avg", "忠实度"),
    ("answer_relevancy_avg", "答案相关性"),
]


def _float(value) -> float | None:
    return float(value) if value is not None else None


def _enabled_abilities(snapshot: str | None) -> list[str]:
    """从策略快照里读出这套策略开了哪几步，图表上用它标注每根柱子。"""
    if not snapshot:
        return []
    try:
        strategy = json.loads(snapshot)
    except json.JSONDecodeError:
        return []
    abilities = []
    if strategy.get("vector_enabled") == "是":
        abilities.append("向量")
    if strategy.get("bm25_enabled") == "是":
        abilities.append("BM25")
    if strategy.get("rerank_enabled") == "是":
        abilities.append("重排")
    if strategy.get("query_rewrite_enabled") == "是":
        abilities.append(strategy.get("rewrite_type") or "改写")
    if strategy.get("parent_recall_enabled") == "是":
        abilities.append("父块回填")
    return abilities


async def select_reports(dataset_id: int | None = None, limit: int = 20) -> list[dict]:
    """报告列表。同一个评测集下的报告才有可比性，所以支持按评测集筛。"""
    tasks_query = EvalTask.all()
    if dataset_id:
        tasks_query = tasks_query.filter(dataset_id=dataset_id)
    tasks = await tasks_query.order_by("-id").limit(limit)
    task_map = {task.id: task for task in tasks}
    if not task_map:
        return []
    reports = await EvalReport.filter(task_id__in=list(task_map.keys())).order_by("-id")
    return [
        {
            "id": report.id,
            "task_id": report.task_id,
            "dataset_id": task_map[report.task_id].dataset_id,
            "strategy_name": report.strategy_name,
            "abilities": _enabled_abilities(report.strategy_snapshot),
            "case_count": report.case_count,
            "context_recall_avg": _float(report.context_recall_avg),
            "context_precision_avg": _float(report.context_precision_avg),
            "faithfulness_avg": _float(report.faithfulness_avg),
            "answer_relevancy_avg": _float(report.answer_relevancy_avg),
            "overall_score": _float(report.overall_score),
            # 耗时来自任务，第 26 章说过对比表里必须有它
            "cost_millis": task_map[report.task_id].cost_millis,
            "avg_cost_millis": round(task_map[report.task_id].cost_millis / report.case_count)
            if task_map[report.task_id].cost_millis and report.case_count
            else None,
            "conclusion": report.conclusion,
            "create_time": report.create_time,
        }
        for report in reports
    ]


async def compare(report_ids: list[int]) -> dict:
    """把几份报告组装成图表能直接用的结构。

    同一个评测集下的报告才有可比性——用例都不一样，分数没法比。
    """
    if len(report_ids) < 2:
        raise CustomException("请至少选择两份报告进行对比")
    reports = await EvalReport.filter(id__in=report_ids)
    if len(reports) != len(report_ids):
        raise CustomException("有报告不存在，请刷新后重试")
    tasks = await EvalTask.filter(id__in=[report.task_id for report in reports])
    task_map = {task.id: task for task in tasks}
    dataset_ids = {task_map[report.task_id].dataset_id for report in reports}
    if len(dataset_ids) > 1:
        raise CustomException("只能对比同一个评测集下的报告，不同评测集的用例不一样，分数没有可比性")

    # 按报告 ID 顺序排列，页面上列的顺序和用户选的顺序一致
    ordered = sorted(reports, key=lambda item: report_ids.index(item.id))
    columns = [
        {
            "report_id": report.id,
            "strategy_name": report.strategy_name,
            "abilities": _enabled_abilities(report.strategy_snapshot),
            "case_count": report.case_count,
            "overall_score": _float(report.overall_score),
            "cost_millis": task_map[report.task_id].cost_millis,
            "conclusion": report.conclusion,
        }
        for report in ordered
    ]
    # 每个指标一行，各报告的分数排成一列，页面直接渲染成分组柱状图
    series = []
    for field, label in METRICS:
        series.append(
            {
                "metric": label,
                "field": field,
                "values": [_float(getattr(report, field)) for report in ordered],
            }
        )
    dataset = await EvalDataset.get_or_none(id=list(dataset_ids)[0])
    return {
        "dataset_name": dataset.name if dataset else None,
        "columns": columns,
        "series": series,
    }
