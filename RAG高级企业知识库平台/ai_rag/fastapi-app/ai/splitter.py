"""文本切分。

把第 07 章解析出来的整篇文本切成小片段。片段是 RAG 里最小的检索单位，
切得太大，一个片段里混了好几个主题，检索命中了也没法精准回答；
切得太小，一句话被拦腰截断，模型看不到完整语义。

本模块提供两种策略：

    递归分块   按分隔符逐级往下切，切到目标长度为止，通用场景用它
    父子分块   先切成大的父块，再把每个父块切成小的子块。
               检索时用子块比对，命中后把整个父块给模型，
               兼顾"检索要小块更准"和"生成要大块上下文更完整"

产出统一是 Chunk 列表，父子分块产出的列表里父块在前、它的子块紧随其后，
写库时先插父块拿到 id，再把 id 填进子块的 parent_id。
"""

import re
from dataclasses import dataclass

from langchain_text_splitters import RecursiveCharacterTextSplitter

# 第 07 章的 PDF 解析在每页开头写了【第 N 页】，这里把页码提出来记到片段上
PAGE_PATTERN = re.compile(r"【第\s*(\d+)\s*页】")

# 分隔符里的转义写法。数据库存的是可见字符 \n，要还原成真正的换行符
ESCAPES = {"\\n": "\n", "\\t": "\t"}


@dataclass
class Chunk:
    """一个待入库的片段。"""

    content: str
    # 普通块 / 父块 / 子块
    chunk_type: str = "普通块"
    # 在文档内的顺序号，父块和子块各自独立编号
    chunk_index: int = 0
    # 子块用，指向它在返回列表里的父块下标，父块和普通块为 None
    parent_index: int | None = None
    page_no: int | None = None


def parse_separators(raw: str | None) -> list[str]:
    """把数据库里逗号分隔的分隔符字符串还原成列表。

    表里存的是 `\\n\\n,\\n,。,！,？` 这样的可见字符，
    直接拿去切分匹配不到真正的换行，要先还原转义。
    """
    if not raw:
        # 不配分隔符时用一套中文文档通用的默认值
        return ["\n\n", "\n", "。", "！", "？", "；", "，", ""]
    items = []
    for item in raw.split(","):
        text = item.strip()
        if not text:
            continue
        for escaped, real in ESCAPES.items():
            text = text.replace(escaped, real)
        items.append(text)
    # 末尾补一个空字符串，保证再长的连续文本也能被强行切开
    if "" not in items:
        items.append("")
    return items


def _page_no_of(text: str, fallback: int | None) -> int | None:
    """从片段文本里找页码标记，找不到就沿用上一段的页码。

    切分后一个片段可能不含【第 N 页】前缀，这时它一定属于上一个标记所在的页。
    """
    matched = PAGE_PATTERN.search(text)
    if matched:
        return int(matched.group(1))
    return fallback


def _split_recursive(text: str, chunk_size: int, chunk_overlap: int, separators: list[str]) -> list[str]:
    """按分隔符逐级切分。

    RecursiveCharacterTextSplitter 会先用第一个分隔符切，
    切出来的块还超长就换下一个分隔符继续切，直到达到目标长度。
    这样能尽量在段落、句子这些自然边界上断开，而不是从句子中间截断。
    """
    splitter = RecursiveCharacterTextSplitter(
        chunk_size=chunk_size,
        chunk_overlap=chunk_overlap,
        separators=separators,
        # 按字符数算长度。中文一个字就是一个字符，不需要按 token 估算
        length_function=len,
        # 保留分隔符，句号问号留在句尾，读起来才是完整句子
        keep_separator=True,
    )
    return [piece.strip() for piece in splitter.split_text(text) if piece.strip()]


def split_by_recursive(text: str, chunk_size: int, chunk_overlap: int, separators: list[str]) -> list[Chunk]:
    """递归分块：整篇文本切成一组平级的普通块。"""
    chunks = []
    page_no = None
    for index, piece in enumerate(_split_recursive(text, chunk_size, chunk_overlap, separators)):
        page_no = _page_no_of(piece, page_no)
        chunks.append(
            Chunk(content=piece, chunk_type="普通块", chunk_index=index, page_no=page_no)
        )
    return chunks


def split_by_parent_child(
    text: str,
    chunk_size: int,
    chunk_overlap: int,
    parent_chunk_size: int,
    separators: list[str],
) -> list[Chunk]:
    """父子分块：先切父块，每个父块再切子块。

    返回的列表里父块和它的子块相邻，子块的 parent_index 指向父块在列表里的下标。
    """
    chunks: list[Chunk] = []
    page_no = None
    parent_index = 0
    child_index = 0
    # 父块用不重叠的切法，父块之间重叠会让回填给模型的上下文出现大段重复
    parents = _split_recursive(text, parent_chunk_size, 0, separators)
    for parent_text in parents:
        page_no = _page_no_of(parent_text, page_no)
        parent_position = len(chunks)
        chunks.append(
            Chunk(
                content=parent_text,
                chunk_type="父块",
                chunk_index=parent_index,
                page_no=page_no,
            )
        )
        parent_index += 1
        for child_text in _split_recursive(parent_text, chunk_size, chunk_overlap, separators):
            chunks.append(
                Chunk(
                    content=child_text,
                    chunk_type="子块",
                    chunk_index=child_index,
                    parent_index=parent_position,
                    page_no=_page_no_of(child_text, page_no),
                )
            )
            child_index += 1
    return chunks


def split(text: str, strategy: dict) -> list[Chunk]:
    """按策略配置切分文本。

    strategy 来自 chunk_strategy 表，字段和表结构一一对应。
    """
    separators = parse_separators(strategy.get("separators"))
    chunk_size = strategy.get("chunk_size") or 500
    chunk_overlap = strategy.get("chunk_overlap") or 0
    strategy_type = strategy.get("strategy_type")
    if strategy_type == "父子分块":
        parent_chunk_size = strategy.get("parent_chunk_size") or chunk_size * 4
        return split_by_parent_child(text, chunk_size, chunk_overlap, parent_chunk_size, separators)
    if strategy_type == "递归分块":
        return split_by_recursive(text, chunk_size, chunk_overlap, separators)
    raise ValueError(f"没有对应 {strategy_type} 的切分实现")
