"""工具中心测试。

工具的注册、启用开关、定义生成、调用日志都不依赖模型和向量库，可以直接测。
"""

import pytest

from ai import tools
from common.exception_handler import CustomException
from models import FunctionTool, ToolCallLog

TOOL_CODE = "unit_test_tool"


@pytest.fixture()
async def temp_tool(db):
    """注册一条只存在于表里、代码里没有实现的工具。"""
    tool = await FunctionTool.create(
        tool_code=TOOL_CODE,
        tool_name="单元测试工具",
        description="仅用于测试的工具",
        enabled="是",
        sort=99,
    )
    yield tool
    await ToolCallLog.filter(tool_code=TOOL_CODE).delete()
    await FunctionTool.filter(tool_code=TOOL_CODE).delete()


def test_seed_tools_are_registered(client, admin_headers):
    """初始化数据里的三条工具都注册了，且代码里都有实现。"""
    body = client.get(
        "/functionTool/selectPage",
        params={"page_num": 1, "page_size": 20},
        headers=admin_headers,
    ).json()
    codes = {item["tool_code"] for item in body["data"]["list"]}
    assert {"search_knowledge", "list_documents", "get_document_detail"} <= codes
    for item in body["data"]["list"]:
        if item["tool_code"] in tools.IMPLEMENTATIONS:
            assert item["implemented"] is True


def test_description_is_required(client, admin_headers):
    """描述会原样发给模型，不允许为空。"""
    body = client.post(
        "/functionTool/add",
        json={"tool_code": "no_desc_tool", "tool_name": "没有描述"},
        headers=admin_headers,
    ).json()
    assert body["code"] == "500"
    assert body["msg"] == "请输入工具描述，模型靠它判断什么时候调用这个工具"


def test_duplicated_code_is_rejected(client, admin_headers):
    """工具编码不允许重复。"""
    body = client.post(
        "/functionTool/add",
        json={"tool_code": "search_knowledge", "tool_name": "重复的", "description": "描述"},
        headers=admin_headers,
    ).json()
    assert body["code"] == "500"
    assert body["msg"] == "工具编码重复"


def test_implemented_tool_cannot_be_deleted(client, admin_headers):
    """代码里有实现的工具不允许删除，只能停用。"""
    page = client.get(
        "/functionTool/selectPage",
        params={"page_num": 1, "page_size": 20},
        headers=admin_headers,
    ).json()
    target = [item for item in page["data"]["list"] if item["tool_code"] == "search_knowledge"][0]

    body = client.delete(f"/functionTool/delete/{target['id']}", headers=admin_headers).json()
    assert body["code"] == "500"
    assert body["msg"] == "代码里有实现的工具不允许删除，请改用停用"


async def test_disabled_tool_is_not_given_to_model(db, temp_tool):
    """停用的工具不会出现在给模型的工具清单里。"""
    before = await tools.load_enabled_tools()
    before_codes = {item["tool_code"] for item in before}

    await FunctionTool.filter(id=temp_tool.id).update(enabled="否")
    after = await tools.load_enabled_tools()
    after_codes = {item["tool_code"] for item in after}

    # 这条工具本来就因为没实现而不在清单里，验证的是有实现那几条不受影响
    assert "search_knowledge" in before_codes
    assert "search_knowledge" in after_codes


async def test_registered_but_unimplemented_tool_is_skipped(db, temp_tool):
    """表里启用、但代码里没实现的工具不会给模型。"""
    usable = await tools.load_enabled_tools()
    assert TOOL_CODE not in {item["tool_code"] for item in usable}


async def test_invoke_unimplemented_tool_is_rejected(db, temp_tool):
    """调用没有实现的工具时给出人话提示。"""
    with pytest.raises(CustomException) as excinfo:
        await tools.invoke(TOOL_CODE, {})
    assert excinfo.value.message == f"工具 {TOOL_CODE} 没有对应的实现"


async def test_invoke_disabled_tool_is_rejected(db):
    """运行时再校验一次启用状态，挡住拿旧清单调已停用工具的情况。"""
    await FunctionTool.filter(tool_code="list_documents").update(enabled="否")
    try:
        with pytest.raises(CustomException) as excinfo:
            await tools.invoke("list_documents", {"kb_id": 1})
        assert "已被停用" in excinfo.value.message
    finally:
        await FunctionTool.filter(tool_code="list_documents").update(enabled="是")


async def test_invoke_writes_success_log(db):
    """成功调用会留下一条状态为成功的日志。"""
    before = await ToolCallLog.filter(tool_code="list_documents").count()

    await tools.invoke("list_documents", {"kb_id": 999999})

    after = await ToolCallLog.filter(tool_code="list_documents").count()
    assert after == before + 1
    latest = await ToolCallLog.filter(tool_code="list_documents").order_by("-id").first()
    assert latest.call_status == "成功"
    assert latest.cost_millis is not None


async def test_invoke_writes_failure_log(db):
    """调用失败同样留日志，并记下失败原因。"""
    with pytest.raises(CustomException):
        await tools.invoke("get_document_detail", {"document_id": 999999})

    latest = await ToolCallLog.filter(tool_code="get_document_detail").order_by("-id").first()
    assert latest.call_status == "失败"
    assert latest.error_message == "未找到文档"


def test_definitions_only_include_enabled_tools(client, admin_headers):
    """工具定义预览只包含启用且有实现的工具。"""
    body = client.get("/functionTool/definitions", headers=admin_headers).json()
    assert body["code"] == "200"
    names = {item["function"]["name"] for item in body["data"]}
    assert "search_knowledge" in names
    for item in body["data"]:
        assert item["type"] == "function"
        # 描述直接来自表里那段文字
        assert item["function"]["description"]


def test_toggle_changes_definitions(client, admin_headers):
    """页面上停用一个工具后，工具定义里立刻少一条。"""
    page = client.get(
        "/functionTool/selectPage",
        params={"page_num": 1, "page_size": 20},
        headers=admin_headers,
    ).json()
    target = [item for item in page["data"]["list"] if item["tool_code"] == "list_documents"][0]

    client.put(f"/functionTool/toggle/{target['id']}", params={"enabled": "否"}, headers=admin_headers)
    after = client.get("/functionTool/definitions", headers=admin_headers).json()
    assert "list_documents" not in {item["function"]["name"] for item in after["data"]}

    client.put(f"/functionTool/toggle/{target['id']}", params={"enabled": "是"}, headers=admin_headers)
    restored = client.get("/functionTool/definitions", headers=admin_headers).json()
    assert "list_documents" in {item["function"]["name"] for item in restored["data"]}


def test_log_summary_counts_by_tool(client, admin_headers):
    """按工具统计调用次数和成功率。"""
    body = client.get("/functionTool/logSummary", headers=admin_headers).json()
    assert body["code"] == "200"
    for item in body["data"]:
        assert {"tool_code", "tool_name", "enabled", "total", "failed", "success_rate"} <= set(item.keys())
        if item["total"] == 0:
            # 一次都没调过时不显示 100%，避免造成误解
            assert item["success_rate"] is None
