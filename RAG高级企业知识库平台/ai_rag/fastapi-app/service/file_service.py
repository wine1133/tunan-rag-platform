"""文件上传下载业务逻辑。"""

import os
import shutil

from fastapi import UploadFile

from common.exception_handler import CustomException

# 上传的文件统一放在 fastapi-app/files 目录下
UPLOAD_DIR = "files"
# 下载地址前缀，和后端启动端口保持一致，
# 上传成功后拼上文件名返回给前端，前端直接把这个地址存进数据库
# 下载地址前缀，和后端启动端口保持一致，
# 上传成功后拼上文件名返回给前端，前端直接把这个地址存进数据库
DOWNLOAD_PREFIX = "http://127.0.0.1:9090/files/download/"


def save(file: UploadFile) -> str:
    """保存上传的文件，返回可直接访问的下载地址。"""
    # 目录不存在时自动建，避免第一次上传报找不到路径
    os.makedirs(UPLOAD_DIR, exist_ok=True)
    # 用原始文件名保存，同名文件会被覆盖
    file_location = os.path.join(UPLOAD_DIR, file.filename)
    # 以二进制写入，copyfileobj 分块拷贝，大文件不会一次性读进内存
    with open(file_location, "wb") as buffer:
        shutil.copyfileobj(file.file, buffer)
    # 返回的这个地址会被前端存进 user 表的 avatar 列，
    # 或者第 06 章存进 knowledge_document 表的 file_url 列
    return DOWNLOAD_PREFIX + file.filename


def resolve(filename: str) -> str:
    """根据文件名定位磁盘路径，文件不存在时给出明确提示。"""
    file_path = os.path.join(UPLOAD_DIR, filename)
    # 文件被手工删掉或者文件名拼错时，返回人话提示而不是 500
    if not os.path.exists(file_path):
        raise CustomException("文件不存在")
    return file_path
