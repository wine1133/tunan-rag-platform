"""检索。

第 13 章讲的第一个失效点：向量检索认不出 GTE-3000 这类专有名词，
关键词检索认得出型号却听不懂"保修"和"质保"是一回事。
本模块把两路一起跑，再用 RRF 把两份排名融合成一份。

    向量检索   语义匹配，认不出精确字符
    BM25 检索  字符匹配，听不懂同义表达
    RRF 融合   只看名次不看分数，把两份榜单合成一份
"""

import re

import jieba

from rank_bm25 import BM25Okapi

# 字母和数字连写的片段，例如 gte3000、v2、err5021
ALNUM_MIXED = re.compile(r"^(?=.*[a-z])(?=.*\d)[a-z\d]+$")
# 把连写片段拆成字母段和数字段
ALNUM_PARTS = re.compile(r"[a-z]+|\d+")

# 分词后要丢掉的词。这些词几乎每段都有，留着会让 BM25 的区分度下降
STOP_WORDS = {
    "的", "了", "和", "是", "在", "有", "为", "与", "及", "或", "对", "从",
    "把", "被", "个", "我", "你", "他", "它", "这", "那", "吗", "呢", "吧",
    "什么", "怎么", "如何", "多少", "哪些", "可以", "需要", "请问",
    " ", "\n", "\t", "，", "。", "、", "？", "！", "；", "：", "（", "）",
    ",", ".", "?", "!", ";", ":", "(", ")", "-", "_",
}


def tokenize(text: str) -> list[str]:
    """中文分词。

    BM25 的输入是词列表，中文不像英文有空格天然分词，要先切开。

    这里在 jieba 的基础上多做一步：把字母数字连写的词额外拆一份出来。
    文档里写的是 GTE-3000，jieba 切成 gte、-、3000；
    用户输入的是 GTE3000，jieba 切成一个词 gte3000。
    不拆的话两边一个词都对不上，型号反而检索不到——这正是本章要解决的问题。
    拆完之后两边都含有 gte 和 3000，能匹配上。
    """
    tokens = []
    for word in jieba.lcut(text.lower()):
        word = word.strip()
        if not word or word in STOP_WORDS:
            continue
        tokens.append(word)
        # 字母数字连写的词，再补一份拆开的形式，原词也保留
        if ALNUM_MIXED.match(word):
            tokens.extend(ALNUM_PARTS.findall(word))
    return tokens


def bm25_search(query: str, candidates: list[dict], top_k: int) -> list[dict]:
    """在给定的候选片段里做 BM25 关键词检索。

    candidates 的每一项至少要有 chunk_id 和 content 两个键，
    由调用方从 MySQL 的 knowledge_chunk 表查出来。

    BM25 是一次性在内存里建索引再打分。知识库片段量很大时这一步会变慢，
    所以调用方会先按知识库和文档把候选范围缩小。
    """
    if not candidates:
        return []
    corpus = [tokenize(item["content"]) for item in candidates]
    # 全部片段分完词都是空的时候没法建索引，直接返回空结果
    if not any(corpus):
        return []
    bm25 = BM25Okapi(corpus)
    query_tokens = tokenize(query)
    if not query_tokens:
        return []
    scores = bm25.get_scores(query_tokens)
    ranked = sorted(zip(candidates, scores), key=lambda pair: pair[1], reverse=True)
    results = []
    for item, score in ranked[:top_k]:
        # BM25 的分数没有上界，不同问题之间不可比，
        # 所以只作为排序依据，融合时也只用名次不用分数
        if score <= 0:
            continue
        merged = dict(item)
        merged["score"] = round(float(score), 6)
        merged["source"] = "BM25检索"
        results.append(merged)
    return results


def rrf_fuse(rankings: list[list[dict]], k: int = 60, top_k: int = 10) -> list[dict]:
    """用 RRF 把多路召回的排名融合成一份。

    RRF 的公式是：一条结果的总分 = 各路里 1 / (k + 名次) 的和。

    它只看名次不看原始分数，这一点是关键：
    向量检索的分数是 0 到 1 的相似度，BM25 的分数没有上界，
    两者量纲完全不同，直接加权求和是在加两个不可比的数。
    换成名次之后，两路都变成"第 1 名、第 2 名"，可以放在一起算。

    k 是平滑常数，控制名次之间的差距有多大：
    k 越大，各个名次的贡献越接近，被多路同时召回的结果越占优；
    k 越小，头部名次的贡献被放大，单路排第 1 的结果更容易冒头。
    60 是这个算法论文里给出的经验值，本项目默认也用它。
    """
    scores: dict[int, float] = {}
    payloads: dict[int, dict] = {}
    sources: dict[int, set] = {}
    for ranking in rankings:
        for index, item in enumerate(ranking):
            chunk_id = item["chunk_id"]
            # 名次从 1 开始算，所以是 index + 1
            scores[chunk_id] = scores.get(chunk_id, 0.0) + 1.0 / (k + index + 1)
            sources.setdefault(chunk_id, set()).add(item.get("source", ""))
            # 同一条片段可能被两路都召回，内容一样，留先到的那份即可
            payloads.setdefault(chunk_id, item)
    fused = []
    for chunk_id, score in sorted(scores.items(), key=lambda pair: pair[1], reverse=True)[:top_k]:
        item = dict(payloads[chunk_id])
        item["score"] = round(score, 6)
        # 标出这条是被哪几路召回的，两路都召回的结果可信度更高
        item["source"] = "+".join(sorted(source for source in sources[chunk_id] if source))
        fused.append(item)
    return fused
