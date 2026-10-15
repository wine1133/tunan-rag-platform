"""知识库管理接口测试。

覆盖新增、名称查重、分页查询、编辑、删除，跑完自己清理掉造的数据。
"""

TEST_NAME = "测试知识库-单元测试专用"


def _create(client, admin_headers, name=TEST_NAME):
    return client.post(
        "/knowledgeBase/add",
        json={"name": name, "description": "自动化测试创建", "status": "正常"},
        headers=admin_headers,
    ).json()


def _find_id(client, admin_headers, name=TEST_NAME):
    body = client.get(
        "/knowledgeBase/selectPage",
        params={"name": name, "page_num": 1, "page_size": 10},
        headers=admin_headers,
    ).json()
    for item in body["data"]["list"]:
        if item["name"] == name:
            return item["id"]
    return None


def _cleanup(client, admin_headers, name=TEST_NAME):
    kb_id = _find_id(client, admin_headers, name)
    if kb_id is not None:
        client.delete(f"/knowledgeBase/delete/{kb_id}", headers=admin_headers)


def test_add_and_select_page(client, admin_headers):
    """新增后能在分页列表里查到，文档数和片段数初始为 0。"""
    _cleanup(client, admin_headers)
    assert _create(client, admin_headers)["code"] == "200"

    body = client.get(
        "/knowledgeBase/selectPage",
        params={"name": TEST_NAME, "page_num": 1, "page_size": 10},
        headers=admin_headers,
    ).json()
    assert body["code"] == "200"
    assert body["data"]["total"] >= 1
    created = [item for item in body["data"]["list"] if item["name"] == TEST_NAME][0]
    assert created["document_count"] == 0
    assert created["chunk_count"] == 0
    assert created["status"] == "正常"

    _cleanup(client, admin_headers)


def test_add_duplicated_name_is_rejected(client, admin_headers):
    """同名知识库不允许重复创建。"""
    _cleanup(client, admin_headers)
    _create(client, admin_headers)

    body = _create(client, admin_headers)
    assert body["code"] == "500"
    assert body["msg"] == "知识库名称重复"

    _cleanup(client, admin_headers)


def test_add_without_name_is_rejected(client, admin_headers):
    """名称为空时给出人话提示。"""
    body = client.post(
        "/knowledgeBase/add",
        json={"description": "没有名称"},
        headers=admin_headers,
    ).json()
    assert body["code"] == "500"
    assert body["msg"] == "请输入知识库名称"


def test_update_keeps_own_name_available(client, admin_headers):
    """编辑时保持原名保存不会被自己的查重拦下。"""
    _cleanup(client, admin_headers)
    _create(client, admin_headers)
    kb_id = _find_id(client, admin_headers)

    body = client.put(
        "/knowledgeBase/update",
        json={"id": kb_id, "name": TEST_NAME, "description": "改了描述", "status": "停用"},
        headers=admin_headers,
    ).json()
    assert body["code"] == "200"

    detail = client.get(f"/knowledgeBase/selectById/{kb_id}", headers=admin_headers).json()
    assert detail["data"]["description"] == "改了描述"
    assert detail["data"]["status"] == "停用"

    _cleanup(client, admin_headers)


def test_select_all_only_returns_normal_status(client, admin_headers):
    """下拉框接口只返回正常状态的知识库。"""
    _cleanup(client, admin_headers)
    _create(client, admin_headers)
    kb_id = _find_id(client, admin_headers)
    client.put(
        "/knowledgeBase/update",
        json={"id": kb_id, "name": TEST_NAME, "status": "停用"},
        headers=admin_headers,
    )

    body = client.get("/knowledgeBase/selectAll", headers=admin_headers).json()
    names = [item["name"] for item in body["data"]]
    assert TEST_NAME not in names

    _cleanup(client, admin_headers)


def test_normal_user_cannot_access(client):
    """普通用户调管理端接口返回 403。"""
    login = client.post("/login", json={"username": "zhangsan", "password": "123456"}).json()
    headers = {"token": login["data"]["token"]}
    body = client.get("/knowledgeBase/selectPage", headers=headers).json()
    assert body["code"] == "403"
    assert body["msg"] == "没有操作权限"
