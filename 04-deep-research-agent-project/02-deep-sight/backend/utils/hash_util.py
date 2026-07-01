# backend/utils/hash_util.py
import hashlib
import os
import tempfile

from fastapi import UploadFile


async def save_and_hash_upload(upload_file: UploadFile) -> tuple[str, str]:
    """
    流式读取上传的文件：
    1. 计算 SHA-256 hash (去重依据)
    2. 保存至系统的 /tmp 目录 (供 worker 读取)
    返回: (文件路径, hash值)
    """
    sha256 = hashlib.sha256()

    # 创建一个安全的临时文件，且不自动删除（需要将其留给 worker）
    fd, temp_path = tempfile.mkstemp(suffix=".pdf")

    with os.fdopen(fd, "wb") as out_file:
        while chunk := await upload_file.read(1024 * 1024):  # 每次处理 1MB
            sha256.update(chunk)
            out_file.write(chunk)

    # 将指针拨回，以防有其他中间件想要读取
    await upload_file.seek(0)
    return temp_path, sha256.hexdigest()
