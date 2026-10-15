"""用户管理业务逻辑。"""

from typing import List

from common.exception_handler import CustomException
from common.result import PageInfo
from models import User
from service.account_service import ROLES, STATUSES


def user_dict(user: User) -> dict:
    # 表格每一列取的都是这里的字段，密码不放进来，列表页看不到密码
    return {
        "id": user.id,
        "username": user.username,
        "name": user.name,
        "avatar": user.avatar,
        "role": user.role,
        "phone": user.phone,
        "email": user.email,
        "status": user.status,
        "create_time": user.create_time,
        "update_time": user.update_time,
    }


async def add(payload: dict) -> None:
    username = payload.get("username")
    # 账号是登录凭据，必须有值
    if not username:
        raise CustomException("请输入账号")
    # 账号唯一，重复就中断，不进入插入逻辑
    if await User.get_or_none(username=username):
        raise CustomException("账号重复")
    # 弹窗默认给的是 USER，这里再兜一次底，防止绕过页面直接调接口传乱值
    role = payload.get("role") or "USER"
    if role not in ROLES:
        raise CustomException("角色参数错误")
    await User.create(
        username=username,
        # 密码框留空时给默认密码，和弹窗里的占位提示一致
        password=payload.get("password") or "123456",
        # 姓名不填就用账号顶上，保证列表页姓名列不为空
        name=payload.get("name") or username,
        avatar=payload.get("avatar"),
        role=role,
        phone=payload.get("phone"),
        email=payload.get("email"),
        # 状态不填默认正常，新建的账号可以直接登录
        status=payload.get("status") or "NORMAL",
    )


async def update(current_user: User, user_id: int | None, update_data: dict) -> None:
    if user_id is None:
        raise CustomException("用户ID不能为空")
    user = await User.get_or_none(id=user_id)
    if user is None:
        raise CustomException("未找到用户")
    # 管理员可以改任何人，普通用户只能改自己
    if current_user.role != "ADMIN" and current_user.id != user.id:
        raise CustomException("没有操作权限", "403")
    # 普通用户不允许给自己改角色和账号状态
    if current_user.role != "ADMIN":
        update_data.pop("role", None)
        update_data.pop("status", None)
    # 传了角色就必须是合法值，没传则跳过校验
    if update_data.get("role") is not None and update_data["role"] not in ROLES:
        raise CustomException("角色参数错误")
    # 传了状态就必须是合法值，没传则跳过校验
    if update_data.get("status") is not None and update_data["status"] not in STATUSES:
        raise CustomException("账号状态参数错误")
    await User.filter(id=user.id).update(**update_data)


async def delete(current_user: User, user_id: int) -> None:
    # 删掉自己会导致当前会话立刻失效，页面停在一个无效登录态上，直接拦住
    if current_user.id == user_id:
        raise CustomException("不能删除当前登录账号")
    await User.filter(id=user_id).delete()


async def delete_batch(current_user: User, ids: List[int]) -> None:
    # 勾选里包含自己就整批拦下，不做"跳过自己删其他人"的处理，
    # 避免用户以为全删了、实际漏了一条
    if current_user.id in ids:
        raise CustomException("不能删除当前登录账号")
    await User.filter(id__in=ids).delete()


async def select_by_id(current_user: User, user_id: int) -> dict:
    # 普通用户只能查自己那条，防止改地址栏 id 看别人的资料
    if current_user.role != "ADMIN" and current_user.id != user_id:
        raise CustomException("没有操作权限", "403")
    user = await User.get_or_none(id=user_id)
    if user is None:
        raise CustomException("未找到用户")
    return user_dict(user)


async def select_all(name: str = "") -> List[dict]:
    users = await User.filter(name__contains=name).order_by("-id")
    return [user_dict(user) for user in users]


async def select_page(name: str = "", role: str = "", page_num: int = 1, page_size: int = 10) -> PageInfo:
    # name 来自页面顶部姓名输入框，contains 是模糊匹配；
    # 空字符串时 like '%%' 能匹配所有记录，等于不加这个条件
    query = User.filter(name__contains=name)
    # role 来自角色下拉框，只有选了角色才追加精确匹配条件
    if role:
        query = query.filter(role=role)
    # 按 id 倒序排，新建的用户排在最前面；
    # offset 跳过前面几页的数据，limit 取当前页的条数
    users = await query.order_by("-id").offset((page_num - 1) * page_size).limit(page_size)
    # 总条数要用不带分页的同一个 query 去数，分页条靠它算出总页数
    total = await query.count()
    return PageInfo(total=total, list=[user_dict(user) for user in users])
