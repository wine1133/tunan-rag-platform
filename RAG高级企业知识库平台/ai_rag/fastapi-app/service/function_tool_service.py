"""工具中心业务逻辑。"""

from typing import List

from ai import tools
from common.exception_handler import CustomException
from common.result import PageInfo
from models import FunctionTool, ToolCallLog


def tool_dict(tool: FunctionTool) -> dict:
    return {
        "id": tool.id,
        "tool_code": tool.tool_code,
        "tool_name": tool.tool_name,
        "description": tool.description,
        "input_schema": tool.input_schema,
        "enabled": tool.enabled,
        "sort": tool.sort,
        # 表里配了但代码里没实现的工具，页面上要标出来，
        # 否则管理员以为启用了、模型其实拿不到
        "implemented": tool.tool_code in tools.IMPLEMENTATIONS,
        "create_time": tool.create_time,
        "update_time": tool.update_time,
    }


def _validate(payload: dict) -> None:
    if not payload.get("tool_code"):
        raise CustomException("请输入工具编码")
    if not payload.get("tool_name"):
        raise CustomException("请输入工具名称")
    # 描述会原样发给模型，模型靠它判断什么时候该调这个工具，不能为空
    if not payload.get("description"):
        raise CustomException("请输入工具描述，模型靠它判断什么时候调用这个工具")


async def add(payload: dict) -> None:
    _validate(payload)
    if await FunctionTool.get_or_none(tool_code=payload["tool_code"]):
        raise CustomException("工具编码重复")
    await FunctionTool.create(
        tool_code=payload["tool_code"],
        tool_name=payload["tool_name"],
        description=payload.get("description"),
        input_schema=payload.get("input_schema"),
        enabled=payload.get("enabled") or "是",
        sort=payload.get("sort") or 0,
    )


async def update(tool_id: int | None, payload: dict) -> None:
    if tool_id is None:
        raise CustomException("工具ID不能为空")
    if await FunctionTool.get_or_none(id=tool_id) is None:
        raise CustomException("未找到工具")
    _validate(payload)
    if await FunctionTool.filter(tool_code=payload["tool_code"]).exclude(id=tool_id).exists():
        raise CustomException("工具编码重复")
    await FunctionTool.filter(id=tool_id).update(
        tool_code=payload["tool_code"],
        tool_name=payload["tool_name"],
        description=payload.get("description"),
        input_schema=payload.get("input_schema"),
        enabled=payload.get("enabled") or "是",
        sort=payload.get("sort") or 0,
    )


async def toggle(tool_id: int, enabled: str) -> None:
    """页面上的启用开关。改完模型下一次执行就拿不到这个工具了。"""
    if enabled not in {"是", "否"}:
        raise CustomException("启用状态参数错误")
    if await FunctionTool.get_or_none(id=tool_id) is None:
        raise CustomException("未找到工具")
    await FunctionTool.filter(id=tool_id).update(enabled=enabled)


async def delete(tool_id: int) -> None:
    tool = await FunctionTool.get_or_none(id=tool_id)
    if tool is None:
        raise CustomException("未找到工具")
    # 代码里有实现的工具删掉之后，模型永远调不到它了，容易被忘掉
    if tool.tool_code in tools.IMPLEMENTATIONS:
        raise CustomException("代码里有实现的工具不允许删除，请改用停用")
    await FunctionTool.filter(id=tool_id).delete()


async def select_page(keyword: str = "", enabled: str = "", page_num: int = 1, page_size: int = 10) -> PageInfo:
    query = FunctionTool.filter(tool_name__contains=keyword)
    if enabled:
        query = query.filter(enabled=enabled)
    items = await query.order_by("sort", "id").offset((page_num - 1) * page_size).limit(page_size)
    total = await query.count()
    return PageInfo(total=total, list=[tool_dict(item) for item in items])


async def preview_definitions() -> List[dict]:
    """预览真正会发给模型的工具定义。

    页面上把这段 JSON 展示出来，管理员改完描述能立刻看到模型将会收到什么。
    """
    enabled_tools = await tools.load_enabled_tools()
    return tools.to_openai_tools(enabled_tools)


async def select_logs(
    tool_code: str = "",
    call_status: str = "",
    run_id: int | None = None,
    page_num: int = 1,
    page_size: int = 10,
) -> PageInfo:
    query = ToolCallLog.all()
    if tool_code:
        query = query.filter(tool_code=tool_code)
    if call_status:
        query = query.filter(call_status=call_status)
    if run_id:
        query = query.filter(run_id=run_id)
    logs = await query.order_by("-id").offset((page_num - 1) * page_size).limit(page_size)
    total = await query.count()
    return PageInfo(
        total=total,
        list=[
            {
                "id": log.id,
                "run_id": log.run_id,
                "step_id": log.step_id,
                "tool_code": log.tool_code,
                "tool_name": log.tool_name,
                "request_params": log.request_params,
                "response_result": log.response_result,
                "call_status": log.call_status,
                "error_message": log.error_message,
                "cost_millis": log.cost_millis,
                "create_time": log.create_time,
            }
            for log in logs
        ],
    )


async def log_summary() -> List[dict]:
    """按工具统计调用次数和成功率，看出哪个工具最常用、哪个最容易失败。"""
    all_tools = await FunctionTool.all().order_by("sort", "id")
    summary = []
    for tool in all_tools:
        total = await ToolCallLog.filter(tool_code=tool.tool_code).count()
        failed = await ToolCallLog.filter(tool_code=tool.tool_code, call_status="失败").count()
        summary.append(
            {
                "tool_code": tool.tool_code,
                "tool_name": tool.tool_name,
                "enabled": tool.enabled,
                "total": total,
                "failed": failed,
                # 一次都没调过时成功率显示为空，不显示 100% 造成误解
                "success_rate": round((total - failed) / total * 100, 1) if total else None,
            }
        )
    return summary
