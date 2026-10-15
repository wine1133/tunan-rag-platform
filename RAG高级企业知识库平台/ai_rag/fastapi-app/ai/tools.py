"""Agent 工具。

Agent 能用哪些工具由 function_tool 表决定，不是由这个文件里写了多少个函数决定。
表里 enabled 为"否"的工具，运行时不会出现在给模型的工具清单里——
这个开关是真的：管理员在页面上停用之后，模型下一次执行就真的用不了它。

新增一个工具要做两件事，缺一不可：

    1. 在这里写一个实现函数，并登记进 IMPLEMENTATIONS
    2. 在 function_tool 表里插一条记录，tool_code 和函数名一致

只做第一件，工具不会被启用；只做第二件，调用时会报"没有对应的实现"。
"""

import json

from common.exception_handler import CustomException
from common.times import cost_millis, now
from models import FunctionTool, KnowledgeDocument, ToolCallLog


async def search_knowledge(query: str, kb_id: int, top_k: int = 5) -> dict:
    """在指定知识库里检索资料。

    Agent 最主要的工具，内部走的就是第 15 到 19 章那条完整的检索链路。
    """
    # 在函数内部导入，避免 service 层和 ai 层在模块加载时相互引用
    from service import retrieval_service

    strategy = await retrieval_service.load_strategy(None)
    outcome = await retrieval_service.retrieve([kb_id], query, strategy)
    return {
        "count": len(outcome["results"]),
        "results": [
            {
                "chunk_id": item["chunk_id"],
                "document_id": item.get("document_id"),
                "score": item.get("score"),
                "content": item["content"],
            }
            for item in outcome["results"][:top_k]
        ],
    }


async def list_documents(kb_id: int) -> dict:
    """查这个知识库下有哪些文档。

    用来回答"知识库里都有什么资料"这类问题——这类问题检索不出答案，
    因为答案不在任何一个片段里，而在文档清单上。
    """
    documents = await KnowledgeDocument.filter(kb_id=kb_id).order_by("id").limit(50)
    return {
        "count": len(documents),
        "documents": [
            {"id": doc.id, "name": doc.name, "file_type": doc.file_type, "chunk_count": doc.chunk_count}
            for doc in documents
        ],
    }


async def get_document_detail(document_id: int) -> dict:
    """按文档 ID 查一篇文档的详情。"""
    doc = await KnowledgeDocument.get_or_none(id=document_id)
    if doc is None:
        raise CustomException("未找到文档")
    return {
        "id": doc.id,
        "name": doc.name,
        "file_type": doc.file_type,
        "char_count": doc.char_count,
        "chunk_count": doc.chunk_count,
        "parse_status": doc.parse_status,
        "vector_status": doc.vector_status,
    }


# tool_code 到实现函数的映射。表里的 tool_code 必须能在这里找到对应的函数
IMPLEMENTATIONS = {
    "search_knowledge": search_knowledge,
    "list_documents": list_documents,
    "get_document_detail": get_document_detail,
}


async def load_enabled_tools() -> list[dict]:
    """读出当前启用、且代码里有实现的工具清单。

    两个条件缺一不可：
    表里停用的不给模型；表里启用但代码里没实现的也不给，
    否则模型会调一个根本执行不了的工具。
    """
    tools = await FunctionTool.filter(enabled="是").order_by("sort", "id")
    usable = []
    for tool in tools:
        if tool.tool_code not in IMPLEMENTATIONS:
            continue
        usable.append(
            {
                "tool_code": tool.tool_code,
                "tool_name": tool.tool_name,
                "description": tool.description,
                "input_schema": tool.input_schema,
            }
        )
    return usable


def to_openai_tools(tools: list[dict]) -> list[dict]:
    """把工具清单转成模型能识别的 tools 结构。

    description 直接用表里那段文字，管理员改完描述、模型下一次判断就跟着变，
    不用改代码也不用重启。
    """
    definitions = []
    for tool in tools:
        try:
            schema = json.loads(tool["input_schema"]) if tool["input_schema"] else {}
        except json.JSONDecodeError:
            # 表里的 JSON 写错了不该让整次执行崩掉，退化成无参工具
            schema = {}
        definitions.append(
            {
                "type": "function",
                "function": {
                    "name": tool["tool_code"],
                    "description": tool["description"] or tool["tool_name"],
                    "parameters": {
                        "type": "object",
                        "properties": {
                            key: {"type": "string", "description": str(value)}
                            for key, value in schema.items()
                        },
                    },
                },
            }
        )
    return definitions


async def invoke(tool_code: str, params: dict, run_id: int | None = None, step_id: int | None = None) -> dict:
    """执行一个工具并记日志。

    成功失败都记一条日志，失败时把原因写进 error_message，
    第 21 章的工具调用日志页面靠它统计每个工具的成功率。
    """
    tool = await FunctionTool.get_or_none(tool_code=tool_code)
    if tool is None:
        raise CustomException(f"工具 {tool_code} 未注册")
    # 运行时再校验一次启用状态，挡住"模型拿着旧清单调已停用工具"的情况
    if tool.enabled != "是":
        raise CustomException(f"工具 {tool.tool_name} 已被停用")
    implementation = IMPLEMENTATIONS.get(tool_code)
    if implementation is None:
        raise CustomException(f"工具 {tool_code} 没有对应的实现")
    started = now()
    try:
        result = await implementation(**params)
        await ToolCallLog.create(
            run_id=run_id,
            step_id=step_id,
            tool_code=tool_code,
            tool_name=tool.tool_name,
            request_params=json.dumps(params, ensure_ascii=False),
            response_result=json.dumps(result, ensure_ascii=False, default=str)[:60000],
            call_status="成功",
            cost_millis=cost_millis(started),
        )
        return result
    except Exception as exc:
        message = exc.message if isinstance(exc, CustomException) else str(exc)
        await ToolCallLog.create(
            run_id=run_id,
            step_id=step_id,
            tool_code=tool_code,
            tool_name=tool.tool_name,
            request_params=json.dumps(params, ensure_ascii=False),
            call_status="失败",
            # 列宽是 varchar(500)，写库前截断
            error_message=message[:500],
            cost_millis=cost_millis(started),
        )
        raise
