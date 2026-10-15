"""查询改写。

第 13 章讲的第三个失效点：用户的口语问法和文档的书面写法对不上，
多轮对话里的"那它呢"根本没有信息量，拿去检索等于随机。

本模块在检索之前先改写问题，三种方式：

    多查询扩展  把一个问题改写成几个说法不同、意思相同的问题，每个都检索一遍
    指代消解    把多轮对话的当前问题补全成一个独立完整的问题
    HyDE        先让模型编一段假答案，拿假答案去检索

三种方式都要调对话模型，都会给整条链路多加一次模型调用的耗时。
"""

from ai import model_factory, prompt_loader

MULTI_QUERY = "多查询扩展"
COREFERENCE = "指代消解"
HYDE = "HyDE"

# 一次最多扩展出多少条查询。条数越多召回越全，但检索次数和耗时也成倍增加
MAX_QUERY_COUNT = 5


def _split_lines(text: str) -> list[str]:
    """把模型返回的多行文本拆成列表，并去掉行首的编号和符号。

    模型有时会不听话地加上 "1. " "- " 这类前缀，统一清掉。
    """
    lines = []
    for raw in str(text).splitlines():
        line = raw.strip()
        if not line:
            continue
        # 去掉常见的编号和项目符号前缀
        line = line.lstrip("0123456789.、)-— ").strip()
        if line:
            lines.append(line)
    return lines


async def multi_query(question: str, count: int) -> list[str]:
    """多查询扩展：一个问题改写成 count 个说法不同、意思相同的问题。

    返回的列表里第一条是原问题。原问题必须保留——
    改写是为了增加命中机会，不是替换用户的表达，
    万一模型改写跑偏了，原问题这一路还在。
    """
    count = max(1, min(count, MAX_QUERY_COUNT))
    config = await model_factory.load_enabled(model_factory.CHAT)
    model = model_factory.build_chat_model(config)
    prompt = await prompt_loader.render("QUERY_REWRITE", count=count, question=question)
    reply = await model.ainvoke(prompt)
    queries = [question]
    for line in _split_lines(reply.content):
        # 模型可能把原问题也重复一遍，去重
        if line not in queries:
            queries.append(line)
    return queries[: count + 1]


async def resolve_coreference(question: str, history: list[dict]) -> str:
    """指代消解：把当前这句话补全成不依赖上下文的完整问题。

    history 是最近几轮对话，每项形如 {"role": "user"/"assistant", "content": "..."}。
    没有历史时原样返回，不做无谓的模型调用。
    """
    if not history:
        return question
    lines = []
    for item in history:
        speaker = "用户" if item.get("role") == "user" else "助手"
        lines.append(f"{speaker}：{item.get('content', '')}")
    config = await model_factory.load_enabled(model_factory.CHAT)
    model = model_factory.build_chat_model(config)
    prompt = await prompt_loader.render(
        "COREFERENCE_RESOLVE", history="\n".join(lines), question=question
    )
    reply = await model.ainvoke(prompt)
    rewritten = str(reply.content).strip()
    # 模型返回空内容时退回原问题，不能让检索拿着空字符串去跑
    return rewritten or question


async def hyde(question: str) -> str:
    """HyDE：先让模型写一段假答案，用假答案去检索。

    假答案的内容不一定对，但它的用词和句式和真正的文档很接近。
    问题和答案在语义空间里未必靠得近，但答案和答案一定靠得近。
    """
    config = await model_factory.load_enabled(model_factory.CHAT)
    model = model_factory.build_chat_model(config)
    prompt = await prompt_loader.render("HYDE_ANSWER", question=question)
    reply = await model.ainvoke(prompt)
    answer = str(reply.content).strip()
    if not answer:
        return question
    # 把原问题拼在假答案前面，既保留原始意图又带上文档腔的表达
    return f"{question}\n{answer}"


async def rewrite(question: str, rewrite_type: str, count: int, history: list[dict] | None = None) -> list[str]:
    """按改写方式返回一组用于检索的查询。

    返回值统一是列表：多查询扩展返回多条，另外两种返回一条，
    调用方不用为三种方式写三套分支。
    """
    if rewrite_type == MULTI_QUERY:
        return await multi_query(question, count)
    if rewrite_type == COREFERENCE:
        return [await resolve_coreference(question, history or [])]
    if rewrite_type == HYDE:
        return [await hyde(question)]
    # 没配改写方式时按原问题检索
    return [question]
