"""向量库读写。

向量存在 PostgreSQL 的 knowledge_chunk_vector 表里，业务数据仍然在 MySQL。
两个库通过 chunk_id 关联：这里的 chunk_id 就是 MySQL 里 knowledge_chunk.id。

不用 langchain_postgres 的 PGVector 封装，因为它会按自己的约定建表，
而本项目的向量表是第 10 章用 ai_rag_vector.sql 建的，多了 kb_id、chunk_type
这些用于元数据过滤的列。直接用 psycopg 写 SQL，表结构完全由我们自己掌控。
"""

import psycopg
from pgvector.psycopg import Vector, register_vector_async

from common.exception_handler import CustomException
from settings import PGVECTOR


def _dsn() -> str:
    """按 settings.py 里的配置拼出 PostgreSQL 连接串。"""
    return (
        f"host={PGVECTOR['host']} port={PGVECTOR['port']} dbname={PGVECTOR['database']} "
        f"user={PGVECTOR['user']} password={PGVECTOR['password']}"
    )


async def _connect() -> psycopg.AsyncConnection:
    """打开一个到向量库的连接，并注册 vector 类型。

    register_vector_async 让 psycopg 认识 vector 类型，
    不注册的话传 Python 列表进去会被当成数组类型，插入直接报错。
    """
    try:
        connection = await psycopg.AsyncConnection.connect(_dsn())
    except Exception as exc:
        raise CustomException(f"连不上向量库，请确认 PostgreSQL 已启动：{str(exc)[:200]}")
    await register_vector_async(connection)
    return connection


async def upsert(rows: list[dict]) -> int:
    """写入或覆盖一批片段的向量。

    表上 chunk_id 有唯一索引，重复向量化同一批片段时按 chunk_id 覆盖，
    不会插出两条，所以可以反复执行而不用先删。
    """
    if not rows:
        return 0
    sql = """
        insert into knowledge_chunk_vector
            (chunk_id, kb_id, document_id, parent_chunk_id, chunk_type, title_path, content, embedding)
        values
            (%(chunk_id)s, %(kb_id)s, %(document_id)s, %(parent_chunk_id)s,
             %(chunk_type)s, %(title_path)s, %(content)s, %(embedding)s)
        on conflict (chunk_id) do update set
            kb_id = excluded.kb_id,
            document_id = excluded.document_id,
            parent_chunk_id = excluded.parent_chunk_id,
            chunk_type = excluded.chunk_type,
            title_path = excluded.title_path,
            content = excluded.content,
            embedding = excluded.embedding,
            update_time = current_timestamp
    """
    connection = await _connect()
    async with connection:
        async with connection.cursor() as cursor:
            await cursor.executemany(sql, rows)
        await connection.commit()
    return len(rows)


async def delete_by_document(document_id: int) -> int:
    """删掉一篇文档的全部向量。文档被删或重新切分时调用。"""
    connection = await _connect()
    async with connection:
        async with connection.cursor() as cursor:
            await cursor.execute(
                "delete from knowledge_chunk_vector where document_id = %s", (document_id,)
            )
            deleted = cursor.rowcount
        await connection.commit()
    return deleted


async def delete_by_chunk_ids(chunk_ids: list[int]) -> int:
    """删掉指定片段的向量。片段被人工删除时调用。"""
    if not chunk_ids:
        return 0
    connection = await _connect()
    async with connection:
        async with connection.cursor() as cursor:
            await cursor.execute(
                "delete from knowledge_chunk_vector where chunk_id = any(%s)", (chunk_ids,)
            )
            deleted = cursor.rowcount
        await connection.commit()
    return deleted


async def delete_by_kb(kb_id: int) -> int:
    """删掉一个知识库的全部向量。换向量模型需要全量重建时调用。"""
    connection = await _connect()
    async with connection:
        async with connection.cursor() as cursor:
            await cursor.execute("delete from knowledge_chunk_vector where kb_id = %s", (kb_id,))
            deleted = cursor.rowcount
        await connection.commit()
    return deleted


async def count_by_kb(kb_id: int) -> int:
    """统计一个知识库已经写进向量库的片段数。"""
    connection = await _connect()
    async with connection:
        async with connection.cursor() as cursor:
            await cursor.execute(
                "select count(*) from knowledge_chunk_vector where kb_id = %s", (kb_id,)
            )
            row = await cursor.fetchone()
    return row[0] if row else 0


async def search(
    kb_ids: list[int],
    embedding: list[float],
    top_k: int = 5,
    document_ids: list[int] | None = None,
    chunk_types: list[str] | None = None,
) -> list[dict]:
    """按余弦距离检索最相似的片段。

    kb_ids、document_ids、chunk_types 是元数据过滤条件，
    它们和向量比对写在同一条 SQL 里，数据库先按条件缩小范围再算距离，
    不用先全表算距离再回 MySQL 筛一遍。

    返回的 score 是相似度，由距离换算而来，越大越相似，取值 0 到 1。
    """
    if not kb_ids:
        return []
    conditions = ["kb_id = any(%(kb_ids)s)"]
    # 查询向量必须包一层 Vector 再传。
    # upsert 里直接传 Python 列表没问题，是因为它写进的是 vector(1024) 列，
    # 数据库能从列类型推断出来；而这里的向量是 <=> 运算符的操作数，
    # 两边都没有类型上下文，裸列表会被当成 float8[]，直接报
    # operator does not exist: vector <=> double precision[]。
    params: dict = {"kb_ids": kb_ids, "embedding": Vector(embedding), "top_k": top_k}
    if document_ids:
        conditions.append("document_id = any(%(document_ids)s)")
        params["document_ids"] = document_ids
    if chunk_types:
        # 父子分块的库只检索子块，父块留给命中之后回填上下文
        conditions.append("chunk_type = any(%(chunk_types)s)")
        params["chunk_types"] = chunk_types
    where = " and ".join(conditions)
    sql = f"""
        select chunk_id, kb_id, document_id, parent_chunk_id, chunk_type, title_path, content,
               embedding <=> %(embedding)s as distance
        from knowledge_chunk_vector
        where {where}
        order by embedding <=> %(embedding)s
        limit %(top_k)s
    """
    connection = await _connect()
    async with connection:
        async with connection.cursor() as cursor:
            await cursor.execute(sql, params)
            rows = await cursor.fetchall()
    results = []
    for row in rows:
        distance = float(row[7])
        results.append(
            {
                "chunk_id": row[0],
                "kb_id": row[1],
                "document_id": row[2],
                "parent_chunk_id": row[3],
                "chunk_type": row[4],
                "title_path": row[5],
                "content": row[6],
                # 余弦距离范围是 0 到 2，1 减去距离得到相似度，
                # 页面上展示相似度比展示距离直观：数字越大越相关
                "score": round(1 - distance, 6),
                "source": "向量检索",
            }
        )
    return results


async def health_check() -> str:
    """连通性自检，供页面上的向量库状态显示使用。"""
    connection = await _connect()
    async with connection:
        async with connection.cursor() as cursor:
            await cursor.execute("select count(*) from knowledge_chunk_vector")
            row = await cursor.fetchone()
    return f"向量库连接正常，当前共 {row[0] if row else 0} 条向量"
