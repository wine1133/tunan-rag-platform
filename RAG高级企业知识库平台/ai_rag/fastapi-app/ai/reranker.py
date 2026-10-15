"""重排。

第 13 章讲的第二个失效点：向量相似度衡量的是整体语义接近，
不是"这段能不能回答这个问题"，所以真正的答案经常排在第 4 位被模型忽略。

向量检索是双塔模型：问题和片段各自独立编码成向量，再算距离，
编码片段的时候模型并不知道用户会问什么。

重排模型是交叉编码：把问题和片段拼在一起送进模型，直接输出相关性得分。
精确得多，但也慢得多，所以只能用在粗筛之后的少量候选上：

    向量 + BM25 粗筛出 10 到 20 条  ->  重排精排出前 3 到 4 条

百炼的重排接口不在 OpenAI 兼容模式下，调用逻辑写在第 11 章的 model_factory 里。
本模块把它包装成 LangChain 的 BaseDocumentCompressor，
这样重排就能作为一个标准组件接进 LangChain 的检索链路。
"""

from typing import Sequence

from langchain_core.callbacks import Callbacks
from langchain_core.documents import BaseDocumentCompressor, Document

from ai import model_factory
from common.exception_handler import CustomException
from models import AiModelConfig


class DashScopeRerank(BaseDocumentCompressor):
    """把百炼的重排接口包装成 LangChain 的文档压缩器。

    LangChain 把重排归类为"压缩"：输入一批文档，输出更少但更相关的一批。
    实现这个接口之后，它可以直接塞进 ContextualCompressionRetriever，
    也可以像本项目这样单独调用。
    """

    # BaseDocumentCompressor 继承自 pydantic 模型，字段要显式声明
    config: AiModelConfig
    top_n: int = 3

    # AiModelConfig 是 Tortoise 模型，不是 pydantic 类型，要允许任意类型
    model_config = {"arbitrary_types_allowed": True}

    def compress_documents(
        self,
        documents: Sequence[Document],
        query: str,
        callbacks: Callbacks = None,
    ) -> Sequence[Document]:
        """同步接口。本项目全链路异步，只走下面的异步版本。"""
        raise NotImplementedError("请使用 acompress_documents，本项目的调用链路是异步的")

    async def acompress_documents(
        self,
        documents: Sequence[Document],
        query: str,
        callbacks: Callbacks = None,
    ) -> Sequence[Document]:
        """把文档按与问题的相关性重新排序，只保留前 top_n 条。"""
        if not documents:
            return []
        texts = [doc.page_content for doc in documents]
        results = await model_factory.rerank(self.config, query, texts, self.top_n)
        if not results:
            raise CustomException("重排接口没有返回结果，请检查重排模型配置")
        ranked = []
        for item in results:
            index = item.get("index")
            # 接口返回的 index 指向传进去的 texts，越界说明返回结构不符合预期
            if index is None or index < 0 or index >= len(documents):
                continue
            source = documents[index]
            metadata = dict(source.metadata)
            # 把重排给的相关性得分写进元数据，覆盖粗筛阶段的分数
            metadata["rerank_score"] = item.get("relevance_score")
            ranked.append(Document(page_content=source.page_content, metadata=metadata))
        return ranked


def to_documents(results: list[dict]) -> list[Document]:
    """把检索结果转成 LangChain 的 Document。

    page_content 放片段正文，其余字段全部塞进 metadata，
    重排之后还要靠 metadata 里的 chunk_id 找回原来那条结果。
    """
    documents = []
    for item in results:
        metadata = {key: value for key, value in item.items() if key != "content"}
        documents.append(Document(page_content=item["content"], metadata=metadata))
    return documents


def from_documents(documents: Sequence[Document]) -> list[dict]:
    """把重排后的 Document 转回本项目的结果字典。"""
    results = []
    for doc in documents:
        item = dict(doc.metadata)
        item["content"] = doc.page_content
        score = item.pop("rerank_score", None)
        if score is not None:
            # 重排分才是最终排序依据，覆盖掉粗筛阶段的分数
            item["score"] = round(float(score), 6)
        # 保留粗筛阶段的来源，再标上经过了重排
        previous = item.get("source", "")
        item["source"] = f"{previous}→重排" if previous else "重排"
        results.append(item)
    return results
