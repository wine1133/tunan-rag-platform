"""路由层入口。

本文件只做两件事：创建总路由 api_router、自动扫描并注册 api 包下所有子模块的 router。
具体接口写在同目录的业务文件里（account.py / user.py / files.py ...），
新增一个业务域时只要在本目录下新建文件并定义 router，无需修改本文件。
"""

import importlib
import pkgutil

from fastapi import APIRouter

api_router = APIRouter()

for _, module_name, _ in pkgutil.iter_modules(__path__, __name__ + "."):
    module = importlib.import_module(module_name)
    if hasattr(module, "router"):
        api_router.include_router(module.router)
