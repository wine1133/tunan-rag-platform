"""RAG 效果评测。

第 26 章那四个指标的实现。四个指标全是语义判断，规则写不出来，
所以用大模型当裁判——这套方法叫 LLM-as-judge。

    Context Recall     标准答案的每句话，能不能在召回的资料里找到依据
    Context Precision  召回的资料里，有用的那些是不是排在前面
    Faithfulness       答案的每句话，能不能在资料里找到支撑
    Answer Relevancy   从答案反推问题，和原问题有多接近

裁判模型的 temperature 必须是 0，否则同一段资料这次判"相关"下次判"不相关"，
两次评测的差异就分不清是策略变了还是裁判抖了。第 11 章的模型工厂已经定死为 0。

省调用的两个做法：
    判断类的 Prompt 让模型一次判多条，不逐条调用
    用例带了 reference_chunk_ids 时，Context Recall 直接对比片段 ID，不调模型
"""

import math

from ai import model_factory, prompt_loader

# 一次最多判断多少条陈述，太多模型容易漏行导致对不上号
MAX_STATEMENTS = 12
# 拼进裁判 Prompt 的资料最多多少字
MAX_JUDGE_CHARS = 5000


async def _chat(prompt: str) -> str:
    config = await model_factory.load_enabled(model_factory.CHAT)
    model = model_factory.build_chat_model(config)
    reply = await model.ainvoke(prompt)
    return str(reply.content).strip()


def _clean_lines(text: str) -> list[str]:
    """把模型的多行输出清洗成列表，去掉编号和项目符号。"""
    lines = []
    for raw in str(text).splitlines():
        line = raw.strip().lstrip("0123456789.、)-— ").strip()
        if line:
            lines.append(line)
    return lines


def parse_verdicts(text: str, expected: int) -> list[bool]:
    """把模型逐行输出的是否结论解析成布尔列表。

    模型偶尔会少输出一行或多输出一行，这里按期望条数对齐：
    多了截断，少了按"否"补齐——判断不出来时按不通过算，分数偏保守不偏乐观。
    """
    verdicts = []
    for line in _clean_lines(text):
        # 先查否定词，"否"和"不"都算否；"是"才算通过
        if line.startswith("否") or line.startswith("不"):
            verdicts.append(False)
        elif line.startswith("是"):
            verdicts.append(True)
        else:
            # 模型没按格式回答时保守判为不通过
            verdicts.append(False)
    if len(verdicts) > expected:
        return verdicts[:expected]
    return verdicts + [False] * (expected - len(verdicts))


def build_context(contents: list[str]) -> str:
    """把片段拼成裁判能读的资料段，超长截断。"""
    parts = []
    used = 0
    for index, content in enumerate(contents, start=1):
        if used + len(content) > MAX_JUDGE_CHARS:
            break
        parts.append(f"[资料{index}] {content}")
        used += len(content)
    return "\n\n".join(parts)


async def split_statements(text: str) -> list[str]:
    """把一段文字拆成若干条独立陈述。

    拆完才能逐条判断，这是 Context Recall 和 Faithfulness 的共同前提。
    """
    if not text or not text.strip():
        return []
    prompt = await prompt_loader.render("EVAL_SPLIT_STATEMENTS", text=text.strip())
    statements = _clean_lines(await _chat(prompt))
    return statements[:MAX_STATEMENTS]


async def judge_support(context: str, statements: list[str]) -> list[bool]:
    """逐条判断陈述能否由资料推出。一次调用判完所有条，不逐条调。"""
    if not statements:
        return []
    numbered = "\n".join(f"{index}. {item}" for index, item in enumerate(statements, start=1))
    prompt = await prompt_loader.render(
        "EVAL_JUDGE_SUPPORT", context=context, statements=numbered
    )
    return parse_verdicts(await _chat(prompt), len(statements))


async def judge_relevance(question: str, contents: list[str]) -> list[bool]:
    """逐段判断资料对回答这个问题有没有用。"""
    if not contents:
        return []
    numbered = "\n\n".join(
        f"[资料{index}] {content[:800]}" for index, content in enumerate(contents, start=1)
    )
    prompt = await prompt_loader.render(
        "EVAL_JUDGE_RELEVANCE", question=question, contexts=numbered
    )
    return parse_verdicts(await _chat(prompt), len(contents))


async def reverse_question(answer: str) -> str:
    """从答案反推问题。"""
    if not answer or not answer.strip():
        return ""
    prompt = await prompt_loader.render("EVAL_REVERSE_QUESTION", answer=answer.strip())
    return await _chat(prompt)


def cosine(left: list[float], right: list[float]) -> float:
    """两个向量的余弦相似度。"""
    if not left or not right or len(left) != len(right):
        return 0.0
    dot = sum(a * b for a, b in zip(left, right))
    norm_left = math.sqrt(sum(a * a for a in left))
    norm_right = math.sqrt(sum(b * b for b in right))
    if norm_left == 0 or norm_right == 0:
        return 0.0
    return dot / (norm_left * norm_right)


def precision_at_k(relevances: list[bool]) -> float:
    """按名次加权算上下文精度。

    第 26 章说过：同样的召回内容，相关的排第 1 和排第 4，精度应该差很多。
    这里对每个相关位置算一次"截止到这个位置的精确率"，再取平均：

        召回 [相关, 不相关, 不相关, 不相关]
            位置1 相关，截止到这里的精确率 1/1 = 1.0
            精度 = 1.0 / 1 = 1.0

        召回 [不相关, 不相关, 不相关, 相关]
            位置4 相关，截止到这里的精确率 1/4 = 0.25
            精度 = 0.25 / 1 = 0.25
    """
    if not relevances:
        return 0.0
    hit = 0
    total = 0.0
    for index, relevant in enumerate(relevances, start=1):
        if relevant:
            hit += 1
            total += hit / index
    if hit == 0:
        return 0.0
    return total / hit


async def context_recall(ground_truth: str, contents: list[str], reference_chunk_ids: list[int] | None,
                         retrieved_chunk_ids: list[int]) -> float:
    """上下文召回：标准答案里的信息，检索有没有找回来。

    用例带了 reference_chunk_ids 时直接对比片段 ID，不调模型——
    更准也更省钱，第 27 章文档生成的用例都带着这个字段。
    """
    if reference_chunk_ids:
        expected = set(reference_chunk_ids)
        hit = expected & set(retrieved_chunk_ids)
        return len(hit) / len(expected)
    statements = await split_statements(ground_truth)
    if not statements:
        return 0.0
    verdicts = await judge_support(build_context(contents), statements)
    return sum(1 for item in verdicts if item) / len(verdicts)


async def faithfulness(answer: str, contents: list[str]) -> float:
    """忠实度：答案里的每句话是不是都有资料支撑。"""
    statements = await split_statements(answer)
    if not statements:
        return 0.0
    verdicts = await judge_support(build_context(contents), statements)
    return sum(1 for item in verdicts if item) / len(verdicts)


async def context_precision(question: str, contents: list[str]) -> float:
    """上下文精度：有用的资料是不是排在前面。"""
    relevances = await judge_relevance(question, contents)
    return precision_at_k(relevances)


async def answer_relevancy(question: str, answer: str) -> float:
    """答案相关性：从答案反推的问题和原问题有多接近。

    用向量相似度比对，比让模型打分稳定得多——
    模型给"相似度 0.8"这种数字时非常随意，向量算出来的是确定的。
    """
    reversed_question = await reverse_question(answer)
    if not reversed_question:
        return 0.0
    config = await model_factory.load_enabled(model_factory.EMBEDDING)
    embeddings = model_factory.build_embeddings(config)
    vectors = await embeddings.aembed_documents([question, reversed_question])
    score = cosine(vectors[0], vectors[1])
    # 余弦相似度可能是负数，负相关等同于完全不相关，截到 0
    return max(0.0, score)


async def evaluate_case(
    question: str,
    ground_truth: str,
    answer: str,
    contents: list[str],
    retrieved_chunk_ids: list[int],
    reference_chunk_ids: list[int] | None = None,
) -> dict:
    """算一条用例的四个指标。"""
    recall = await context_recall(ground_truth, contents, reference_chunk_ids, retrieved_chunk_ids)
    precision = await context_precision(question, contents)
    faithful = await faithfulness(answer, contents)
    relevancy = await answer_relevancy(question, answer)
    scores = [recall, precision, faithful, relevancy]
    return {
        "context_recall": round(recall, 4),
        "context_precision": round(precision, 4),
        "faithfulness": round(faithful, 4),
        "answer_relevancy": round(relevancy, 4),
        "avg_score": round(sum(scores) / len(scores), 4),
    }
