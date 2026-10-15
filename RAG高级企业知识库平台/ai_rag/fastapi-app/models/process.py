from tortoise import fields
from tortoise.models import Model


class DocumentProcessTask(Model):
    """文档处理任务表。

    解析、切分、向量化都是耗时操作，接口不能一直等着，
    所以每次触发都先建一条任务记录，页面靠它看进度和失败原因。
    """

    id = fields.IntField(primary_key=True)
    kb_id = fields.IntField()
    # 整库重建时为空，单篇处理时指向具体文档
    document_id = fields.IntField(null=True)
    task_type = fields.CharField(max_length=30)
    task_status = fields.CharField(max_length=30, default="等待中")
    total_count = fields.IntField(default=0)
    success_count = fields.IntField(default=0)
    fail_count = fields.IntField(default=0)
    # 写库前要截断到 500 字，第三方库抛出的异常信息经常上千字
    error_message = fields.CharField(max_length=500, null=True)
    start_time = fields.DatetimeField(null=True)
    end_time = fields.DatetimeField(null=True)
    cost_millis = fields.BigIntField(null=True)
    create_time = fields.DatetimeField(auto_now_add=True)

    class Meta:
        table = "document_process_task"


class RetrievalDebugRecord(Model):
    """召回调试记录表。

    调试台每做一次策略对比就存一条，把当时各套策略召回了什么原样留下来。
    调完参数过几天回头看，能对照出改动前后的差别。
    """

    id = fields.IntField(primary_key=True)
    kb_id = fields.IntField()
    query = fields.CharField(max_length=1000)
    # 参与对比的策略 ID，逗号分隔
    strategy_ids = fields.CharField(max_length=255, null=True)
    # 各策略召回结果的完整快照 JSON，含片段、分数、各阶段耗时
    result_snapshot = fields.TextField(null=True)
    cost_millis = fields.BigIntField(null=True)
    create_user_id = fields.IntField(null=True)
    create_time = fields.DatetimeField(auto_now_add=True)

    class Meta:
        table = "retrieval_debug_record"


class AgentRun(Model):
    """Agent 运行记录表。

    一次 Agentic 问答就是一条运行记录。跑了几轮、检索了几次、
    最后是正常回答还是走了兜底，全部记在这里。
    """

    id = fields.IntField(primary_key=True)
    run_no = fields.CharField(max_length=64, unique=True)
    app_id = fields.IntField(null=True)
    session_id = fields.IntField(null=True)
    message_id = fields.IntField(null=True)
    user_id = fields.IntField(null=True)
    run_type = fields.CharField(max_length=100, null=True)
    run_status = fields.CharField(max_length=50, default="运行中")
    current_step = fields.IntField(default=0)
    total_step = fields.IntField(default=0)
    # 实际检索次数。执行完要反查它，为 0 说明这次运行根本没检索过
    retrieve_count = fields.IntField(default=0)
    rewrite_count = fields.IntField(default=0)
    input_snapshot = fields.TextField(null=True)
    output_summary = fields.TextField(null=True)
    error_message = fields.CharField(max_length=500, null=True)
    start_time = fields.DatetimeField(null=True)
    end_time = fields.DatetimeField(null=True)
    cost_millis = fields.BigIntField(null=True)
    create_time = fields.DatetimeField(auto_now_add=True)

    class Meta:
        table = "agent_run"


class AgentStep(Model):
    """Agent 执行步骤表。

    状态图里每个节点执行一次就记一条。node_name 是图里的节点名，
    step_name 是给人看的中文步骤名，第 23 章的时间线按 step_index 排序展示。
    """

    id = fields.IntField(primary_key=True)
    run_id = fields.IntField()
    step_index = fields.IntField(default=0)
    step_name = fields.CharField(max_length=255, null=True)
    node_name = fields.CharField(max_length=100, null=True)
    tool_code = fields.CharField(max_length=100, null=True)
    request_params = fields.TextField(null=True)
    response_result = fields.TextField(null=True)
    step_status = fields.CharField(max_length=50, default="运行中")
    error_message = fields.CharField(max_length=500, null=True)
    start_time = fields.DatetimeField(null=True)
    end_time = fields.DatetimeField(null=True)
    cost_millis = fields.BigIntField(null=True)
    create_time = fields.DatetimeField(auto_now_add=True)

    class Meta:
        table = "agent_step"


class ToolCallLog(Model):
    """工具调用日志表。

    Agent 每调一次工具就记一条，成功失败都记。
    页面上按工具编码统计成功率，能看出哪个工具最常被调、哪个最容易失败。
    """

    id = fields.IntField(primary_key=True)
    run_id = fields.IntField(null=True)
    step_id = fields.IntField(null=True)
    tool_code = fields.CharField(max_length=100)
    tool_name = fields.CharField(max_length=255, null=True)
    request_params = fields.TextField(null=True)
    response_result = fields.TextField(null=True)
    call_status = fields.CharField(max_length=20, default="成功")
    error_message = fields.CharField(max_length=500, null=True)
    cost_millis = fields.BigIntField(null=True)
    create_time = fields.DatetimeField(auto_now_add=True)

    class Meta:
        table = "tool_call_log"
