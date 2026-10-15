"""查询改写测试。

真实改写要调对话模型，这里把模型工厂换成假实现，
验证的是本项目自己写的那部分：多行解析、原问题保留、条数上限、空返回兜底。
"""

import pytest

from ai import model_factory, prompt_loader, query_rewriter


class FakeReply:
    def __init__(self, content: str):
        self.content = content


class FakeModel:
    def __init__(self, content: str):
        self._content = content
        # 记录实际发给模型的 Prompt，用来断言模板被正确渲染
        self.last_prompt = None

    async def ainvoke(self, prompt):
        self.last_prompt = prompt
        return FakeReply(self._content)


@pytest.fixture()
def fake_chat(monkeypatch):
    """把取配置和构造模型两步都换成假实现，返回那个假模型以便断言。"""
    holder = {}

    async def fake_load_enabled(model_type):
        return object()

    def fake_build(config, temperature=0.0):
        return holder["model"]

    monkeypatch.setattr(model_factory, "load_enabled", fake_load_enabled)
    monkeypatch.setattr(model_factory, "build_chat_model", fake_build)

    def setup(content):
        holder["model"] = FakeModel(content)
        return holder["model"]

    return setup


def test_split_lines_strips_numbering():
    """模型返回带编号的多行文本时，编号和项目符号被清掉。"""
    lines = query_rewriter._split_lines("1. 产品是否支持私有化部署\n- 能否部署在自有服务器\n\n2、是否提供本地安装")
    assert lines == ["产品是否支持私有化部署", "能否部署在自有服务器", "是否提供本地安装"]


async def test_multi_query_keeps_original_question(db, fake_chat):
    """多查询扩展的结果里第一条永远是原问题。"""
    fake_chat("产品是否支持私有化部署\n能否部署在客户自有服务器\n是否提供本地化安装方案")

    queries = await query_rewriter.multi_query("能装在我们自己机房吗", 3)

    assert queries[0] == "能装在我们自己机房吗"
    assert "产品是否支持私有化部署" in queries
    # 原问题加上 count 条改写，总数不超过 count + 1
    assert len(queries) == 4


async def test_multi_query_dedupes_repeated_question(db, fake_chat):
    """模型把原问题也重复一遍时去重。"""
    fake_chat("能装在我们自己机房吗\n产品是否支持私有化部署")

    queries = await query_rewriter.multi_query("能装在我们自己机房吗", 3)

    assert queries.count("能装在我们自己机房吗") == 1
    assert len(queries) == 2


async def test_multi_query_count_is_capped(db, fake_chat):
    """扩展条数有上限，防止一次问答把检索次数放大到失控。"""
    model = fake_chat("\n".join(f"改写问题{index}" for index in range(1, 20)))

    queries = await query_rewriter.multi_query("原问题", 99)

    assert len(queries) == query_rewriter.MAX_QUERY_COUNT + 1
    # 渲染进 Prompt 的条数也被截到上限
    assert str(query_rewriter.MAX_QUERY_COUNT) in model.last_prompt


async def test_resolve_coreference_without_history_skips_model():
    """没有对话历史时原样返回，不做无谓的模型调用。"""
    assert await query_rewriter.resolve_coreference("那超期了呢", []) == "那超期了呢"


async def test_resolve_coreference_rewrites_question(db, fake_chat):
    """有历史时把指代补全成独立完整的问题。"""
    model = fake_chat("GTE-3000 超过 24 个月保修期后如何处理")

    history = [
        {"role": "user", "content": "GTE-3000 的保修期是多久？"},
        {"role": "assistant", "content": "24 个月。"},
    ]
    rewritten = await query_rewriter.resolve_coreference("那超期了呢", history)

    assert rewritten == "GTE-3000 超过 24 个月保修期后如何处理"
    # 历史按"用户/助手"的形式拼进 Prompt
    assert "用户：GTE-3000 的保修期是多久？" in model.last_prompt
    assert "助手：24 个月。" in model.last_prompt


async def test_resolve_coreference_falls_back_on_empty_reply(db, fake_chat):
    """模型返回空内容时退回原问题，不让检索拿着空字符串去跑。"""
    fake_chat("   ")

    history = [{"role": "user", "content": "上一句"}]
    assert await query_rewriter.resolve_coreference("那它呢", history) == "那它呢"


async def test_hyde_prepends_original_question(db, fake_chat):
    """HyDE 把原问题和假答案拼在一起，既保留意图又带上文档腔。"""
    fake_chat("本产品支持私有化部署，可以部署在客户自有的服务器环境中。")

    result = await query_rewriter.hyde("能装在我们自己机房吗")

    assert result.startswith("能装在我们自己机房吗")
    assert "私有化部署" in result


async def test_hyde_falls_back_on_empty_reply(db, fake_chat):
    """假答案为空时退回原问题。"""
    fake_chat("")
    assert await query_rewriter.hyde("原问题") == "原问题"


async def test_rewrite_returns_list_for_every_type(db, fake_chat):
    """三种改写方式返回值统一是列表，调用方不用写三套分支。"""
    fake_chat("改写结果")

    assert isinstance(await query_rewriter.rewrite("问题", query_rewriter.MULTI_QUERY, 2), list)
    assert isinstance(await query_rewriter.rewrite("问题", query_rewriter.HYDE, 2), list)
    assert isinstance(
        await query_rewriter.rewrite("问题", query_rewriter.COREFERENCE, 2, [{"role": "user", "content": "上一句"}]),
        list,
    )


async def test_rewrite_without_type_returns_original(db, fake_chat):
    """没配改写方式时按原问题检索。"""
    fake_chat("不该被用到")
    assert await query_rewriter.rewrite("原问题", None, 3) == ["原问题"]


def test_rewrite_prompt_templates_exist(client, admin_headers):
    """三种改写方式各自依赖的 Prompt 模板都在初始化数据里。"""
    body = client.get("/promptTemplate/selectAll", headers=admin_headers).json()
    codes = {item["code"] for item in body["data"]}
    assert {"QUERY_REWRITE", "COREFERENCE_RESOLVE", "HYDE_ANSWER"} <= codes


async def test_hyde_template_renders(db):
    """HyDE 模板只需要 question 一个变量。"""
    content = await prompt_loader.render("HYDE_ANSWER", question="保修期多久")
    assert "保修期多久" in content
