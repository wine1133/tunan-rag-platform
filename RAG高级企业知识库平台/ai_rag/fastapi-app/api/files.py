"""文件上传下载接口。"""

from fastapi import APIRouter, File, UploadFile
from starlette.responses import FileResponse

from common.result import Result
from service import file_service

router = APIRouter(prefix="/files")


@router.post("/upload")
async def upload_file(file: UploadFile = File(...)):
    """上传单个文件，返回可直接访问的下载地址。"""
    # 参数类型写成 UploadFile 而不是普通字段，
    # 因为浏览器上传走的是 multipart/form-data，不是 JSON
    return Result.success(file_service.save(file))


@router.get("/download/{filename}")
async def download_file(filename: str):
    """按文件名下载文件。"""
    # 文件名写在路径上，浏览器 img 标签的 src 可以直接指向这个地址
    return FileResponse(
        # resolve 把文件名拼成 fastapi-app/files 目录下的绝对路径
        path=file_service.resolve(filename),
        filename=filename,
        media_type="application/octet-stream",
    )
