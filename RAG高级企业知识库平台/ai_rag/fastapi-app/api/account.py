"""登录、注册、修改密码、获取当前登录账号。"""

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from common.auth import get_current_user
from common.result import Result
from models import User
from service import account_service

# 这个 router 不加 prefix，所以路径就是 /login、/register，
# 和前端 request.post('/login') 里写的地址一一对应
router = APIRouter()


class Account(BaseModel):
    # 前端 data.form 里可能只填了部分字段，所以四个字段全部允许为 None，
    # 具体哪个必填由 service 层判断并给出人话提示
    username: str | None = None
    password: str | None = None
    newPassword: str | None = None
    confirmPassword: str | None = None


@router.post("/login")
async def login(account: Account):
    # FastAPI 按 Account 的字段名自动把请求体 JSON 解析成对象，
    # 路由层不做业务判断，直接把账号密码交给 service
    data = await account_service.login(account.username, account.password)
    # data 里含 token 和用户信息，Result.success 包成统一格式返回给前端
    return Result.success(data)


@router.post("/register")
async def register(account: Account):
    # 注册用到 Account 里的三个字段，newPassword 用不上
    await account_service.register(account.username, account.password, account.confirmPassword)
    return Result.success()


@router.put("/updatePassword")
async def update_password(account: Account, current_user: User = Depends(get_current_user)):
    # 改的一定是自己的密码，用户身份从 token 解析，不接受前端传 id
    await account_service.update_password(current_user, account.password, account.newPassword)
    # 注册成功不返回任何数据，前端只看 code 是不是 200
    return Result.success()


@router.get("/currentUser")
async def current_user(user: User = Depends(get_current_user)):
    return Result.success(account_service.account_dict(user))
