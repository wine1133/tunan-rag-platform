"""Tortoise 模型包。

原脚手架把所有模型放在单个 models.py 里，本项目表数量多，改为按业务域拆分文件：

    user.py       用户与系统底座
    knowledge.py  知识库、文档、片段、检索策略
    config.py     模型配置、Prompt 模板、工具注册
    process.py    文档处理任务、调试记录、工具调用日志

后续章节引入新表时按域放进对应文件，并在本文件中导入，Tortoise 才能扫描到。
"""

from models.chat import (
    ChatMessage,
    ChatSession,
    MessageFeedback,
    MessageReference,
    QaApp,
    QaAppKb,
)
from models.config import AiModelConfig, FunctionTool, PromptTemplate
from models.evaluation import (
    EvalCase,
    EvalCaseResult,
    EvalDataset,
    EvalReport,
    EvalTask,
)
from models.knowledge import (
    ChunkStrategy,
    KnowledgeBase,
    KnowledgeChunk,
    KnowledgeDocument,
    RetrievalStrategy,
)
from models.process import (
    AgentRun,
    AgentStep,
    DocumentProcessTask,
    RetrievalDebugRecord,
    ToolCallLog,
)
from models.user import User

__all__ = [
    "User",
    "KnowledgeBase",
    "KnowledgeDocument",
    "ChunkStrategy",
    "KnowledgeChunk",
    "RetrievalStrategy",
    "DocumentProcessTask",
    "AgentRun",
    "AgentStep",
    "RetrievalDebugRecord",
    "ToolCallLog",
    "AiModelConfig",
    "PromptTemplate",
    "FunctionTool",
    "QaApp",
    "QaAppKb",
    "ChatSession",
    "ChatMessage",
    "MessageReference",
    "MessageFeedback",
    "EvalDataset",
    "EvalCase",
    "EvalTask",
    "EvalCaseResult",
    "EvalReport",
]
