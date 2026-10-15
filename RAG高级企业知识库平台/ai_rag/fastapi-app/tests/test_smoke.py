"""工程骨架冒烟测试。

只验证三件事：应用能起来、数据库能连上、统一返回格式没被破坏。
业务功能的测试放在各自章节里，本文件不随业务增长而膨胀。

运行前提：MySQL 已启动，且已执行过 ai_rag.sql。
运行方式（在 fastapi-app 目录下）：pytest
"""

from fastapi.testclient import TestClient

from main import app


def test_root_returns_success():
    """根路径返回统一格式的成功结果，说明应用和数据库都已就绪。"""
    with TestClient(app) as client:
        response = client.get("/")
    assert response.status_code == 200
    body = response.json()
    assert body["code"] == "200"
    assert body["msg"] == "请求成功"


def test_login_with_wrong_password_returns_business_error():
    """业务失败走统一异常处理：HTTP 仍然是 200，code 为 500，msg 是人话。"""
    with TestClient(app) as client:
        response = client.post("/login", json={"username": "admin", "password": "wrong"})
    assert response.status_code == 200
    body = response.json()
    assert body["code"] == "500"
    assert body["msg"] == "账号或密码错误"


def test_login_success_returns_token():
    """初始化数据里的管理员账号能登录，并拿到 token。"""
    with TestClient(app) as client:
        response = client.post("/login", json={"username": "admin", "password": "123456"})
    body = response.json()
    assert body["code"] == "200"
    assert body["data"]["role"] == "ADMIN"
    assert body["data"]["token"]


def test_protected_api_without_token_returns_401_code():
    """未登录访问受保护接口，返回 401 业务码而不是直接抛异常。"""
    with TestClient(app) as client:
        response = client.get("/user/selectPage")
    body = response.json()
    assert body["code"] == "401"
