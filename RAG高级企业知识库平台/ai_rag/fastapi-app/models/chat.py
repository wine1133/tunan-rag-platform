from tortoise import fields
from tortoise.models import Model


class QaApp(Model):
    """问答应用表。

    一个应用 = 一组知识库 + 一套检索策略 + 一个对话模型 + 一段系统 Prompt。
    管理员配好之后，用户端就能对着它提问。
    """

    id = fields.IntField(primary_key=True)
    name = fields.CharField(max_length=255)
    # 分享链接用的编码，用户端按它找到这个应用
    app_code = fields.CharField(max_length=64, unique=True)
    description = fields.CharField(max_length=1000, null=True)
    avatar = fields.CharField(max_length=500, null=True)
    chat_model_id = fields.IntField(null=True)
    retrieval_strategy_id = fields.IntField(null=True)
    prompt_code = fields.CharField(max_length=100, null=True)
    # 关掉走第 15-19 章的直线链路，打开走第 22 章的 LangGraph 状态图
    agent_enabled = fields.CharField(max_length=10, default="否")
    # 带进模型的历史消息条数，太多会撑爆上下文也会拖慢速度
    max_history = fields.IntField(default=6)
    # 检索不到资料时的兜底话术
    empty_answer = fields.CharField(max_length=500, null=True)
    share_enabled = fields.CharField(max_length=10, default="否")
    status = fields.CharField(max_length=20, default="正常")
    create_user_id = fields.IntField(null=True)
    create_time = fields.DatetimeField(auto_now_add=True)
    update_time = fields.DatetimeField(auto_now=True)

    class Meta:
        table = "qa_app"


class QaAppKb(Model):
    """问答应用与知识库的关联表。一个应用可以挂多个知识库。"""

    id = fields.IntField(primary_key=True)
    app_id = fields.IntField()
    kb_id = fields.IntField()
    create_time = fields.DatetimeField(auto_now_add=True)

    class Meta:
        table = "qa_app_kb"
        unique_together = ("app_id", "kb_id")


class ChatSession(Model):
    """对话会话表。一次连续的多轮对话是一个会话。"""

    id = fields.IntField(primary_key=True)
    session_no = fields.CharField(max_length=64, unique=True)
    app_id = fields.IntField()
    # 分享页匿名访问时为空
    user_id = fields.IntField(null=True)
    # 取首条提问做标题，列表页展示
    title = fields.CharField(max_length=255, null=True)
    message_count = fields.IntField(default=0)
    source = fields.CharField(max_length=30, default="管理端")
    create_time = fields.DatetimeField(auto_now_add=True)
    update_time = fields.DatetimeField(auto_now=True)

    class Meta:
        table = "chat_session"


class ChatMessage(Model):
    """对话消息表。用户的每次提问和助手的每次回答各一条。"""

    id = fields.IntField(primary_key=True)
    session_id = fields.IntField()
    # user 提问 / assistant 回答
    role = fields.CharField(max_length=20)
    content = fields.TextField(null=True)
    # 实际拿去检索的问题，开了改写或指代消解时和原问题不同，便于排查召回
    rewritten_query = fields.CharField(max_length=1000, null=True)
    # 这次问答用的检索策略快照，事后能知道当时开了哪些开关
    strategy_snapshot = fields.TextField(null=True)
    agent_run_id = fields.IntField(null=True)
    prompt_tokens = fields.IntField(null=True)
    completion_tokens = fields.IntField(null=True)
    # length 表示输出被截断了
    finish_reason = fields.CharField(max_length=50, null=True)
    error_message = fields.CharField(max_length=500, null=True)
    cost_millis = fields.BigIntField(null=True)
    create_time = fields.DatetimeField(auto_now_add=True)

    class Meta:
        table = "chat_message"


class MessageReference(Model):
    """消息引用来源表。

    内容存的是快照，因为片段后续可能被修改或删除，
    但用户当时看到的答案是基于那一版内容生成的。
    """

    id = fields.IntField(primary_key=True)
    message_id = fields.IntField()
    chunk_id = fields.IntField()
    document_id = fields.IntField(null=True)
    chunk_content = fields.TextField(null=True)
    score = fields.DecimalField(max_digits=10, decimal_places=6, null=True)
    rank_no = fields.IntField(null=True)
    retrieval_source = fields.CharField(max_length=30, null=True)
    create_time = fields.DatetimeField(auto_now_add=True)

    class Meta:
        table = "message_reference"


class MessageFeedback(Model):
    """消息反馈表。点踩的问题会沉淀成第 27 章的评测用例。"""

    id = fields.IntField(primary_key=True)
    message_id = fields.IntField()
    user_id = fields.IntField(null=True)
    feedback_type = fields.CharField(max_length=20)
    reason = fields.CharField(max_length=500, null=True)
    # 是否已经转成评测用例，避免同一条反复沉淀
    converted = fields.CharField(max_length=10, default="否")
    create_time = fields.DatetimeField(auto_now_add=True)

    class Meta:
        table = "message_feedback"
