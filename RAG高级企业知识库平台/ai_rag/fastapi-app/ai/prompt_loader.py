"""Prompt 加载。

所有发给模型的提示词都从 prompt_template 表读，代码里不写死任何提示词。
取模板时做三项校验：存在、启用、内容非空，任一不满足就报出明确的提示，
不用兜底的硬编码 Prompt——那会让管理员以为改了模板生效了，实际用的还是代码里那份。
"""

import re

from common.exception_handler import CustomException
from models import PromptTemplate

# 模板里的占位变量写法是 {变量名}
VARIABLE_PATTERN = re.compile(r"\{(\w+)\}")


async def load(code: str) -> str:
    """按编码取模板内容。"""
    template = await PromptTemplate.get_or_none(code=code)
    if template is None:
        raise CustomException(f"没有找到编码为 {code} 的 Prompt 模板，请先在 Prompt 模板里添加")
    if template.enabled != "是":
        raise CustomException(f"Prompt 模板 {code} 已被停用，请先启用")
    if not template.content or not template.content.strip():
        raise CustomException(f"Prompt 模板 {code} 的内容是空的，请先补充内容")
    return template.content


async def render(code: str, **values) -> str:
    """取模板并把变量填进去。

    模板里出现但没有传值的变量会被拦住，避免把 {context} 这种占位符原样发给模型。
    """
    content = await load(code)
    required = set(VARIABLE_PATTERN.findall(content))
    missing = required - set(values.keys())
    if missing:
        raise CustomException(f"Prompt 模板 {code} 缺少变量：{'、'.join(sorted(missing))}")
    # 只替换模板里真正用到的变量，多传的值忽略
    result = content
    for name in required:
        result = result.replace("{" + name + "}", str(values[name]))
    return result


def extract_variables(content: str | None) -> str:
    """从模板内容里抽出变量清单，逗号分隔，保存时自动回填到 variables 列。"""
    if not content:
        return ""
    # dict.fromkeys 去重的同时保留出现顺序，页面上展示顺序和模板里一致
    names = list(dict.fromkeys(VARIABLE_PATTERN.findall(content)))
    return ",".join(names)
