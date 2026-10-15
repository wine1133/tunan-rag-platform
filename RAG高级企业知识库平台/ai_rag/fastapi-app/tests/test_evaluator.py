"""评测指标测试。

裁判要调模型，这里把模型换成假实现；
解析、加权算法、直接对比片段 ID 这些都是本项目自己的逻辑，可以直接测。
"""

import pytest

from ai import evaluator, model_factory


def test_parse_verdicts_reads_yes_and_no():
    """逐行的是否结论被正确解析。"""
    assert evaluator.parse_verdicts("是\n否\n是", 3) == [True, False, True]


def test_parse_verdicts_strips_numbering():
    """模型加了编号也能解析。"""
    assert evaluator.parse_verdicts("1. 是\n2. 否", 2) == [True, False]


def test_parse_verdicts_pads_missing_as_false():
    """模型少输出几行时按不通过补齐，分数偏保守不偏乐观。"""
    assert evaluator.parse_verdicts("是", 3) == [True, False, False]


def test_parse_verdicts_truncates_extra():
    """模型多输出几行时截断到期望条数。"""
    assert evaluator.parse_verdicts("是\n是\n是\n是", 2) == [True, True]


def test_parse_verdicts_treats_unknown_as_false():
    """模型没按格式回答时保守判为不通过。"""
    assert evaluator.parse_verdicts("我不确定\n是", 2) == [False, True]


def test_precision_at_k_rewards_top_rank():
    """相关的排第 1 比排第 4 精度高得多。"""
    top = evaluator.precision_at_k([True, False, False, False])
    bottom = evaluator.precision_at_k([False, False, False, True])
    assert top == 1.0
    assert bottom == 0.25
    assert top > bottom


def test_precision_at_k_all_relevant_is_one():
    """全部相关时精度是满分。"""
    assert evaluator.precision_at_k([True, True, True]) == 1.0


def test_precision_at_k_none_relevant_is_zero():
    """一条相关的都没有时精度是 0。"""
    assert evaluator.precision_at_k([False, False]) == 0.0


def test_precision_at_k_empty_is_zero():
    """一条都没召回时精度是 0，不抛异常。"""
    assert evaluator.precision_at_k([]) == 0.0


def test_cosine_identical_vectors():
    """相同向量的余弦相似度是 1。"""
    assert round(evaluator.cosine([1.0, 0.0], [1.0, 0.0]), 6) == 1.0


def test_cosine_orthogonal_vectors():
    """正交向量的余弦相似度是 0。"""
    assert round(evaluator.cosine([1.0, 0.0], [0.0, 1.0]), 6) == 0.0


def test_cosine_handles_zero_vector():
    """零向量不会导致除零错误。"""
    assert evaluator.cosine([0.0, 0.0], [1.0, 1.0]) == 0.0


def test_build_context_truncates():
    """拼给裁判的资料超长时截断。"""
    contents = ["字" * 3000 for _ in range(5)]
    context = evaluator.build_context(contents)
    assert len(context) <= evaluator.MAX_JUDGE_CHARS + 100


async def test_context_recall_uses_reference_ids_without_model(db):
    """用例带了片段 ID 时直接对比，不调模型。"""
    # 应该召回 1、2、3，实际召回了 1、2 和一个无关的 9
    score = await evaluator.context_recall(
        ground_truth="不会被用到",
        contents=[],
        reference_chunk_ids=[1, 2, 3],
        retrieved_chunk_ids=[1, 2, 9],
    )
    assert round(score, 4) == round(2 / 3, 4)


async def test_context_recall_full_hit(db):
    """应该召回的全部召回时，上下文召回是满分。"""
    score = await evaluator.context_recall("", [], [5, 6], [5, 6, 7])
    assert score == 1.0


class FakeReply:
    def __init__(self, content):
        self.content = content


class ScriptedModel:
    def __init__(self, script):
        self.script = list(script)
        self.prompts = []

    async def ainvoke(self, prompt):
        self.prompts.append(prompt)
        return FakeReply(self.script.pop(0) if self.script else "否")


@pytest.fixture()
def fake_judge(monkeypatch, db):
    holder = {}

    async def fake_load_enabled(model_type):
        return object()

    def fake_build(config, temperature=0.0):
        return holder["model"]

    monkeypatch.setattr(model_factory, "load_enabled", fake_load_enabled)
    monkeypatch.setattr(model_factory, "build_chat_model", fake_build)

    def setup(script):
        holder["model"] = ScriptedModel(script)
        return holder["model"]

    return setup


async def test_faithfulness_counts_supported_statements(fake_judge):
    """答案拆成三句，两句有支撑，忠实度是 2/3。"""
    fake_judge([
        # 第一次调用：拆陈述
        "质保期是 24 个月\n非人为损坏免费维修\n超期可购买延保",
        # 第二次调用：逐条判断
        "是\n是\n否",
    ])

    score = await evaluator.faithfulness("答案正文", ["资料内容"])
    assert round(score, 4) == round(2 / 3, 4)


async def test_faithfulness_zero_when_no_statements(fake_judge):
    """拆不出陈述句时返回 0，不抛异常。"""
    fake_judge(["", "是"])
    assert await evaluator.faithfulness("", ["资料"]) == 0.0


async def test_context_precision_uses_rank(fake_judge):
    """相关的排最后时精度明显低于排最前。"""
    fake_judge(["否\n否\n否\n是"])
    score = await evaluator.context_precision("问题", ["a", "b", "c", "d"])
    assert score == 0.25


async def test_context_recall_falls_back_to_model(fake_judge):
    """没有片段 ID 时靠模型判断标准答案有没有被覆盖。"""
    fake_judge([
        "质保期是 24 个月\n超期按次收费",
        "是\n否",
    ])
    score = await evaluator.context_recall("标准答案", ["资料"], None, [1, 2])
    assert score == 0.5
