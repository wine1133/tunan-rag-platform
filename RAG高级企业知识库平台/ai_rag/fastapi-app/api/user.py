"""用户管理接口。"""

from typing import List

from fastapi import APIRouter, Depends
from pydantic import BaseModel, ConfigDict

from common.auth import get_current_user, require_admin
from common.result import Result
from models import User
from service import user_service

# 这个 router 带 prefix="/user"，所以下面所有路径前面都自动加上 /user
router = APIRouter(prefix="/user")


class UserPayload(BaseModel):
    # from_attributes 允许直接用 ORM 对象构造这个模型
    model_config = ConfigDict(from_attributes=True)

    # 全部字段都允许为 None，前端弹窗可能只填了其中几项，
    # 哪些必填由 service 判断并给出人话提示
    id: int | None = None
    username: str | None = None
    password: str | None = None
    name: str | None = None
    avatar: str | None = None
    role: str | None = None
    phone: str | None = None
    email: str | None = None
    status: str | None = None


@router.post("/add")
async def add(payload: UserPayload, _: User = Depends(require_admin)):
    # exclude_unset=True 只保留前端真正传了的字段，
    # 没填的字段不进字典，交给 service 决定默认值
    await user_service.add(payload.model_dump(exclude_unset=True))
    return Result.success()


@router.put("/update")
async def update(payload: UserPayload, current_user: User = Depends(get_current_user)):
    # 账号和密码不允许通过本接口修改，密码走 /updatePassword
    update_data = payload.model_dump(exclude_unset=True, exclude={"id", "username", "password"})
    await user_service.update(current_user, payload.id, update_data)
    return Result.success()


@router.delete("/delete/{user_id}")
async def delete(user_id: int, current_user: User = Depends(require_admin)):
    # user_id 写在路径上，因为它是被删对象的定位标识，不是一段业务数据；
    # current_user 这里要用到，所以不写成下划线
    await user_service.delete(current_user, user_id)
    return Result.success()


@router.delete("/deleteBatch")
async def delete_batch(ids: List[int], current_user: User = Depends(require_admin)):
    # 请求体是一个纯数字数组，FastAPI 直接解析成 List[int]
    await user_service.delete_batch(current_user, ids)
    return Result.success()


@router.get("/selectById/{user_id}")
async def select_one(user_id: int, current_user: User = Depends(get_current_user)):
    return Result.success(await user_service.select_by_id(current_user, user_id))


@router.get("/selectAll")
async def select_all(name: str = "", _: User = Depends(get_current_user)):
    return Result.success(await user_service.select_all(name))


@router.get("/selectPage")
async def select_page(
    # name 和 role 来自地址栏的查询参数，不传时是空字符串，表示不加这个筛选条件
    name: str = "",
    role: str = "",
    # 页码和每页条数同样来自查询参数，给了默认值，前端不传也能跑
    page_num: int = 1,
    page_size: int = 10,
    # Depends(require_admin) 会先解析请求头里的 token，
    # 不是管理员就直接抛 403，函数体根本不会执行
    _: User = Depends(require_admin),
):
    return Result.success(await user_service.select_page(name, role, page_num, page_size))
