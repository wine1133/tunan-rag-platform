"""检索业务逻辑。

按检索策略执行一次召回，返回带分数和来源的片段列表。
本章实现向量检索、BM25 检索和 RRF 融合三条路，
后面几章在这个函数上继续接重排、查询改写和父块回填。
"""

import asyncio
from typing import List

from ai import model_factory, query_rewriter, reranker, retriever, vector_store
from ai.query_rewriter import MULTI_QUERY
from common.exception_handler import CustomException
from common.times import cost_millis, now
from models import (
    AiModelConfig,
    ChunkStrategy,
    KnowledgeBase,
    KnowledgeChunk,
    RetrievalStrategy,
)

# BM25 要把候选片段全部读进内存建索引，限制一下一次最多读多少条，
# 避免知识库特别大时把内存吃满
BM25_CANDIDATE_LIMIT = 5000
# 只有会被检索到的片段参与召回，父块留给命中之后回填
SEARCHABLE_TYPES = ["普通块", "子块"]

# 检索管线里 score 这一个字段会被不同阶段反复覆盖，每覆盖一次量纲就换一次：
#
#     向量检索    余弦相似度    0 到 1，实测相关片段 0.46~0.77，无关 0.14~0.23
#     BM25 检索   BM25 分数     没有上界，不同问题之间不可比
#     RRF 融合    RRF 名次分    1/(rrf_k+名次)，rrf_k=60 时只有 0.016~0.033
#     重排        重排相关分    0 到 1，实测相关片段 0.14~0.20，无关 0.006
#
# 光看 score 这个数字分不出它现在是哪一种，所以量纲要作为显式信息跟着结果一路传下去，
# 阈值过滤那一步才知道自己在和什么比。
# 检索管线里 score 这一个字段会被不同阶段反复覆盖，每覆盖一次量纲就换一次。
SCALE_COSINE = "余弦相似度"
SCALE_BM25 = "BM25分数"
SCALE_RRF = "RRF名次分"
SCALE_RERANK = "重排相关分"

# 哪种量纲用哪个阈值字段。
# 只有余弦相似度和重排相关分的数值有绝对含义，能和一个固定门槛比大小；
# 两者的取值范围又差一个数量级，所以策略表里给它们各配一个阈值。
# BM25 分数没有上界、RRF 名次分只表示名次先后，都不在这张表里，遇到就不做阈值过滤。
THRESHOLD_FIELD_BY_SCALE = {
    SCALE_COSINE: "vector_score_threshold",
    SCALE_RERANK: "rerank_score_threshold",
}


def predict_score_scale(strategy: dict) -> str:
    """按策略配置推算这套策略跑完之后，分数会是哪种量纲。

    这是"事前预测"，和 retrieve 里那个跟着结果走的 score_scale 不是一回事：
    retrieve 记的是这一次实际发生了什么（BM25 一条都没召回时就只剩一份榜单，
    实际不会走 RRF 融合），本函数只看开关组合，回答"这套配置通常会走到哪一档"。

    策略管理页要在保存之前就告诉管理员该填哪个阈值，只能按配置预测；
    但推算规则必须和 retrieve 的管线保持一致，所以只在这里写一份，
    页面通过接口来取，不在前端另写一遍。
    """
    # 开了重排，最后一步就是重排打分
    if strategy.get("rerank_enabled") == "是":
        return SCALE_RERANK
    # 启用了几路召回，两路都开时会产生两份榜单
    routes = sum(
        1 for field in ("vector_enabled", "bm25_enabled") if strategy.get(field) == "是"
    )
    # 多查询扩展把一个问题拆成多条，每条查询在每一路上各召回一份榜单；
    # 指代消解和 HyDE 只产出一条查询，不影响榜单份数
    queries = 1
    if strategy.get("query_rewrite_enabled") == "是" and strategy.get("rewrite_type") == MULTI_QUERY:
        queries = strategy.get("multi_query_count") or 1
    # 榜单不止一份就要走 RRF 融合，融合后分数变成 1/(k+名次)
    if routes * queries > 1:
        return SCALE_RRF
    # 单路单查询时分数就是这一路自己打的分
    return SCALE_COSINE if strategy.get("vector_enabled") == "是" else SCALE_BM25


def strategy_dict(strategy: RetrievalStrategy) -> dict:
    fields = {
        "id": strategy.id,
        "name": strategy.name,
        "vector_enabled": strategy.vector_enabled,
        "vector_top_k": strategy.vector_top_k,
        "bm25_enabled": strategy.bm25_enabled,
        "bm25_top_k": strategy.bm25_top_k,
        "rrf_k": strategy.rrf_k,
        "rerank_enabled": strategy.rerank_enabled,
        "rerank_model_id": strategy.rerank_model_id,
        "rerank_top_n": strategy.rerank_top_n,
        "query_rewrite_enabled": strategy.query_rewrite_enabled,
        "rewrite_type": strategy.rewrite_type,
        "multi_query_count": strategy.multi_query_count,
        "parent_recall_enabled": strategy.parent_recall_enabled,
        "vector_score_threshold": float(strategy.vector_score_threshold) if strategy.vector_score_threshold is not None else None,
        "rerank_score_threshold": float(strategy.rerank_score_threshold) if strategy.rerank_score_threshold is not None else None,
        "metadata_filter": strategy.metadata_filter,
        "is_default": strategy.is_default,
        "remark": strategy.remark,
        "create_time": strategy.create_time,
        "update_time": strategy.update_time,
    }
    # 列表页据此标出这套策略实际生效的是哪个阈值，判断规则不在前端重写一遍
    fields["score_scale"] = predict_score_scale(fields)
    return fields


async def load_strategy(strategy_id: int | None) -> dict:
    """取检索策略，不指定时用默认策略。"""
    if strategy_id:
        strategy = await RetrievalStrategy.get_or_none(id=strategy_id)
        if strategy is None:
            raise CustomException("未找到检索策略")
        return strategy_dict(strategy)
    strategy = await RetrievalStrategy.get_or_none(is_default="是")
    if strategy is None:
        raise CustomException("没有设置默认检索策略，请先在检索策略里设置一条")
    return strategy_dict(strategy)


async def _load_candidates(kb_ids: List[int], document_ids: List[int] | None) -> List[dict]:
    """从 MySQL 读出参与 BM25 的候选片段。

    BM25 在内存里算，不依赖向量库，所以候选片段直接从 knowledge_chunk 表取。
    """
    query = KnowledgeChunk.filter(kb_id__in=kb_ids, chunk_type__in=SEARCHABLE_TYPES)
    if document_ids:
        query = query.filter(document_id__in=document_ids)
    chunks = await query.limit(BM25_CANDIDATE_LIMIT)
    return [
        {
            "chunk_id": chunk.id,
            "kb_id": chunk.kb_id,
            "document_id": chunk.document_id,
            "parent_chunk_id": chunk.parent_id,
            "chunk_type": chunk.chunk_type,
            "title_path": chunk.title_path,
            "content": chunk.content,
        }
        for chunk in chunks
    ]


async def _vector_recall(kb_ids: List[int], query: str, strategy: dict, document_ids: List[int] | None) -> List[dict]:
    """向量检索：把问题编码成向量，去 PGVector 里找最近的几条。"""
    config = await model_factory.load_enabled(model_factory.EMBEDDING)
    embeddings = model_factory.build_embeddings(config)
    vector = await embeddings.aembed_query(query)
    return await vector_store.search(
        kb_ids=kb_ids,
        embedding=vector,
        top_k=strategy["vector_top_k"],
        document_ids=document_ids,
        chunk_types=SEARCHABLE_TYPES,
    )


async def _bm25_recall(kb_ids: List[int], query: str, strategy: dict, document_ids: List[int] | None) -> List[dict]:
    """BM25 检索：在候选片段里做关键词匹配。"""
    candidates = await _load_candidates(kb_ids, document_ids)
    # 分词和打分是纯 CPU 操作，丢到线程里执行，不阻塞事件循环
    return await asyncio.to_thread(
        retriever.bm25_search, query, candidates, strategy["bm25_top_k"]
    )


async def retrieve(
    kb_ids: List[int],
    query: str,
    strategy: dict,
    document_ids: List[int] | None = None,
    history: List[dict] | None = None,
) -> dict:
    """按策略执行一次检索，返回结果和各阶段耗时。

    返回的 stages 记录每一路召回了多少条、花了多久，
    第 19 章的调试台直接把它展示出来做策略对比。
    """
    if not query or not query.strip():
        raise CustomException("请输入检索问题")
    if not kb_ids:
        raise CustomException("请选择知识库")
    started = now()
    stages: List[dict] = []
    rankings: List[List[dict]] = []
    # 和 rankings 一一对应，记录每一路召回出来的分数是什么量纲
    ranking_scales: List[str] = []

    # 检索之前先改写问题。改写产出一组查询，后面每一路都对每条查询各跑一次
    queries = [query]
    if strategy["query_rewrite_enabled"] == "是":
        stage_started = now()
        queries = await query_rewriter.rewrite(
            query,
            strategy.get("rewrite_type"),
            strategy["multi_query_count"],
            history,
        )
        stages.append(
            {
                "name": f"查询改写（{strategy.get('rewrite_type') or '未配置'}）",
                "count": len(queries),
                "cost_millis": cost_millis(stage_started),
                "detail": queries,
            }
        )

    if strategy["vector_enabled"] == "是":
        stage_started = now()
        total = 0
        for one in queries:
            vector_results = await _vector_recall(kb_ids, one, strategy, document_ids)
            # 每条查询的召回各自作为一份榜单参与融合
            rankings.append(vector_results)
            # 向量库返回的 score 由余弦距离换算而来
            ranking_scales.append(SCALE_COSINE)
            total += len(vector_results)
        stages.append(
            {
                "name": "向量检索",
                "count": total,
                "cost_millis": cost_millis(stage_started),
            }
        )

    if strategy["bm25_enabled"] == "是":
        stage_started = now()
        total = 0
        for one in queries:
            bm25_results = await _bm25_recall(kb_ids, one, strategy, document_ids)
            rankings.append(bm25_results)
            # BM25 打出来的分没有上界，只能用来排序
            ranking_scales.append(SCALE_BM25)
            total += len(bm25_results)
        stages.append(
            {
                "name": "BM25检索",
                "count": total,
                "cost_millis": cost_millis(stage_started),
            }
        )

    if not rankings:
        raise CustomException("该策略没有启用任何一路检索，请至少启用向量检索或 BM25 检索")

    # 过滤掉空榜单，某条改写查询一条都没召回时不该占一个融合位置。
    # 量纲和榜单是一一对应的，要一起筛，不能只筛一边
    survivors = [(scale, ranking) for scale, ranking in zip(ranking_scales, rankings) if ranking]
    # 当前 results 里的 score 是什么量纲，随着管线往下走不断被改写
    score_scale = None
    if not survivors:
        results = []
    elif len(survivors) == 1:
        # 只有一路时不需要融合，直接用这一路的结果，分数还是这一路自己的量纲
        score_scale, results = survivors[0]
    else:
        stage_started = now()
        # RRF 只看名次不看分数，融合后每条的 score 变成 1/(k+名次) 这种量级，
        # 大约 0.016 到 0.03，和向量检索的余弦相似度不是一个量纲
        # RRF 只看名次不看分数，融合后每条的 score 变成 1/(k+名次) 这种量级
        score_scale = SCALE_RRF
        rankings = [ranking for _, ranking in survivors]
        results = retriever.rrf_fuse(
            rankings,
            k=strategy["rrf_k"],
            top_k=max(strategy["vector_top_k"], strategy["bm25_top_k"]),
        )
        stages.append(
            {
                "name": "RRF融合",
                "count": len(results),
                "cost_millis": cost_millis(stage_started),
            }
        )

    if strategy["rerank_enabled"] == "是" and results:
        stage_started = now()
        before = len(results)
        results = await _rerank(query, results, strategy)
        # 重排模型重新给了一份分数，覆盖掉粗筛阶段的分，量纲随之变成重排相关分。
        # 它同样是 0 到 1，但和余弦相似度不是一回事：实测强相关只有 0.14~0.20，
        # 拿余弦那套 0.3 的门槛来卡会把结果全部砍掉，所以两者的阈值分开配
        score_scale = SCALE_RERANK
        stages.append(
            {
                "name": "重排",
                # 重排是做减法：粗筛进来多少条、精排后留下多少条
                "count": f"{before} → {len(results)}",
                "cost_millis": cost_millis(stage_started),
            }
        )

    if strategy["parent_recall_enabled"] == "是" and results:
        stage_started = now()
        before = len(results)
        results = await _backfill_parents(results)
        stages.append(
            {
                "name": "父块回填",
                # 命中的子块被换成父块，几个子块属于同一个父块时会合并成一条
                "count": f"{before} → {len(results)}",
                "cost_millis": cost_millis(stage_started),
            }
        )

    # 分数低于阈值的结果丢掉，让"知识库里没有"这个判断有依据
    results, threshold_stage = apply_score_threshold(results, score_scale, strategy)
    if threshold_stage:
        stages.append(threshold_stage)

    return {
        "query": query,
        # 实际用于检索的查询，开了改写时和原问题不同
        "queries": queries,
        "strategy_id": strategy["id"],
        "strategy_name": strategy["name"],
        "results": results,
        # 结果里 score 是什么量纲，页面据此给分数列标名字，不再笼统叫"相似度"
        "score_scale": score_scale,
        "stages": stages,
        "cost_millis": cost_millis(started),
    }


def apply_score_threshold(
    results: List[dict], score_scale: str | None, strategy: dict
) -> tuple[List[dict], dict | None]:
    """按当前分数量纲做阈值过滤，返回过滤后的结果和要记进阶段表的那一行。

    门槛取哪个字段由量纲决定：管线末端是余弦相似度就用向量阈值，
    是重排相关分就用重排阈值；是 BM25 分数或 RRF 名次分时不过滤，
    因为这两种分数的绝对数值不代表相关程度，和固定门槛比大小没有意义。

    第二个返回值是阶段记录，没有可记的就是 None。过滤和跳过都会留痕：
    页面上那个阈值框是不是真的生效了，必须能从阶段表里看出来。
    """
    if not results:
        return results, None

    threshold_field = THRESHOLD_FIELD_BY_SCALE.get(score_scale)

    if threshold_field is None:
        # 这一次的量纲不支持阈值。策略里一个阈值都没配就没什么好说的，
        # 配了才要说明白它这次为什么没生效
        configured = any(
            strategy.get(field) is not None for field in THRESHOLD_FIELD_BY_SCALE.values()
        )
        if not configured:
            return results, None
        return results, {
            "name": "阈值过滤（本次不适用）",
            "count": f"{len(results)} → {len(results)}",
            "cost_millis": 0,
            "detail": [
                f"当前分数量纲：{score_scale}",
                "这个量纲的数值只表示排序先后，没有绝对含义，不能和固定门槛比大小",
                "要让阈值生效，可以在策略里打开重排，让最终分数变成重排相关分",
            ],
        }

    threshold = strategy.get(threshold_field)
    if threshold is None:
        # 量纲支持阈值，但这一档没填，按不过滤处理
        return results, None

    # 没有分数的结果不参与比较，避免因为缺字段被误删
    kept = [item for item in results if item.get("score") is None or item["score"] >= threshold]
    scores = [item["score"] for item in results if item.get("score") is not None]
    detail = [f"当前分数量纲：{score_scale}，门槛 {threshold}"]
    if scores:
        detail.append(f"本次分数区间 {min(scores):.4f} ~ {max(scores):.4f}")
    if scores and not kept:
        # 结果被砍光时把话说明白。少了这一句，页面上只能看到 0 条，
        # 会让人以为是知识库没切分或没向量化，去查一个根本没问题的地方
        detail.append(
            f"最高分 {max(scores):.4f} 仍低于门槛 {threshold}，本次结果被阈值全部过滤，"
            f"确认知识库有答案的话就把这套策略的{score_scale}阈值调低"
        )
    stage = {
        "name": f"阈值过滤（{score_scale} >= {threshold}）",
        "count": f"{len(results)} → {len(kept)}",
        "cost_millis": 0,
        "detail": detail,
    }
    return kept, stage


async def _rerank(query: str, results: List[dict], strategy: dict) -> List[dict]:
    """把粗筛结果交给重排模型精排。

    策略里指定了重排模型就用指定的，没指定就用当前启用的那条。
    """
    config = None
    if strategy.get("rerank_model_id"):
        config = await AiModelConfig.get_or_none(id=strategy["rerank_model_id"])
    if config is None:
        config = await model_factory.load_enabled(model_factory.RERANK)
    compressor = reranker.DashScopeRerank(config=config, top_n=strategy["rerank_top_n"])
    documents = reranker.to_documents(results)
    ranked = await compressor.acompress_documents(documents, query)
    return reranker.from_documents(ranked)


async def retrieve_by_strategy(
    kb_ids: List[int],
    query: str,
    strategy_id: int | None = None,
    document_ids: List[int] | None = None,
    history: List[dict] | None = None,
) -> dict:
    """页面上的检索测试入口：按策略 ID 取配置再检索。"""
    strategy = await load_strategy(strategy_id)
    # 检索结果里带上文档名称，页面上展示"这段来自哪篇文档"
    outcome = await retrieve(kb_ids, query, strategy, document_ids, history)
    await _fill_document_name(outcome["results"])
    return outcome


async def _backfill_parents(results: List[dict]) -> List[dict]:
    """把命中的子块换成它的父块。

    子块小，检索时语义集中，命中更准；父块大，上下文完整，模型才答得全。
    第 09 章切分时建好的 parent_id 就是为这一步准备的。

    几个子块同属一个父块时合并成一条，避免同一段内容重复发给模型。
    普通块没有父块，原样保留。
    """
    parent_ids = {
        item["parent_chunk_id"]
        for item in results
        if item.get("chunk_type") == "子块" and item.get("parent_chunk_id")
    }
    if not parent_ids:
        return results
    parents = await KnowledgeChunk.filter(id__in=list(parent_ids))
    parent_map = {parent.id: parent for parent in parents}

    merged: List[dict] = []
    # 已经放进结果的父块，用来做去重
    used_parents: set[int] = set()
    for item in results:
        parent_id = item.get("parent_chunk_id")
        if item.get("chunk_type") != "子块" or not parent_id:
            merged.append(item)
            continue
        parent = parent_map.get(parent_id)
        if parent is None:
            # 父块被删或数据不一致时退回用子块，不让这条结果凭空消失
            merged.append(item)
            continue
        if parent_id in used_parents:
            continue
        used_parents.add(parent_id)
        expanded = dict(item)
        expanded.update(
            {
                "chunk_id": parent.id,
                "chunk_type": "父块",
                "content": parent.content,
                "page_no": parent.page_no,
                # 排序位次和分数沿用命中的那个子块，父块自己没有参与打分
                "source": f"{item.get('source', '')}→父块回填",
                # 记下是哪个子块命中的，页面上能追溯到实际匹配的那一小段
                "matched_chunk_id": item["chunk_id"],
            }
        )
        merged.append(expanded)
    return merged


async def _fill_document_name(results: List[dict]) -> None:
    """给检索结果补上文档名称。

    向量表里冗余了内容但没冗余文档名，因为文档可以改名，
    冗余了会不一致，所以展示时按 document_id 回查一次。
    """
    if not results:
        return
    from models import KnowledgeDocument

    document_ids = {item["document_id"] for item in results if item.get("document_id")}
    if not document_ids:
        return
    documents = await KnowledgeDocument.filter(id__in=list(document_ids))
    names = {doc.id: doc.name for doc in documents}
    for item in results:
        item["document_name"] = names.get(item.get("document_id"))


async def kb_options_with_chunks() -> List[dict]:
    """页面上检索测试的知识库下拉数据，带上片段数便于判断能不能检索。"""
    bases = await KnowledgeBase.filter(status="正常").order_by("-id")
    return [
        {"id": kb.id, "name": kb.name, "chunk_count": kb.chunk_count}
        for kb in bases
    ]


async def chunk_strategy_of(kb_id: int) -> dict | None:
    """查知识库绑定的切分策略，页面上提示这个库是不是父子分块。"""
    kb = await KnowledgeBase.get_or_none(id=kb_id)
    if kb is None or not kb.chunk_strategy_id:
        return None
    strategy = await ChunkStrategy.get_or_none(id=kb.chunk_strategy_id)
    if strategy is None:
        return None
    return {"id": strategy.id, "name": strategy.name, "strategy_type": strategy.strategy_type}
