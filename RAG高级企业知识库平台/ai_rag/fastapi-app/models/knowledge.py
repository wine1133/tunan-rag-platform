from tortoise import fields
from tortoise.models import Model


class KnowledgeBase(Model):
    """知识库表。企业资料的一级分类，一个知识库下挂多篇文档。"""

    id = fields.IntField(primary_key=True)
    name = fields.CharField(max_length=255)
    description = fields.CharField(max_length=1000, null=True)
    # 绑定的向量模型配置 ID，建库后锁定。库里已有的向量是用这个模型生成的，
    # 换模型必须全量重新向量化，否则新问题和旧向量不在同一语义空间
    embedding_model_id = fields.IntField(null=True)
    # 默认切分策略 ID，上传文档时按它决定怎么切片
    chunk_strategy_id = fields.IntField(null=True)
    # 文档数和片段数是冗余统计列，由文档和片段的增删操作维护，
    # 列表页直接读这两个数，不用每次现算
    document_count = fields.IntField(default=0)
    chunk_count = fields.IntField(default=0)
    status = fields.CharField(max_length=20, default="正常")
    create_user_id = fields.IntField(null=True)
    create_time = fields.DatetimeField(auto_now_add=True)
    update_time = fields.DatetimeField(auto_now=True)

    class Meta:
        table = "knowledge_base"


class KnowledgeDocument(Model):
    """知识文档表。用户上传的原始文件，一篇文档属于一个知识库。"""

    id = fields.IntField(primary_key=True)
    # 所属知识库 ID，删除知识库前要求先删完它下面的文档
    kb_id = fields.IntField()
    name = fields.CharField(max_length=255)
    # 磁盘文件名，配合 /files/download/{file_name} 能取到原始文件
    file_name = fields.CharField(max_length=500, null=True)
    # 文件访问地址，由 /files/upload 返回后回填
    file_url = fields.CharField(max_length=500, null=True)
    # 文件类型由文件后缀推断，决定第 07 章用哪个解析器
    file_type = fields.CharField(max_length=30, null=True)
    file_size = fields.BigIntField(default=0)
    # 解析状态，第 07 章解析文档时流转
    parse_status = fields.CharField(max_length=30, default="待解析")
    parse_error = fields.CharField(max_length=500, null=True)
    # 解析出的纯文本，第 09 章按它切分片段
    parsed_text = fields.TextField(null=True)
    # 解析时是否抽到过表格、是否走过 OCR，列表页用来标记这篇文档的复杂度
    has_table = fields.CharField(max_length=10, default="否")
    has_ocr = fields.CharField(max_length=10, default="否")
    char_count = fields.IntField(default=0)
    chunk_count = fields.IntField(default=0)
    # 向量化状态，第 12 章写入向量时流转
    vector_status = fields.CharField(max_length=30, default="待向量化")
    upload_user_id = fields.IntField(null=True)
    create_time = fields.DatetimeField(auto_now_add=True)
    update_time = fields.DatetimeField(auto_now=True)

    class Meta:
        table = "knowledge_document"


class ChunkStrategy(Model):
    """切分策略表。一行就是一套切分参数，知识库切分文档时按它执行。"""

    id = fields.IntField(primary_key=True)
    name = fields.CharField(max_length=255)
    # 递归分块：按分隔符逐级切；父子分块：先切大块再切小块
    strategy_type = fields.CharField(max_length=30)
    chunk_size = fields.IntField(default=500)
    chunk_overlap = fields.IntField(default=50)
    # 仅父子分块使用，父块长度必须大于子块长度
    parent_chunk_size = fields.IntField(null=True)
    # 分隔符清单，逗号分隔，按顺序逐级尝试
    separators = fields.CharField(max_length=255, null=True)
    # 知识库没有指定策略时用默认策略，全表只允许一条为"是"
    is_default = fields.CharField(max_length=10, default="否")
    remark = fields.CharField(max_length=500, null=True)
    create_time = fields.DatetimeField(auto_now_add=True)
    update_time = fields.DatetimeField(auto_now=True)

    class Meta:
        table = "chunk_strategy"


class RetrievalStrategy(Model):
    """检索策略表。

    一行就是一整套检索参数。第 19 章的调试台拿多行做并排对比，
    第 24 章的问答应用引用其中一行作为自己的检索方式。
    """

    id = fields.IntField(primary_key=True)
    name = fields.CharField(max_length=255)
    # 向量检索：语义匹配，认不出精确字符
    vector_enabled = fields.CharField(max_length=10, default="是")
    vector_top_k = fields.IntField(default=5)
    # BM25 关键词检索：字符匹配，听不懂同义表达
    bm25_enabled = fields.CharField(max_length=10, default="否")
    bm25_top_k = fields.IntField(default=5)
    # RRF 融合常数，越小越偏向各路头部结果
    rrf_k = fields.IntField(default=60)
    # 重排在第 16 章接入
    rerank_enabled = fields.CharField(max_length=10, default="否")
    rerank_model_id = fields.IntField(null=True)
    rerank_top_n = fields.IntField(default=3)
    # 查询改写在第 17 章接入
    query_rewrite_enabled = fields.CharField(max_length=10, default="否")
    rewrite_type = fields.CharField(max_length=30, null=True)
    multi_query_count = fields.IntField(default=3)
    # 父块回填在第 18 章接入
    parent_recall_enabled = fields.CharField(max_length=10, default="否")
    # 阈值按分数量纲分开配。检索管线末端的分数可能是余弦相似度，也可能是重排相关分，
    # 两者取值范围差一个数量级，同一个数字放在两边含义完全不同，所以拆成两个字段。
    # 向量单路召回时最终分数是余弦相似度，取值 0 到 1，低于阈值判定为没有答案
    vector_score_threshold = fields.DecimalField(max_digits=5, decimal_places=3, null=True)
    # 开了重排时最终分数是重排模型给的相关分，量纲和余弦相似度不同，单独配一个门槛
    rerank_score_threshold = fields.DecimalField(max_digits=5, decimal_places=3, null=True)
    metadata_filter = fields.CharField(max_length=1000, null=True)
    is_default = fields.CharField(max_length=10, default="否")
    remark = fields.CharField(max_length=500, null=True)
    create_time = fields.DatetimeField(auto_now_add=True)
    update_time = fields.DatetimeField(auto_now=True)

    class Meta:
        table = "retrieval_strategy"


class KnowledgeChunk(Model):
    """知识片段表。文档切分后的最小检索单位。"""

    id = fields.IntField(primary_key=True)
    kb_id = fields.IntField()
    document_id = fields.IntField()
    # 父子分块时子块指向父块，其余情况为空
    parent_id = fields.IntField(null=True)
    chunk_index = fields.IntField(default=0)
    # 普通块参与检索也参与生成；子块只参与检索，父块只在命中子块后回填
    chunk_type = fields.CharField(max_length=20, default="普通块")
    content = fields.TextField()
    char_count = fields.IntField(default=0)
    # 从解析文本的【第 N 页】标记里提取，问答时用来告诉用户答案在第几页
    page_no = fields.IntField(null=True)
    title_path = fields.CharField(max_length=500, null=True)
    extra_meta = fields.TextField(null=True)
    vector_status = fields.CharField(max_length=30, default="待向量化")
    create_time = fields.DatetimeField(auto_now_add=True)
    update_time = fields.DatetimeField(auto_now=True)

    class Meta:
        table = "knowledge_chunk"
