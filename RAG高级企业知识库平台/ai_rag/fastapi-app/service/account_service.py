"""登录注册与当前账号相关的业务逻辑。"""

from common.auth import create_token
from common.exception_handler import CustomException
from models import User

# 系统只有两种角色：管理端 ADMIN、用户端 USER
ROLES = {"ADMIN", "USER"}
STATUSES = {"NORMAL", "DISABLED"}


def account_dict(user: User, token: str | None = None) -> dict:
    """账号信息脱敏输出，不返回密码字段。"""
    # 这个字典就是前端 res.data 的内容，也是存进 localStorage 的 xm-user，
    # 页面右上角的姓名头像、路由守卫判断角色，用的都是这里的字段
    data = {
        "id": user.id,
        "username": user.username,
        "name": user.name,
        "avatar": user.avatar,
        "role": user.role,
        "phone": user.phone,
        "email": user.email,
        "status": user.status,
    }
    # 只有登录接口会传 token 进来，其他接口复用这个函数时不带 token
    if token:
        data["token"] = token
    return data


async def login(username: str | None, password: str | None) -> dict:
    # 按账号查用户，username 上有唯一索引，最多命中一条
    user = await User.get_or_none(username=username)
    # 账号不存在和密码错误合并成同一句提示，不告诉对方是哪一步错了
    if user is None or user.password != password:
        raise CustomException("账号或密码错误")
    # 密码对了还要看状态，管理员在用户管理里停用的账号不允许登录
    if user.status != "NORMAL":
        raise CustomException("账号已被停用")
    # 校验全通过，签发 token 并连同用户信息一起返回
    return account_dict(user, create_token(user))


async def register(username: str | None, password: str | None, confirm_password: str | None) -> None:
    # 前端 rules 已经拦过一次空值，后端再拦一次，防止绕过页面直接调接口
    if not username or not password:
        raise CustomException("账号和密码不能为空")
    # 两次密码一致性后端也要复核一遍，同样是防止绕过页面直接调接口
    if password != confirm_password:
        raise CustomException("两次输入的密码不一致")
    # 账号重复校验，命中就中断，不进入插入逻辑
    if await User.get_or_none(username=username):
        raise CustomException("账号重复")
    # 注册入口只能创建普通用户，管理员账号由管理端在用户管理里添加
    await User.create(
        username=username,
        password=password,
        # 姓名默认填成账号，用户可以在第 03 章的个人资料页改成真实姓名
        name=username,
        role="USER",
        status="NORMAL",
    )


async def update_password(
    current_user: User,
    password: str | None,
    new_password: str | None,
) -> None:
    # 原密码必须对得上，防止别人趁着页面没锁屏直接改密码
    if current_user.password != password:
        raise CustomException("原密码错误")
    if not new_password:
        raise CustomException("请输入新密码")
    # 新旧密码一样等于没改，直接拦下来
    if current_user.password == new_password:
        raise CustomException("新密码不能与原密码相同")
    # 按当前登录用户的 id 更新，改不到别人头上
    await User.filter(id=current_user.id).update(password=new_password)
