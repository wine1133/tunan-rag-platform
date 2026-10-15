from tortoise import fields
from tortoise.models import Model


class AiModelConfig(Model):
    """AI 模型配置表。

    本项目三类模型全部用阿里云百炼，但接口协议不一样：
    对话模型和向量模型走 OpenAI 兼容模式，重排模型只有 DashScope 原生接口。
    protocol 字段决定代码走哪条调用路径。
    """

    id = fields.IntField(primary_key=True)
    name = fields.CharField(max_length=255)
    # 对话模型 / 向量模型 / 重排模型
    model_type = fields.CharField(max_length=50)
    provider = fields.CharField(max_length=100, null=True)
    # OpenAI兼容 / DashScope原生
    protocol = fields.CharField(max_length=50, default="OpenAI兼容")
    base_url = fields.CharField(max_length=500, null=True)
    api_key = fields.CharField(max_length=500, null=True)
    model_name = fields.CharField(max_length=255, null=True)
    # 仅向量模型需要，必须和 PGVector 建表时的维度一致
    dimension = fields.IntField(null=True)
    # 同一类型下只允许一条启用，代码按"类型 + 启用"取配置
    enabled = fields.CharField(max_length=10, default="是")
    remark = fields.CharField(max_length=500, null=True)
    create_time = fields.DatetimeField(auto_now_add=True)
    update_time = fields.DatetimeField(auto_now=True)

    class Meta:
        table = "ai_model_config"


class PromptTemplate(Model):
    """Prompt 模板表。

    所有发给模型的提示词都存在这里，改 Prompt 不用改代码也不用重启，
    代码按 code 取模板，取不到或被停用时直接报错，不用兜底的硬编码 Prompt。
    """

    id = fields.IntField(primary_key=True)
    # 模板编码，代码里按它取模板，全表唯一
    code = fields.CharField(max_length=100, unique=True)
    name = fields.CharField(max_length=255)
    scene = fields.CharField(max_length=100, null=True)
    # 模板内容，用大括号占位变量，例如 {context}、{question}
    content = fields.TextField()
    # 变量清单，逗号分隔，页面上展示给管理员看这个模板需要哪些变量
    variables = fields.CharField(max_length=500, null=True)
    enabled = fields.CharField(max_length=10, default="是")
    remark = fields.CharField(max_length=500, null=True)
    create_time = fields.DatetimeField(auto_now_add=True)
    update_time = fields.DatetimeField(auto_now=True)

    class Meta:
        table = "prompt_template"


class FunctionTool(Model):
    """Function 工具注册表。

    Agent 能用哪些工具由这张表决定，不是由代码里注册了多少个决定。
    enabled 是真开关：停用之后，Agent 下一次执行就真的拿不到这个工具。
    """

    id = fields.IntField(primary_key=True)
    # 必须和 ai/tools.py 里实现函数的名字一致，对不上就是配了个用不了的工具
    tool_code = fields.CharField(max_length=100, unique=True)
    tool_name = fields.CharField(max_length=255)
    # 这段描述会原样发给模型，模型靠它判断什么时候该调这个工具
    description = fields.CharField(max_length=1000, null=True)
    input_schema = fields.TextField(null=True)
    enabled = fields.CharField(max_length=10, default="是")
    sort = fields.IntField(default=0)
    create_time = fields.DatetimeField(auto_now_add=True)
    update_time = fields.DatetimeField(auto_now=True)

    class Meta:
        table = "function_tool"
