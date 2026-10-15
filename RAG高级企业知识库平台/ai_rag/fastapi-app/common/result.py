from datetime import date, datetime
from typing import Any, List

from fastapi.encoders import jsonable_encoder
from pydantic import BaseModel
from tortoise import Model

# 时间字段的输出格式。不指定的话 datetime 会被序列化成
# 2026-09-03T21:09:50+08:00 这种 ISO 串，表格里直接展示很难读，
# 这里统一成"年-月-日 时:分:秒"，前端拿到就能直接显示
DATETIME_ENCODERS = {
    datetime: lambda value: value.strftime("%Y-%m-%d %H:%M:%S"),
    date: lambda value: value.strftime("%Y-%m-%d"),
}



class Result(BaseModel):
    # 业务状态码，字符串类型："200" 成功、"500" 业务失败、"401" 未登录、"403" 无权限
    code: str
    # 提示文案，失败时前端直接把它弹出来给用户看
    msg: str
    # 业务数据，成功时放列表、对象或字符串，失败时为空
    data: Any = None

    @staticmethod
    def success(data: Any = None):
        json_data = None
        if data is not None:
            # PageInfo 是 pydantic 模型，jsonable_encoder 会先让 pydantic 自己序列化，
            # 里面的 datetime 在那一步就被转成 ISO 串了，下面的 custom_encoder 再也插不进去。
            # 先摊成普通 dict，列表里的 datetime 才能走到统一的时间格式化
            if isinstance(data, PageInfo):
                data = {"total": data.total, "list": data.list}
            # 所有接口的返回都从这里出去，时间格式在这一处统一
            json_data = jsonable_encoder(data, custom_encoder=DATETIME_ENCODERS)
        return Result(code="200", msg="请求成功", data=json_data)

    @staticmethod
    def error(msg: str = "请求失败"):
        return Result(code="500", msg=msg)


class PageInfo(BaseModel):
    # 总条数，前端用它渲染分页条
    total: int = 0
    # 当前页数据，前端用它渲染表格
    list: List[Any] = []
