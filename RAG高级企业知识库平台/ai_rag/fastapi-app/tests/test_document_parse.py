"""文档解析接口测试。

用临时文件覆盖 TXT、Excel、PDF 三条解析路径，以及文件缺失和空文件两种失败路径。
扫描件 OCR 需要真实扫描件，放在页面上手工验证。
"""

import os

import pytest

from service.file_service import UPLOAD_DIR

KB_NAME = "测试解析库-单元测试专用"


@pytest.fixture()
def kb_id(client, admin_headers):
    """建一个临时知识库，用完连同库下文档一起清掉。"""
    client.post(
        "/knowledgeBase/add",
        json={"name": KB_NAME, "status": "正常"},
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


@pytest.fixture()
def temp_files():
    """记录本次测试写到 files 目录里的文件，跑完删掉。"""
    created = []
    yield created
    for name in created:
        path = os.path.join(UPLOAD_DIR, name)
        if os.path.exists(path):
            os.remove(path)


def _write_text_file(temp_files, file_name, content):
    os.makedirs(UPLOAD_DIR, exist_ok=True)
    path = os.path.join(UPLOAD_DIR, file_name)
    with open(path, "w", encoding="utf-8") as handle:
        handle.write(content)
    temp_files.append(file_name)
    return path


def _add_doc(client, admin_headers, kb_id, file_name):
    client.post(
        "/knowledgeDocument/add",
        json={
            "kb_id": kb_id,
            "name": file_name,
            "file_name": file_name,
            "file_url": f"http://127.0.0.1:9090/files/download/{file_name}",
            "file_size": 100,
        },
        headers=admin_headers,
    )
    page = client.get(
        "/knowledgeDocument/selectPage",
        params={"kb_id": kb_id, "name": file_name, "page_num": 1, "page_size": 10},
        headers=admin_headers,
    ).json()
    return page["data"]["list"][0]["id"]


def test_parse_txt_writes_text_and_char_count(client, admin_headers, kb_id, temp_files):
    """TXT 解析完成后写入文本和字符数，状态变成解析完成。"""
    content = "GTE-3000 型号的质保时长为 24 个月。\n超出质保期按次收费。"
    _write_text_file(temp_files, "质保说明.txt", content)
    doc_id = _add_doc(client, admin_headers, kb_id, "质保说明.txt")

    assert client.post(f"/knowledgeDocument/parse/{doc_id}", headers=admin_headers).json()["code"] == "200"

    detail = client.get(f"/knowledgeDocument/parsedText/{doc_id}", headers=admin_headers).json()
    assert detail["data"]["parse_status"] == "解析完成"
    assert "GTE-3000" in detail["data"]["parsed_text"]
    assert detail["data"]["char_count"] == len(content)
    # 纯文本没有表格也没走 OCR
    assert detail["data"]["has_table"] == "否"
    assert detail["data"]["has_ocr"] == "否"


def test_parse_excel_converts_sheet_to_markdown_table(client, admin_headers, kb_id, temp_files):
    """Excel 每个工作表转成 Markdown 表格，并打上含表格标记。"""
    from openpyxl import Workbook

    file_name = "保修期对照表.xlsx"
    os.makedirs(UPLOAD_DIR, exist_ok=True)
    path = os.path.join(UPLOAD_DIR, file_name)
    workbook = Workbook()
    sheet = workbook.active
    sheet.title = "保修期"
    sheet.append(["型号", "保修期", "备注"])
    sheet.append(["GTE-3000", "24个月", "含主板"])
    workbook.save(path)
    workbook.close()
    temp_files.append(file_name)

    doc_id = _add_doc(client, admin_headers, kb_id, file_name)
    client.post(f"/knowledgeDocument/parse/{doc_id}", headers=admin_headers)

    detail = client.get(f"/knowledgeDocument/parsedText/{doc_id}", headers=admin_headers).json()
    text = detail["data"]["parsed_text"]
    assert detail["data"]["parse_status"] == "解析完成"
    assert detail["data"]["has_table"] == "是"
    # 工作表名称带在文本里，一个文件里多张表时能区分
    assert "【工作表：保修期】" in text
    # 转成了 Markdown 表格，模型能认出行列关系
    assert "| 型号 | 保修期 | 备注 |" in text
    assert "| GTE-3000 | 24个月 | 含主板 |" in text


def test_parse_pdf_keeps_page_number(client, admin_headers, kb_id, temp_files):
    """PDF 解析结果按页分段，段首标出页码。"""
    import pymupdf

    file_name = "产品说明.pdf"
    os.makedirs(UPLOAD_DIR, exist_ok=True)
    path = os.path.join(UPLOAD_DIR, file_name)
    document = pymupdf.open()
    page = document.new_page()
    page.insert_text((72, 100), "Warranty period is 24 months.")
    document.save(path)
    document.close()
    temp_files.append(file_name)

    doc_id = _add_doc(client, admin_headers, kb_id, file_name)
    client.post(f"/knowledgeDocument/parse/{doc_id}", headers=admin_headers)

    detail = client.get(f"/knowledgeDocument/parsedText/{doc_id}", headers=admin_headers).json()
    assert detail["data"]["parse_status"] == "解析完成"
    assert "【第 1 页】" in detail["data"]["parsed_text"]
    assert "24 months" in detail["data"]["parsed_text"]
    # 有文字层就不会走 OCR
    assert detail["data"]["has_ocr"] == "否"


def test_parse_missing_file_is_rejected(client, admin_headers, kb_id):
    """原始文件不在磁盘上时，接口直接拦住，不建任务。"""
    doc_id = _add_doc(client, admin_headers, kb_id, "根本不存在的文件.txt")

    body = client.post(f"/knowledgeDocument/parse/{doc_id}", headers=admin_headers).json()
    assert body["code"] == "500"
    assert body["msg"] == "原始文件不存在，请重新上传"


def test_parse_empty_file_marks_failed(client, admin_headers, kb_id, temp_files):
    """空文件解析不出内容，状态标成解析失败并记下原因。"""
    _write_text_file(temp_files, "空文件.txt", "   ")
    doc_id = _add_doc(client, admin_headers, kb_id, "空文件.txt")

    client.post(f"/knowledgeDocument/parse/{doc_id}", headers=admin_headers)

    detail = client.get(f"/knowledgeDocument/parsedText/{doc_id}", headers=admin_headers).json()
    assert detail["data"]["parse_status"] == "解析失败"
    assert detail["data"]["parse_error"] == "没有解析出任何文本，请确认文件内容不是空的"


def test_parse_records_task(client, admin_headers, kb_id, temp_files):
    """每次解析都会留下一条任务记录，成功时状态是已完成。"""
    _write_text_file(temp_files, "任务记录测试.txt", "一段用于验证任务记录的文本。")
    doc_id = _add_doc(client, admin_headers, kb_id, "任务记录测试.txt")

    client.post(f"/knowledgeDocument/parse/{doc_id}", headers=admin_headers)

    tasks = client.get(f"/knowledgeDocument/tasks/{doc_id}", headers=admin_headers).json()
    assert tasks["code"] == "200"
    latest = tasks["data"][0]
    assert latest["task_type"] == "文档解析"
    assert latest["task_status"] == "已完成"
    assert latest["success_count"] == 1
    assert latest["cost_millis"] is not None
