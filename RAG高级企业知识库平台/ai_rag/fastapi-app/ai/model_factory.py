"""模型工厂。

全项目只有这一个地方构造大模型对象，配置一律从 ai_model_config 表里读，
改配置立刻生效，不用重启服务，也不用在代码里写死任何密钥和地址。

三类模型的调用路径：

    对话模型  OpenAI 兼容接口 -> langchain_openai.ChatOpenAI
    向量模型  OpenAI 兼容接口 -> langchain_openai.OpenAIEmbeddings
    重排模型  百炼没有 OpenAI 兼容的重排接口，走 DashScope 原生接口，用 httpx 直接调
"""

import httpx
from langchain_openai import ChatOpenAI, OpenAIEmbeddings

from common.exception_handler import CustomException
from models import AiModelConfig

CHAT = "对话模型"
EMBEDDING = "向量模型"
RERANK = "重排模型"

# DashScope 原生的文本重排接口路径，拼在配置的 base_url 后面
RERANK_PATH = "/services/rerank/text-rerank/text-rerank"


async def load_enabled(model_type: str) -> AiModelConfig:
    """取某一类型下启用的那条配置。

    同一类型允许存多条，但只允许一条启用，代码永远只认启用的那条。
    """
    config = await AiModelConfig.get_or_none(model_type=model_type, enabled="是")
    if config is None:
        raise CustomException(f"没有启用的{model_type}，请先到 AI 模型配置里启用一条")
    if not config.api_key:
        raise CustomException(f"{model_type}还没有填写 API Key，请先到 AI 模型配置里补上")
    if not config.model_name:
        raise CustomException(f"{model_type}还没有填写模型名称，请先到 AI 模型配置里补上")
    return config


def build_chat_model(config: AiModelConfig, temperature: float = 0.0) -> ChatOpenAI:
    """构造对话模型。

    temperature 默认给 0，检索问答、相关性判断、评分这些场景都要求结果稳定，
    同一个问题反复问应该给出一致的答案。
    """
    return ChatOpenAI(
        model=config.model_name,
        api_key=config.api_key,
        base_url=config.base_url,
        temperature=temperature,
        # 超时和重试次数写在这里，避免某次网络抖动让整个问答链路挂掉
        timeout=60,
        max_retries=2,
    )


def build_embeddings(config: AiModelConfig) -> OpenAIEmbeddings:
    """构造向量模型。"""
    return OpenAIEmbeddings(
        model=config.model_name,
        api_key=config.api_key,
        base_url=config.base_url,
        # 显式指定维度，必须和 PGVector 建表时的 vector(1024) 一致
        dimensions=config.dimension or 1024,
        # LangChain 默认先把文本切成 token id 数组再发，只有 OpenAI 官方接口收这种格式。
        # 百炼的 OpenAI 兼容接口只接受字符串，收到数组会返回
        # "contents is neither str nor list of str"，所以这里关掉这个预处理，
        # 让请求体里原样带上文本。
        check_embedding_ctx_length=False,
        timeout=60,
        max_retries=2,
    )


async def rerank(config: AiModelConfig, query: str, documents: list[str], top_n: int) -> list[dict]:
    """调用 DashScope 原生重排接口，返回按相关性排好序的结果。

    返回的每一项形如 {"index": 原始下标, "relevance_score": 相关性得分}，
    index 指向传进来的 documents 列表，调用方按它回到原始片段。
    """
    url = config.base_url.rstrip("/") + RERANK_PATH
    payload = {
        "model": config.model_name,
        "input": {"query": query, "documents": documents},
        "parameters": {"top_n": top_n, "return_documents": False},
    }
    headers = {
        "Authorization": f"Bearer {config.api_key}",
        "Content-Type": "application/json",
    }
    async with httpx.AsyncClient(timeout=60) as client:
        response = await client.post(url, json=payload, headers=headers)
    if response.status_code != 200:
        raise CustomException(f"重排接口调用失败：{translate_http_error(response)}")
    body = response.json()
    return body.get("output", {}).get("results", [])


def translate_http_error(response: httpx.Response) -> str:
    """把接口返回的错误翻译成人话。

    模型服务返回的原始报文是英文的 JSON，直接抛给用户看不懂，
    这里按状态码给出对应的处置建议。
    """
    if response.status_code == 401:
        return "API Key 无效，请检查 AI 模型配置里的密钥"
    if response.status_code == 403:
        return "API Key 没有该模型的调用权限，请到百炼控制台确认已开通"
    if response.status_code == 404:
        return "接口地址或模型名称不存在，请检查 base_url 和模型名称"
    if response.status_code == 429:
        return "调用太频繁或额度已用尽，请稍后再试"
    # 其他情况把原始报文截断后带上，便于排查
    return f"状态码 {response.status_code}，返回内容：{response.text[:200]}"


def translate_exception(exc: Exception) -> str:
    """把 SDK 抛出的异常翻译成人话。"""
    message = str(exc)
    lowered = message.lower()
    if "api key" in lowered or "401" in lowered or "invalid_api_key" in lowered:
        return "API Key 无效，请检查 AI 模型配置里的密钥"
    if "not found" in lowered or "404" in lowered:
        return "模型名称或接口地址不存在，请检查配置"
    if "timeout" in lowered or "timed out" in lowered:
        return "调用超时，请检查网络或稍后再试"
    if "connect" in lowered:
        return "连不上接口地址，请检查 base_url 和本机网络"
    return f"调用失败：{message[:200]}"


async def test_connection(config: AiModelConfig) -> str:
    """连通性测试。

    每类模型都发一次最小请求，能拿到正常响应就说明地址、密钥、模型名都对。
    """
    if not config.api_key:
        raise CustomException("请先填写 API Key")
    if not config.model_name:
        raise CustomException("请先填写模型名称")
    try:
        if config.model_type == CHAT:
            model = build_chat_model(config)
            # 只让模型回一个字，把测试成本压到最低
            reply = await model.ainvoke("回复一个字：好")
            return f"对话模型连通正常，返回：{str(reply.content)[:50]}"
        if config.model_type == EMBEDDING:
            embeddings = build_embeddings(config)
            vector = await embeddings.aembed_query("连通性测试")
            actual = len(vector)
            expected = config.dimension or 1024
            # 维度对不上会导致写向量库时报错，这里提前发现
            if actual != expected:
                raise CustomException(
                    f"向量模型实际输出 {actual} 维，配置里写的是 {expected} 维，请改成一致"
                )
            return f"向量模型连通正常，输出 {actual} 维向量"
        if config.model_type == RERANK:
            results = await rerank(config, "保修期", ["质保时长为 24 个月", "退换货流程"], 1)
            if not results:
                raise CustomException("重排接口没有返回结果，请检查模型名称")
            return "重排模型连通正常"
        raise CustomException("未知的模型类型")
    except CustomException:
        raise
    except Exception as exc:
        raise CustomException(translate_exception(exc))
