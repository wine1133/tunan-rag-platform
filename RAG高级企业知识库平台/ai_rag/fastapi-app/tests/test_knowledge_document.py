"""知识文档管理接口测试。

覆盖上传建档、文件类型校验、知识库文档数同步、换文件后状态重置、删除。
"""

import pytest

KB_NAME = "测试文档库-单元测试专用"
DOC_NAME = "测试文档-单元测试专用"


@pytest.fixture()
def kb_id(client, admin_headers):
    """建一个临时知识库，用完连同库下文档一起清掉。"""
    client.post(
        "/knowledgeBase/add",
        json={"name": KB_NAME, "description": "自动化测试创建", "status": "正常"},
        headers=admin_headers,
    )
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
        client.request(
            "DELETE", "/knowledgeDocument/deleteBatch", json=doc_ids, headers=admin_headers
        )
    client.delete(f"/knowledgeBase/delete/{created['id']}", headers=admin_headers)


def _add_doc(client, admin_headers, kb_id, file_name="产品手册.pdf"):
    return client.post(
        "/knowledgeDocument/add",
        json={
            "kb_id": kb_id,
            "name": DOC_NAME,
            "file_name": file_name,
            "file_url": f"http://127.0.0.1:9090/files/download/{file_name}",
            "file_size": 20480,
        },
        headers=admin_headers,
    ).json()


def test_add_document_and_refresh_kb_count(client, admin_headers, kb_id):
    """上传建档后，知识库上的文档数同步加一。"""
    assert _add_doc(client, admin_headers, kb_id)["code"] == "200"

    detail = client.get(f"/knowledgeBase/selectById/{kb_id}", headers=admin_headers).json()
    assert detail["data"]["document_count"] == 1

    page = client.get(
        "/knowledgeDocument/selectPage",
        params={"kb_id": kb_id, "page_num": 1, "page_size": 10},
        headers=admin_headers,
    ).json()
    doc = page["data"]["list"][0]
    # 文件类型按后缀推断，解析和向量化都还没做，两个状态是初始值
    assert doc["file_type"] == "PDF"
    assert doc["parse_status"] == "待解析"
    assert doc["vector_status"] == "待向量化"
    # 列表要显示所属知识库名称，它由后端按 kb_id 查知识库表得到
    assert doc["kb_name"] == KB_NAME


def test_unsupported_file_type_is_rejected(client, admin_headers, kb_id):
    """不在支持范围内的后缀直接拦住。"""
    body = _add_doc(client, admin_headers, kb_id, file_name="演示视频.mp4")
    assert body["code"] == "500"
    assert body["msg"] == "暂不支持该文件类型，请上传 PDF、Word、Excel、Markdown 或 TXT"


def test_add_without_file_is_rejected(client, admin_headers, kb_id):
    """没有上传文件时给出人话提示。"""
    body = client.post(
        "/knowledgeDocument/add",
        json={"kb_id": kb_id, "name": DOC_NAME},
        headers=admin_headers,
    ).json()
    assert body["code"] == "500"
    assert body["msg"] == "请先上传文件"


def test_add_to_disabled_kb_is_rejected(client, admin_headers, kb_id):
    """知识库停用后不允许再往里传文档。"""
    client.put(
        "/knowledgeBase/update",
        json={"id": kb_id, "name": KB_NAME, "status": "停用"},
        headers=admin_headers,
    )
    body = _add_doc(client, admin_headers, kb_id)
    assert body["code"] == "500"
    assert body["msg"] == "该知识库已停用，不能上传文档"
    # 复原，让夹具能正常清理
    client.put(
        "/knowledgeBase/update",
        json={"id": kb_id, "name": KB_NAME, "status": "正常"},
        headers=admin_headers,
    )


def test_replace_file_resets_parse_and_vector_status(client, admin_headers, kb_id):
    """换了文件后解析结果作废，状态回到初始值。"""
    _add_doc(client, admin_headers, kb_id)
    page = client.get(
        "/knowledgeDocument/selectPage",
        params={"kb_id": kb_id, "page_num": 1, "page_size": 10},
        headers=admin_headers,
    ).json()
    doc_id = page["data"]["list"][0]["id"]

    body = client.put(
        "/knowledgeDocument/update",
        json={
            "id": doc_id,
            "kb_id": kb_id,
            "name": DOC_NAME,
            "file_name": "售后制度.docx",
            "file_url": "http://127.0.0.1:9090/files/download/售后制度.docx",
            "file_size": 10240,
        },
        headers=admin_headers,
    ).json()
    assert body["code"] == "200"

    detail = client.get(f"/knowledgeDocument/selectById/{doc_id}", headers=admin_headers).json()
    assert detail["data"]["file_type"] == "WORD"
    assert detail["data"]["parse_status"] == "待解析"
    assert detail["data"]["vector_status"] == "待向量化"
    assert detail["data"]["char_count"] == 0


def test_delete_document_refresh_kb_count(client, admin_headers, kb_id):
    """删除文档后知识库上的文档数减回去。"""
    _add_doc(client, admin_headers, kb_id)
    page = client.get(
        "/knowledgeDocument/selectPage",
        params={"kb_id": kb_id, "page_num": 1, "page_size": 10},
        headers=admin_headers,
    ).json()
    doc_id = page["data"]["list"][0]["id"]

    client.delete(f"/knowledgeDocument/delete/{doc_id}", headers=admin_headers)

    detail = client.get(f"/knowledgeBase/selectById/{kb_id}", headers=admin_headers).json()
    assert detail["data"]["document_count"] == 0


def test_kb_with_documents_cannot_be_deleted(client, admin_headers, kb_id):
    """知识库下还有文档时不允许删库。"""
    _add_doc(client, admin_headers, kb_id)

    body = client.delete(f"/knowledgeBase/delete/{kb_id}", headers=admin_headers).json()
    assert body["code"] == "500"
    assert body["msg"] == "该知识库下还有文档，请先删除文档"
