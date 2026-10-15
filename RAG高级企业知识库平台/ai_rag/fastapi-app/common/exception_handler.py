from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from starlette import status
from starlette.responses import JSONResponse


# 自定义异常类
class CustomException(Exception):
    def __init__(self, message: str, code: str = "500"):
        # message 是给用户看的人话提示，会原样出现在前端的红色弹窗里
        self.message = message
        # code 默认 500 表示业务失败，登录失效传 401，无权限传 403
        self.code = code


def setup_exceptions(app: FastAPI):
    @app.exception_handler(CustomException)
    async def custom_exception_handler(request: Request, exc: CustomException):
        return JSONResponse(
            # 业务异常也返回 HTTP 200，错误信息放在响应体的 code 里，
            # 前端只需要判断 code 这一个字段，不用同时处理 HTTP 状态码和业务码两套
            status_code=status.HTTP_200_OK,
            content={"code": exc.code, "msg": exc.message}
        )

    @app.exception_handler(RequestValidationError)
    async def validate_exception_handler(request: Request, exc: RequestValidationError):
        print("捕获到422错误:", exc.errors())
        """处理422异常"""
        # 返回统一格式
        return JSONResponse(
            # 同样返回 HTTP 200，参数错误由响应体里的 code=500 表达
            status_code=status.HTTP_200_OK,
            content={"code": "500", "msg": "请求参数错误"}
        )

    @app.exception_handler(Exception)
    async def global_exception_handler(request: Request, exc: Exception):
        print("捕获到系统错误:", repr(exc))
        """处理所有异常"""
        # 返回统一格式
        response = JSONResponse(
            # 兜底处理器同样返回 HTTP 200，未预料的异常也走统一格式
            status_code=status.HTTP_200_OK,
            content={"code": "500", "msg": "系统错误"}
        )
        # 兜底处理器返回的响应不经过 CORS 中间件，跨域头要自己补上，
        # 否则前端拿到的是一个被浏览器拦掉的响应，看不到"系统错误"这条提示
        # 允许所有源（与你的 CORS 配置一致）
        response.headers["Access-Control-Allow-Origin"] = "*"
        response.headers["Access-Control-Allow-Methods"] = "*"
        response.headers["Access-Control-Allow-Headers"] = "*"
        return response
