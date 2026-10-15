import asyncio
import sys
from contextlib import asynccontextmanager

import jieba
import uvicorn
from fastapi import FastAPI
from starlette.middleware.cors import CORSMiddleware
from tortoise.contrib.fastapi import RegisterTortoise, tortoise_exception_handlers

from api import api_router
from common.exception_handler import setup_exceptions
from common.result import Result
from settings import TORTOISE_ORM


@asynccontextmanager
async def lifespan(app: FastAPI):
    """应用启动时连接数据库、预热分词器，关闭时释放连接。"""
    # jieba 第一次分词时才加载词典，要一两秒。BM25 检索每次都要分词，
    # 不预热的话这段耗时会落在用户的第一次提问上，这里挪到启动阶段。
    # 加载是纯 CPU 的同步操作，丢到线程里跑，不占事件循环。
    await asyncio.to_thread(jieba.initialize)
    async with RegisterTortoise(app, config=TORTOISE_ORM):
        yield


app = FastAPI(
    title="兔南高级企业知识库RAG平台",
    lifespan=lifespan,
    # ORM 层的异常（记录不存在、唯一键冲突等）交给 Tortoise 自带的处理器
    exception_handlers=tortoise_exception_handlers(),
)

# 跨域配置 CORS。前端跑在 5173 端口、后端在 9090，属于跨域请求，
# 不配的话浏览器会拦掉所有接口调用
app.add_middleware(
    CORSMiddleware,
    # 允许所有源
    allow_origins=["*"],
    # 允许所有 HTTP 方法
    allow_methods=["*"],
    # 允许所有请求头，前端要带自定义的 token 头
    allow_headers=["*"],
)

# 注册全部业务路由
app.include_router(api_router)
# 注册统一异常处理器
setup_exceptions(app)


@app.get("/")
async def root():
    return Result.success()


def loop_factory() -> asyncio.AbstractEventLoop:
    """指定事件循环类型，交给 uvicorn 用来创建循环。

    Windows 上 Python 默认用 ProactorEventLoop，而向量库用的 psycopg
    异步模式不支持它，一连接就报：

        Psycopg cannot use the 'ProactorEventLoop' to run in async mode

    所以 Windows 上必须换成 SelectorEventLoop。uvicorn 只在开了 reload
    的时候才会自己换成 Selector，一旦有人把 reload 关掉，向量检索就会
    在运行时突然连不上库，所以这里显式指定，不依赖 reload 的副作用。
    """
    if sys.platform == "win32":
        return asyncio.SelectorEventLoop()
    return asyncio.new_event_loop()


if __name__ == "__main__":
    uvicorn.run("main:app", host="localhost", reload=True, port=9090, loop="main:loop_factory")
