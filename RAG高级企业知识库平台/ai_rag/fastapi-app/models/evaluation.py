from tortoise import fields
from tortoise.models import Model


class EvalDataset(Model):
    """评测集表。一组用例构成一个评测集，一次评测跑完整个集。"""

    id = fields.IntField(primary_key=True)
    name = fields.CharField(max_length=255)
    kb_id = fields.IntField(null=True)
    description = fields.CharField(max_length=1000, null=True)
    # 冗余统计列，用例增删时重算
    case_count = fields.IntField(default=0)
    create_time = fields.DatetimeField(auto_now_add=True)
    update_time = fields.DatetimeField(auto_now=True)

    class Meta:
        table = "eval_dataset"


class EvalCase(Model):
    """评测用例表。

    第 26 章说过：四个指标里只有 Context Recall 需要标准答案，
    所以 question 和 ground_truth 是一条用例的最低要求。
    """

    id = fields.IntField(primary_key=True)
    dataset_id = fields.IntField()
    question = fields.CharField(max_length=1000)
    ground_truth = fields.TextField(null=True)
    # 标准答案对应的片段 ID，逗号分隔。有了它 Context Recall 可以不靠模型直接算
    reference_chunk_ids = fields.CharField(max_length=500, null=True)
    # 手工录入 / 文档生成 / 反馈沉淀
    source = fields.CharField(max_length=30, default="手工录入")
    enabled = fields.CharField(max_length=10, default="是")
    remark = fields.CharField(max_length=500, null=True)
    create_time = fields.DatetimeField(auto_now_add=True)
    update_time = fields.DatetimeField(auto_now=True)

    class Meta:
        table = "eval_case"


class EvalTask(Model):
    """评测任务表。一次批量评测就是一条任务记录。"""

    id = fields.IntField(primary_key=True)
    task_no = fields.CharField(max_length=64, unique=True)
    dataset_id = fields.IntField()
    app_id = fields.IntField(null=True)
    retrieval_strategy_id = fields.IntField(null=True)
    # 策略参数快照。报告放一周后再看，要知道当时开了哪些开关，对比才有意义
    strategy_snapshot = fields.TextField(null=True)
    judge_model_id = fields.IntField(null=True)
    task_status = fields.CharField(max_length=30, default="等待中")
    total_count = fields.IntField(default=0)
    success_count = fields.IntField(default=0)
    fail_count = fields.IntField(default=0)
    error_message = fields.CharField(max_length=500, null=True)
    start_time = fields.DatetimeField(null=True)
    end_time = fields.DatetimeField(null=True)
    cost_millis = fields.BigIntField(null=True)
    create_user_id = fields.IntField(null=True)
    create_time = fields.DatetimeField(auto_now_add=True)

    class Meta:
        table = "eval_task"


class EvalCaseResult(Model):
    """单条用例的评测结果。四个指标各一列。"""

    id = fields.IntField(primary_key=True)
    task_id = fields.IntField()
    case_id = fields.IntField()
    answer = fields.TextField(null=True)
    retrieved_chunk_ids = fields.CharField(max_length=500, null=True)
    # 第 26 章那四个指标，取值 0 到 1
    faithfulness = fields.DecimalField(max_digits=5, decimal_places=4, null=True)
    answer_relevancy = fields.DecimalField(max_digits=5, decimal_places=4, null=True)
    context_precision = fields.DecimalField(max_digits=5, decimal_places=4, null=True)
    context_recall = fields.DecimalField(max_digits=5, decimal_places=4, null=True)
    avg_score = fields.DecimalField(max_digits=5, decimal_places=4, null=True)
    error_message = fields.CharField(max_length=500, null=True)
    cost_millis = fields.BigIntField(null=True)
    create_time = fields.DatetimeField(auto_now_add=True)

    class Meta:
        table = "eval_case_result"


class EvalReport(Model):
    """评测报告表。一次任务跑完汇总成一条报告，供第 29 章的看板横向对比。"""

    id = fields.IntField(primary_key=True)
    report_no = fields.CharField(max_length=64, unique=True)
    task_id = fields.IntField()
    strategy_name = fields.CharField(max_length=255, null=True)
    strategy_snapshot = fields.TextField(null=True)
    case_count = fields.IntField(default=0)
    faithfulness_avg = fields.DecimalField(max_digits=5, decimal_places=4, null=True)
    answer_relevancy_avg = fields.DecimalField(max_digits=5, decimal_places=4, null=True)
    context_precision_avg = fields.DecimalField(max_digits=5, decimal_places=4, null=True)
    context_recall_avg = fields.DecimalField(max_digits=5, decimal_places=4, null=True)
    overall_score = fields.DecimalField(max_digits=5, decimal_places=4, null=True)
    conclusion = fields.TextField(null=True)
    create_time = fields.DatetimeField(auto_now_add=True)

    class Meta:
        table = "eval_report"
