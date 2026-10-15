from datetime import datetime, timedelta, timezone

import jwt
from fastapi import Header

from common.exception_handler import CustomException
from models import User
from settings import JWT_ALGORITHM, JWT_EXPIRE_HOURS, JWT_SECRET


def create_token(user: User) -> str:
    # 过期时间 = 当前 UTC 时间 + 配置的小时数，settings.py 里配的是 24 小时
    expire_time = datetime.now(timezone.utc) + timedelta(hours=JWT_EXPIRE_HOURS)
    # sub 存用户 id，后面每个受保护接口都靠它反查当前登录用户；
    # role 存角色，exp 是 JWT 标准的过期字段，解码时会自动校验
    # sub 存用户 id，后面每个受保护接口都靠它反查当前登录用户；
    # role 存角色，exp 是 JWT 标准的过期字段，解码时会自动校验
    payload = {"sub": str(user.id), "role": user.role, "exp": expire_time}
    # 用 settings.py 里的密钥和 HS256 算法签名，前端拿到的是这串字符串
    return jwt.encode(payload, JWT_SECRET, algorithm=JWT_ALGORITHM)


async def get_current_user(token: str | None = Header(default=None)) -> User:
    # token 从请求头取，前端的 request.js 拦截器每次请求都会带上
    if not token:
        # token 被篡改、过期、格式不对，统一按登录失效处理
        raise CustomException("登录状态已失效，请重新登录", "401")
    try:
        # 解码同时会校验签名和 exp 过期时间，任一不通过就抛异常
        payload = jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALGORITHM])
        user_id = int(payload.get("sub"))
    except (jwt.InvalidTokenError, TypeError, ValueError):
        # token 被篡改、过期、格式不对，统一按登录失效处理
        raise CustomException("登录状态已失效，请重新登录", "401")
    # token 里只有 id，要拿到完整用户信息还要查一次库；
    # 顺便能发现"token 还没过期但账号已经被删或被停用"的情况
    user = await User.get_or_none(id=user_id)
    if user is None or user.status != "NORMAL":
        raise CustomException("账号不存在或已被停用", "401")
    return user


async def require_admin(token: str | None = Header(default=None)) -> User:
    # 先按通用逻辑解析 token 拿到用户，token 无效时这一步就会抛 401
    user = await get_current_user(token)
    # 再判断角色，普通用户访问管理端接口时抛 403
    if user.role != "ADMIN":
        raise CustomException("没有操作权限", "403")
    return user
