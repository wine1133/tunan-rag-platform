from tortoise import fields
from tortoise.models import Model


class User(Model):
    """用户表。管理员和普通用户统一存这里，通过 role 字段区分。"""

    id = fields.IntField(primary_key=True)
    # unique=True 对应表上的唯一索引 uk_user_username
    username = fields.CharField(max_length=100, unique=True)
    password = fields.CharField(max_length=255)
    name = fields.CharField(max_length=100)
    # null=True 表示这些字段允许为空，注册时不填，后面在个人资料页补
    avatar = fields.CharField(max_length=500, null=True)
    # default 只在代码里 create 且没传该字段时生效
    role = fields.CharField(max_length=30, default="USER")
    phone = fields.CharField(max_length=30, null=True)
    email = fields.CharField(max_length=100, null=True)
    status = fields.CharField(max_length=20, default="NORMAL")
    # auto_now_add 在插入时自动填当前时间，auto_now 在每次更新时自动刷新
    create_time = fields.DatetimeField(auto_now_add=True)
    update_time = fields.DatetimeField(auto_now=True)

    class Meta:
        # 指定映射到数据库里的表名，不指定的话 Tortoise 会用类名小写
        table = "user"
