# 业务库：MySQL，保存用户、知识库、对话、评测等全部结构化数据
TORTOISE_ORM = {
    "connections": {
        "default": {
            "engine": "tortoise.backends.mysql",
            "credentials": {
                "host": "localhost",
                "port": 3306,
                # 数据库名称，和 ai_rag.sql 里建的库同名
                "database": "ai_rag",
                "user": "root",
                # 数据库密码，按本机 MySQL 实际密码改（本机 MySQL80 的 root 密码为 root）
                "password": "root",
                "minsize": 1,
                "maxsize": 10,
                "charset": "utf8mb4",
                "echo": True
            }
        },
    },
    "apps": {
      "models": {
          # 指向 models 包，Tortoise 会扫描包里导出的所有 Model 子类
          "models": ["models"],
          "default_connection": "default",
      }
    },
    # use_tz 开着时，auto_now_add / auto_now 生成的是 UTC 时间，
    # 而下面 timezone 又配的是东八区，两边对不上，
    # create_time 会比实际早 8 小时。关掉之后 Tortoise 统一按 timezone 生成
    "use_tz": False,
    "timezone": "Asia/Shanghai"
}

# 向量库：PostgreSQL + PGVector，只保存知识片段的向量和检索用的元数据
# 业务数据仍然在上面的 MySQL 里，两个库通过 knowledge_chunk.id 关联
PGVECTOR = {
    "host": "localhost",
    "port": 5432,
    "database": "ai_rag_vector",
    "user": "postgres",
    "password": "123456",
    # 向量维度，必须与 ai_model_config 中启用的向量模型输出维度一致
    # 百炼 text-embedding-v4 默认输出 1024 维
    "dimension": 1024,
}

JWT_SECRET = "ai-rag-advanced-knowledge-platform-jwt-secret"
JWT_ALGORITHM = "HS256"
JWT_EXPIRE_HOURS = 24
