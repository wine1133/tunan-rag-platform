"""AI 能力层。

本项目所有与大模型、检索、Agent、评测相关的代码都放在这个包里，
不允许散落到 api/ 或 service/ 中，目的是让 AI 链路能被单独阅读和替换。

按章节逐步引入的模块规划：

    model_factory.py   从 ai_model_config 表读配置，构建对话/向量/重排模型
    prompt_loader.py   从 prompt_template 表读 Prompt，做存在性与启用校验
    loader.py          文档加载与解析（PDF 表格、扫描件 OCR）
    splitter.py        文本切分策略（递归 / 语义 / 父子）
    retriever.py       向量检索、BM25、RRF 融合、重排、Query 改写
    graph.py           LangGraph 编排的 Agentic RAG 状态图
    tools.py           Function Calling 工具实现，与 function_tool 表对应
    evaluator.py       RAGAS 评测执行与指标汇总
"""
