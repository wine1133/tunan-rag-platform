"""切分策略与知识片段接口测试。

覆盖策略校验、默认策略唯一性、递归分块、父子分块、片段编辑与删除、统计数同步。
"""

import os

import pytest

from service.file_service import UPLOAD_DIR

KB_NAME = "测试切分库-单元测试专用"
STRATEGY_NAME = "测试策略-单元测试专用"
# 三段用换行分开的文本，递归分块会在换行处断开
DOC_TEXT = "\n\n".join([f"第{index}段：这是一段用于验证切分效果的正文内容。" for index in range(1, 13)])


@pytest.fixture()
def kb_id(client, admin_headers):
    client.post("/knowledgeBase/add", json={"name": KB_NAME, "status": "正常"}, headers=admin_headers)
    page = client.get(
        "/knowledgeBase/selectPage",
        params={"name": KB_NAME, "page_num": 1, "page_size": 10},
        headers=admin_headers,
    ).json()
    created = [item for item in page["data"]["list"] if item["name"] == KB_NAME][0]

    yield created["id"]

    docs = client.get(
        "/knowledgeDocument/selectPage",
        params={"kb_id": created["id"], "page_num": 1, "page_size": 50},
        headers=admin_headers,
    ).json()
    doc_ids = [item["id"] for item in docs["data"]["list"]]
    if doc_ids:
        client.request("DELETE", "/knowledgeDocument/deleteBatch", json=doc_ids, headers=admin_headers)
    client.delete(f"/knowledgeBase/delete/{created['id']}", headers=admin_headers)


@pytest.fixture()
def parsed_doc(client, admin_headers, kb_id):
    """建一篇已经解析完成的 TXT 文档，供切分测试使用。"""
    file_name = "切分测试文本.txt"
    os.makedirs(UPLOAD_DIR, exist_ok=True)
    path = os.path.join(UPLOAD_DIR, file_name)
    with open(path, "w", encoding="utf-8") as handle:
        handle.write(DOC_TEXT)

    client.post(
        "/knowledgeDocument/add",
        json={
            "kb_id": kb_id,
            "name": file_name,
            "file_name": file_name,
            "file_url": f"http://127.0.0.1:9090/files/download/{file_name}",
            "file_size": len(DOC_TEXT),
        },
        headers=admin_headers,
    )
    page = client.get(
        "/knowledgeDocument/selectPage",
        params={"kb_id": kb_id, "page_num": 1, "page_size": 10},
        headers=admin_headers,
    ).json()
    doc_id = page["data"]["list"][0]["id"]
    client.post(f"/knowledgeDocument/parse/{doc_id}", headers=admin_headers)

    yield doc_id

    if os.path.exists(path):
        os.remove(path)


def _cleanup_strategy(client, admin_headers):
    page = client.get(
        "/chunkStrategy/selectPage",
        params={"name": STRATEGY_NAME, "page_num": 1, "page_size": 10},
        headers=admin_headers,
    ).json()
    for item in page["data"]["list"]:
        if item["name"] == STRATEGY_NAME:
            client.delete(f"/chunkStrategy/delete/{item['id']}", headers=admin_headers)


def test_overlap_must_be_smaller_than_chunk_size(client, admin_headers):
    """重叠字符数不能大于等于片段长度。"""
    body = client.post(
        "/chunkStrategy/add",
        json={"name": STRATEGY_NAME, "strategy_type": "递归分块", "chunk_size": 200, "chunk_overlap": 200},
        headers=admin_headers,
    ).json()
    assert body["code"] == "500"
    assert body["msg"] == "重叠字符数必须小于片段长度"


def test_parent_chunk_size_must_be_larger(client, admin_headers):
    """父子分块的父块长度必须大于子块长度。"""
    body = client.post(
        "/chunkStrategy/add",
        json={
            "name": STRATEGY_NAME,
            "strategy_type": "父子分块",
            "chunk_size": 300,
            "chunk_overlap": 30,
            "parent_chunk_size": 300,
        },
        headers=admin_headers,
    ).json()
    assert body["code"] == "500"
    assert body["msg"] == "父块长度必须大于片段长度"


def test_only_one_default_strategy(client, admin_headers):
    """新增一条默认策略后，原来的默认标记被清掉。"""
    _cleanup_strategy(client, admin_headers)
    before = client.get("/chunkStrategy/selectAll", headers=admin_headers).json()
    old_default = [item for item in before["data"] if item["is_default"] == "是"][0]

    client.post(
        "/chunkStrategy/add",
        json={
            "name": STRATEGY_NAME,
            "strategy_type": "递归分块",
            "chunk_size": 200,
            "chunk_overlap": 20,
            "is_default": "是",
        },
        headers=admin_headers,
    )
    after = client.get("/chunkStrategy/selectAll", headers=admin_headers).json()
    defaults = [item for item in after["data"] if item["is_default"] == "是"]
    assert len(defaults) == 1
    assert defaults[0]["name"] == STRATEGY_NAME

    # 复原：把原来那条重新设为默认，再删掉测试策略
    client.put(
        "/chunkStrategy/update",
        json={
            "id": old_default["id"],
            "name": old_default["name"],
            "strategy_type": old_default["strategy_type"],
            "chunk_size": old_default["chunk_size"],
            "chunk_overlap": old_default["chunk_overlap"],
            "separators": old_default["separators"],
            "is_default": "是",
        },
        headers=admin_headers,
    )
    _cleanup_strategy(client, admin_headers)


def test_default_strategy_cannot_be_deleted(client, admin_headers):
    """默认策略不允许删除。"""
    strategies = client.get("/chunkStrategy/selectAll", headers=admin_headers).json()
    default = [item for item in strategies["data"] if item["is_default"] == "是"][0]

    body = client.delete(f"/chunkStrategy/delete/{default['id']}", headers=admin_headers).json()
    assert body["code"] == "500"
    assert body["msg"] == "默认策略不能删除，请先把其他策略设为默认"


def test_split_recursive_creates_plain_chunks(client, admin_headers, kb_id, parsed_doc):
    """递归分块切出一组平级的普通块，并同步文档和知识库的片段数。"""
    strategies = client.get("/chunkStrategy/selectAll", headers=admin_headers).json()
    recursive = [item for item in strategies["data"] if item["strategy_type"] == "递归分块"][0]

    body = client.post(
        f"/knowledgeChunk/split/{parsed_doc}",
        params={"strategy_id": recursive["id"]},
        headers=admin_headers,
    ).json()
    assert body["code"] == "200"

    page = client.get(
        "/knowledgeChunk/selectPage",
        params={"document_id": parsed_doc, "page_num": 1, "page_size": 50},
        headers=admin_headers,
    ).json()
    chunks = page["data"]["list"]
    assert len(chunks) > 0
    assert all(chunk["chunk_type"] == "普通块" for chunk in chunks)
    assert all(chunk["parent_id"] is None for chunk in chunks)

    detail = client.get(f"/knowledgeDocument/selectById/{parsed_doc}", headers=admin_headers).json()
    assert detail["data"]["chunk_count"] == page["data"]["total"]
    kb = client.get(f"/knowledgeBase/selectById/{kb_id}", headers=admin_headers).json()
    assert kb["data"]["chunk_count"] == page["data"]["total"]


def test_split_parent_child_links_children_to_parent(client, admin_headers, kb_id, parsed_doc):
    """父子分块产出父块和子块，子块的 parent_id 指向真实的父块。"""
    strategies = client.get("/chunkStrategy/selectAll", headers=admin_headers).json()
    parent_child = [item for item in strategies["data"] if item["strategy_type"] == "父子分块"][0]

    client.post(
        f"/knowledgeChunk/split/{parsed_doc}",
        params={"strategy_id": parent_child["id"]},
        headers=admin_headers,
    )

    page = client.get(
        "/knowledgeChunk/selectPage",
        params={"document_id": parsed_doc, "page_num": 1, "page_size": 100},
        headers=admin_headers,
    ).json()
    chunks = page["data"]["list"]
    parents = [chunk for chunk in chunks if chunk["chunk_type"] == "父块"]
    children = [chunk for chunk in chunks if chunk["chunk_type"] == "子块"]
    assert parents and children
    parent_ids = {chunk["id"] for chunk in parents}
    # 每个子块都挂在一个真实存在的父块下
    assert all(chunk["parent_id"] in parent_ids for chunk in children)

    # 片段数只统计参与检索的块，父块不计入
    detail = client.get(f"/knowledgeDocument/selectById/{parsed_doc}", headers=admin_headers).json()
    assert detail["data"]["chunk_count"] == len(children)


def test_split_requires_parsed_document(client, admin_headers, kb_id):
    """没解析过的文档不能切分。"""
    client.post(
        "/knowledgeDocument/add",
        json={
            "kb_id": kb_id,
            "name": "未解析文档.txt",
            "file_name": "未解析文档.txt",
            "file_url": "http://127.0.0.1:9090/files/download/未解析文档.txt",
        },
        headers=admin_headers,
    )
    page = client.get(
        "/knowledgeDocument/selectPage",
        params={"kb_id": kb_id, "name": "未解析文档", "page_num": 1, "page_size": 10},
        headers=admin_headers,
    ).json()
    doc_id = page["data"]["list"][0]["id"]

    body = client.post(f"/knowledgeChunk/split/{doc_id}", headers=admin_headers).json()
    assert body["code"] == "500"
    assert body["msg"] == "请先解析文档，解析完成后才能切分"


def test_update_chunk_resets_vector_status(client, admin_headers, parsed_doc):
    """人工修改片段后，片段和文档的向量化状态都回到待向量化。"""
    client.post(f"/knowledgeChunk/split/{parsed_doc}", headers=admin_headers)
    page = client.get(
        "/knowledgeChunk/selectPage",
        params={"document_id": parsed_doc, "page_num": 1, "page_size": 10},
        headers=admin_headers,
    ).json()
    chunk_id = page["data"]["list"][0]["id"]

    body = client.put(
        "/knowledgeChunk/update",
        json={"id": chunk_id, "content": "人工修正后的片段内容。"},
        headers=admin_headers,
    ).json()
    assert body["code"] == "200"

    detail = client.get(f"/knowledgeChunk/selectById/{chunk_id}", headers=admin_headers).json()
    assert detail["data"]["content"] == "人工修正后的片段内容。"
    assert detail["data"]["char_count"] == len("人工修正后的片段内容。")
    assert detail["data"]["vector_status"] == "待向量化"


def test_empty_chunk_content_is_rejected(client, admin_headers, parsed_doc):
    """片段内容不允许改成空。"""
    client.post(f"/knowledgeChunk/split/{parsed_doc}", headers=admin_headers)
    page = client.get(
        "/knowledgeChunk/selectPage",
        params={"document_id": parsed_doc, "page_num": 1, "page_size": 10},
        headers=admin_headers,
    ).json()
    chunk_id = page["data"]["list"][0]["id"]

    body = client.put(
        "/knowledgeChunk/update",
        json={"id": chunk_id, "content": "   "},
        headers=admin_headers,
    ).json()
    assert body["code"] == "500"
    assert body["msg"] == "片段内容不能为空"


def test_parent_chunk_cannot_be_deleted(client, admin_headers, parsed_doc):
    """父块不允许单独删除。"""
    strategies = client.get("/chunkStrategy/selectAll", headers=admin_headers).json()
    parent_child = [item for item in strategies["data"] if item["strategy_type"] == "父子分块"][0]
    client.post(
        f"/knowledgeChunk/split/{parsed_doc}",
        params={"strategy_id": parent_child["id"]},
        headers=admin_headers,
    )
    page = client.get(
        "/knowledgeChunk/selectPage",
        params={"document_id": parsed_doc, "chunk_type": "父块", "page_num": 1, "page_size": 10},
        headers=admin_headers,
    ).json()
    parent_id = page["data"]["list"][0]["id"]

    body = client.delete(f"/knowledgeChunk/delete/{parent_id}", headers=admin_headers).json()
    assert body["code"] == "500"
    assert body["msg"] == "父块不能单独删除，请重新切分整篇文档"


def test_resplit_replaces_old_chunks(client, admin_headers, parsed_doc):
    """重新切分会清掉旧片段，不会新旧混在一起。"""
    strategies = client.get("/chunkStrategy/selectAll", headers=admin_headers).json()
    long_one = [item for item in strategies["data"] if item["strategy_type"] == "递归分块" and item["chunk_size"] >= 500][0]
    short_one = [item for item in strategies["data"] if item["strategy_type"] == "递归分块" and item["chunk_size"] < 500][0]

    client.post(f"/knowledgeChunk/split/{parsed_doc}", params={"strategy_id": long_one["id"]}, headers=admin_headers)
    first_total = client.get(
        "/knowledgeChunk/selectPage",
        params={"document_id": parsed_doc, "page_num": 1, "page_size": 100},
        headers=admin_headers,
    ).json()["data"]["total"]

    client.post(f"/knowledgeChunk/split/{parsed_doc}", params={"strategy_id": short_one["id"]}, headers=admin_headers)
    second_total = client.get(
        "/knowledgeChunk/selectPage",
        params={"document_id": parsed_doc, "page_num": 1, "page_size": 100},
        headers=admin_headers,
    ).json()["data"]["total"]

    # 片段更短的策略切出的片段数更多，且没有把上一轮的片段留下来
    assert second_total > first_total
    detail = client.get(f"/knowledgeDocument/selectById/{parsed_doc}", headers=admin_headers).json()
    assert detail["data"]["chunk_count"] == second_total
