"""评测报告对比与链路追踪状态测试。"""

import json
import uuid

import pytest

from models import EvalDataset, EvalReport, EvalTask
from service import eval_report_service


def _snapshot(**overrides):
    strategy = {
        "vector_enabled": "是",
        "bm25_enabled": "否",
        "rerank_enabled": "否",
        "query_rewrite_enabled": "否",
        "rewrite_type": None,
        "parent_recall_enabled": "否",
    }
    strategy.update(overrides)
    return json.dumps(strategy, ensure_ascii=False)


@pytest.fixture()
async def reports(db):
    """造一个评测集、两条任务和两份报告。"""
    dataset = await EvalDataset.create(name="对比测试集-单元测试专用")
    other = await EvalDataset.create(name="另一个测试集-单元测试专用")
    task_one = await EvalTask.create(
        task_no=uuid.uuid4().hex, dataset_id=dataset.id, task_status="已完成", cost_millis=6000
    )
    task_two = await EvalTask.create(
        task_no=uuid.uuid4().hex, dataset_id=dataset.id, task_status="已完成", cost_millis=15000
    )
    task_other = await EvalTask.create(
        task_no=uuid.uuid4().hex, dataset_id=other.id, task_status="已完成", cost_millis=5000
    )
    report_one = await EvalReport.create(
        report_no=uuid.uuid4().hex,
        task_id=task_one.id,
        strategy_name="基线-纯向量检索",
        strategy_snapshot=_snapshot(),
        case_count=5,
        context_recall_avg=0.62,
        context_precision_avg=0.44,
        faithfulness_avg=0.81,
        answer_relevancy_avg=0.88,
        overall_score=0.6875,
    )
    report_two = await EvalReport.create(
        report_no=uuid.uuid4().hex,
        task_id=task_two.id,
        strategy_name="完整-混合检索加重排加改写",
        strategy_snapshot=_snapshot(
            bm25_enabled="是", rerank_enabled="是",
            query_rewrite_enabled="是", rewrite_type="多查询扩展",
            parent_recall_enabled="是",
        ),
        case_count=5,
        context_recall_avg=0.88,
        context_precision_avg=0.79,
        faithfulness_avg=0.91,
        answer_relevancy_avg=0.90,
        overall_score=0.87,
    )
    report_other = await EvalReport.create(
        report_no=uuid.uuid4().hex,
        task_id=task_other.id,
        strategy_name="别的评测集的报告",
        strategy_snapshot=_snapshot(),
        case_count=3,
        overall_score=0.5,
    )

    yield {
        "dataset": dataset,
        "one": report_one,
        "two": report_two,
        "other": report_other,
    }

    await EvalReport.filter(id__in=[report_one.id, report_two.id, report_other.id]).delete()
    await EvalTask.filter(id__in=[task_one.id, task_two.id, task_other.id]).delete()
    await EvalDataset.filter(id__in=[dataset.id, other.id]).delete()


def test_enabled_abilities_reads_snapshot():
    """从策略快照里读出开了哪几步。"""
    abilities = eval_report_service._enabled_abilities(
        _snapshot(bm25_enabled="是", rerank_enabled="是", query_rewrite_enabled="是", rewrite_type="HyDE")
    )
    assert abilities == ["向量", "BM25", "重排", "HyDE"]


def test_enabled_abilities_handles_broken_snapshot():
    """快照不是合法 JSON 时返回空列表，不抛异常。"""
    assert eval_report_service._enabled_abilities("不是 JSON") == []
    assert eval_report_service._enabled_abilities(None) == []


async def test_select_reports_carries_cost_and_abilities(reports):
    """报告列表带上耗时和这套策略开了哪几步。"""
    items = await eval_report_service.select_reports(reports["dataset"].id)
    target = [item for item in items if item["id"] == reports["two"].id][0]
    assert target["cost_millis"] == 15000
    # 五条用例，平均每条 3000 毫秒
    assert target["avg_cost_millis"] == 3000
    assert "重排" in target["abilities"]


async def test_compare_requires_two_reports(reports):
    """只选一份时给出人话提示。"""
    with pytest.raises(Exception) as excinfo:
        await eval_report_service.compare([reports["one"].id])
    assert "至少选择两份报告" in str(excinfo.value)


async def test_compare_rejects_cross_dataset(reports):
    """不同评测集的报告不能对比，用例不一样分数没有可比性。"""
    with pytest.raises(Exception) as excinfo:
        await eval_report_service.compare([reports["one"].id, reports["other"].id])
    assert "只能对比同一个评测集" in str(excinfo.value)


async def test_compare_builds_series(reports):
    """对比结果按指标分组，每组里各报告的分数排成一列。"""
    outcome = await eval_report_service.compare([reports["one"].id, reports["two"].id])

    assert len(outcome["columns"]) == 2
    assert outcome["columns"][0]["strategy_name"] == "基线-纯向量检索"
    # 四个指标各一组
    assert [item["metric"] for item in outcome["series"]] == [
        "上下文召回", "上下文精度", "忠实度", "答案相关性"
    ]
    recall = [item for item in outcome["series"] if item["field"] == "context_recall_avg"][0]
    # 顺序和传进去的报告 ID 顺序一致
    assert recall["values"] == [0.62, 0.88]


async def test_compare_keeps_requested_order(reports):
    """列的顺序和用户选择的顺序一致。"""
    outcome = await eval_report_service.compare([reports["two"].id, reports["one"].id])
    assert outcome["columns"][0]["strategy_name"] == "完整-混合检索加重排加改写"
