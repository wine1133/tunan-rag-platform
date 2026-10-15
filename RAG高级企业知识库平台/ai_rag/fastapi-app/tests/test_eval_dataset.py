"""评测集与评测用例测试。

自动生成要调模型，这里把模型换成假实现；
JSON 解析、反馈沉淀、用例数同步这些都是本项目自己的逻辑，可以直接测。
"""

import pytest

from ai import model_factory
from models import (
    ChatMessage,
    ChatSession,
    EvalCase,
    EvalDataset,
    KnowledgeBase,
    KnowledgeChunk,
    KnowledgeDocument,
    MessageFeedback,
    QaApp,
    User,
)
from service import eval_dataset_service

DATASET_NAME = "测试评测集-单元测试专用"


@pytest.fixture()
async def dataset(db):
    record = await EvalDataset.create(name=DATASET_NAME, description="自动化测试")
    yield record
    await EvalCase.filter(dataset_id=record.id).delete()
    await EvalDataset.filter(id=record.id).delete()


def test_parse_generated_handles_code_fence():
    """模型把 JSON 裹在代码块里时也能解析出来。"""
    text = """好的，以下是问答对：
```json
[{"question": "保修期多久", "ground_truth": "24 个月"}]
```
"""
    pairs = eval_dataset_service.parse_generated(text)
    assert len(pairs) == 1
    assert pairs[0]["question"] == "保修期多久"


def test_parse_generated_drops_incomplete_items():
    """缺问题或缺标准答案的条目直接丢掉，不生成半条用例。"""
    text = '[{"question": "有问题没答案"}, {"ground_truth": "有答案没问题"}, {"question": "完整", "ground_truth": "答案"}]'
    pairs = eval_dataset_service.parse_generated(text)
    assert len(pairs) == 1
    assert pairs[0]["question"] == "完整"


def test_parse_generated_returns_empty_on_garbage():
    """模型返回的不是 JSON 时返回空列表，不抛异常。"""
    assert eval_dataset_service.parse_generated("抱歉，我无法完成这个任务") == []


async def test_case_requires_ground_truth(dataset):
    """没有标准答案就算不了上下文召回，必须填。"""
    with pytest.raises(Exception) as excinfo:
        await eval_dataset_service.add_case({"dataset_id": dataset.id, "question": "保修期多久"})
    assert "请输入标准答案" in str(excinfo.value)


async def test_case_count_is_synced(dataset):
    """增删用例后评测集上的用例数跟着变。"""
    await eval_dataset_service.add_case(
        {"dataset_id": dataset.id, "question": "保修期多久", "ground_truth": "24 个月"}
    )
    refreshed = await EvalDataset.get_or_none(id=dataset.id)
    assert refreshed.case_count == 1

    case = await EvalCase.filter(dataset_id=dataset.id).first()
    await eval_dataset_service.delete_case(case.id)
    refreshed = await EvalDataset.get_or_none(id=dataset.id)
    assert refreshed.case_count == 0


async def test_delete_dataset_removes_cases(dataset):
    """删评测集时用例跟着删，不留孤儿用例。"""
    await eval_dataset_service.add_case(
        {"dataset_id": dataset.id, "question": "保修期多久", "ground_truth": "24 个月"}
    )
    await eval_dataset_service.delete_dataset(dataset.id)
    assert await EvalCase.filter(dataset_id=dataset.id).count() == 0


async def test_generate_from_document(dataset, monkeypatch):
    """自动生成的用例带上来源片段 ID，来源标成文档生成。"""
    kb = await KnowledgeBase.create(name="测试生成库-单元测试专用", status="正常")
    doc = await KnowledgeDocument.create(kb_id=kb.id, name="生成测试文档.txt")
    chunk = await KnowledgeChunk.create(
        kb_id=kb.id,
        document_id=doc.id,
        chunk_index=0,
        chunk_type="普通块",
        content="GTE-3000 质保时长为 24 个月。",
        char_count=20,
    )

    class FakeReply:
        # source_index 指向 Prompt 里的 [片段1]，也就是上面建的那条 chunk
        content = '[{"question": "GTE-3000 保修多久", "ground_truth": "24 个月", "source_index": 1}]'

    class FakeModel:
        async def ainvoke(self, prompt):
            return FakeReply()

    async def fake_load_enabled(model_type):
        return object()

    monkeypatch.setattr(model_factory, "load_enabled", fake_load_enabled)
    monkeypatch.setattr(model_factory, "build_chat_model", lambda config, temperature=0.0: FakeModel())

    created = await eval_dataset_service.generate_from_document(dataset.id, doc.id, 5)
    assert created == 1

    case = await EvalCase.filter(dataset_id=dataset.id).first()
    assert case.source == "文档生成"
    assert case.reference_chunk_ids == str(chunk.id)
    assert case.enabled == "是"

    await KnowledgeChunk.filter(kb_id=kb.id).delete()
    await KnowledgeDocument.filter(id=doc.id).delete()
    await KnowledgeBase.filter(id=kb.id).delete()


async def test_generate_without_chunks_is_rejected(dataset):
    """文档还没切分时给出人话提示。"""
    kb = await KnowledgeBase.create(name="空库-单元测试专用", status="正常")
    doc = await KnowledgeDocument.create(kb_id=kb.id, name="没切分的文档.txt")

    with pytest.raises(Exception) as excinfo:
        await eval_dataset_service.generate_from_document(dataset.id, doc.id, 5)
    assert "请先解析并切分" in str(excinfo.value)

    await KnowledgeDocument.filter(id=doc.id).delete()
    await KnowledgeBase.filter(id=kb.id).delete()


async def test_convert_from_feedback(dataset):
    """点踩沉淀成用例，标准答案留空且默认停用，反馈标记为已沉淀。"""
    app = await QaApp.create(name="沉淀测试应用-单元测试专用", app_code="unittestcv0001", status="正常")
    session = await ChatSession.create(session_no="unittestcvsession", app_id=app.id)
    await ChatMessage.create(session_id=session.id, role="user", content="退款多久到账")
    answer = await ChatMessage.create(session_id=session.id, role="assistant", content="不清楚。")
    admin = await User.get_or_none(username="admin")
    feedback = await MessageFeedback.create(
        message_id=answer.id, user_id=admin.id, feedback_type="点踩", reason="没有回答"
    )

    created = await eval_dataset_service.convert_from_feedback(dataset.id)
    assert created >= 1

    case = await EvalCase.filter(dataset_id=dataset.id, source="反馈沉淀").first()
    assert case.question == "退款多久到账"
    # 标准答案留空由人工补，补完才启用
    assert case.ground_truth == ""
    assert case.enabled == "否"
    assert "来自点踩反馈" in case.remark

    # 反馈被标记为已沉淀，下次不会重复沉淀
    refreshed = await MessageFeedback.get_or_none(id=feedback.id)
    assert refreshed.converted == "是"

    await MessageFeedback.filter(id=feedback.id).delete()
    await ChatMessage.filter(session_id=session.id).delete()
    await ChatSession.filter(id=session.id).delete()
    await QaApp.filter(id=app.id).delete()


async def test_convert_without_pending_is_rejected(dataset):
    """没有待沉淀的点踩时给出人话提示。"""
    await MessageFeedback.filter(feedback_type="点踩", converted="否").update(converted="是")
    with pytest.raises(Exception) as excinfo:
        await eval_dataset_service.convert_from_feedback(dataset.id)
    assert "没有待沉淀的点踩记录" in str(excinfo.value)


async def test_generated_cases_reference_only_their_own_chunk(dataset, monkeypatch):
    """每条用例只记自己那一段的片段 ID，不是整篇文档的全部片段。

    Context Recall 是"命中的参照片段 / 全部参照片段"。
    如果把整篇文档的片段都记成参照，答案明明只在一段里，
    却要求把整篇都召回才算满分，分母被撑大，这个指标就永远上不去——
    top_k=5、文档有 9 段时，理论最高分只有 5/9。
    """
    kb = await KnowledgeBase.create(name="测试来源库-单元测试专用", status="正常")
    doc = await KnowledgeDocument.create(kb_id=kb.id, name="多片段文档.txt")
    chunks = []
    for index, text in enumerate(["整机质保 24 个月。", "电源适配器保修 12 个月。", "有偿维修保修 3 个月。"]):
        chunks.append(
            await KnowledgeChunk.create(
                kb_id=kb.id, document_id=doc.id, chunk_index=index,
                chunk_type="普通块", content=text, char_count=len(text),
            )
        )

    class FakeReply:
        # 三条问答对分别来自第 1、2、3 段
        content = (
            '[{"question": "整机质保多久", "ground_truth": "24 个月", "source_index": 1},'
            ' {"question": "适配器保修多久", "ground_truth": "12 个月", "source_index": 2},'
            ' {"question": "有偿维修保修多久", "ground_truth": "3 个月", "source_index": 3}]'
        )

    class FakeModel:
        async def ainvoke(self, prompt):
            return FakeReply()

    async def fake_load_enabled(model_type):
        return object()

    monkeypatch.setattr(model_factory, "load_enabled", fake_load_enabled)
    monkeypatch.setattr(model_factory, "build_chat_model", lambda config, temperature=0.0: FakeModel())

    await eval_dataset_service.generate_from_document(dataset.id, doc.id, 3)
    cases = await EvalCase.filter(dataset_id=dataset.id).order_by("id")

    references = [case.reference_chunk_ids for case in cases]
    # 三条用例各指向各自的片段，不能都是同一串
    assert references == [str(chunks[0].id), str(chunks[1].id), str(chunks[2].id)]
    # 每条只记一个片段，不是整篇三段
    assert all("," not in item for item in references)


async def test_generated_case_without_source_index_leaves_reference_empty(dataset, monkeypatch):
    """模型没标来源时参照留空，让 Context Recall 退回按语义判断。

    留空比记一串错的片段好：错的参照会算出一个看着正常、其实没意义的分数。
    """
    kb = await KnowledgeBase.create(name="测试无来源库-单元测试专用", status="正常")
    doc = await KnowledgeDocument.create(kb_id=kb.id, name="无来源标注.txt")
    await KnowledgeChunk.create(
        kb_id=kb.id, document_id=doc.id, chunk_index=0,
        chunk_type="普通块", content="整机质保 24 个月。", char_count=12,
    )

    class FakeReply:
        # 模型不听话，没给 source_index
        content = '[{"question": "整机质保多久", "ground_truth": "24 个月"}]'

    class FakeModel:
        async def ainvoke(self, prompt):
            return FakeReply()

    async def fake_load_enabled(model_type):
        return object()

    monkeypatch.setattr(model_factory, "load_enabled", fake_load_enabled)
    monkeypatch.setattr(model_factory, "build_chat_model", lambda config, temperature=0.0: FakeModel())

    await eval_dataset_service.generate_from_document(dataset.id, doc.id, 1)
    case = await EvalCase.filter(dataset_id=dataset.id).first()
    assert case.reference_chunk_ids is None
