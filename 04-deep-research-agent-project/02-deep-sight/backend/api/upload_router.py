# backend/api/upload_router.py
from arq.jobs import Job
from fastapi import APIRouter, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import JSONResponse
from utils.hash_util import save_and_hash_upload

router = APIRouter()


@router.post("/api/upload")
async def upload_document(
    request: Request, company_name: str = Form(...), file: UploadFile = File(...)
):
    if not file.filename.endswith(".pdf"):
        raise HTTPException(400, "Only PDF files are supported.")

    redis_pool = request.app.state.redis

    # 1. 存临时文件 & 计算 Hash
    temp_path, file_hash = await save_and_hash_upload(file)

    # 2. API 级秒级查重
    is_processed = await redis_pool.get(f"processed_hash:{file_hash}")
    if is_processed:
        import os

        os.remove(temp_path)  # 既然已处理过，立即删掉刚存的临时文件
        return JSONResponse(
            status_code=200,
            content={"status": "cached", "message": "该文件已被解析过，数据为最新。"},
        )

    # 3. 投递后台任务
    job = await redis_pool.enqueue_job(
        "process_pdf_task", temp_path, file_hash, company_name
    )

    # 4. [企业级改进 9]：返回标准的 202 异步状态
    return JSONResponse(
        status_code=202,
        content={
            "status": "accepted",
            "job_id": job.job_id,
            "message": "文件已进入后台解析队列。",
        },
    )


@router.get("/api/upload/status/{job_id}")
async def get_job_status(request: Request, job_id: str):
    """轮询任务状态"""
    redis_pool = request.app.state.redis
    job = Job(job_id, redis_pool)

    status = await job.status()
    response = {"job_id": job_id, "status": status.value}

    # 如果完成，尝试获取结果
    if status.value == "complete":
        try:
            # 尝试获取正常执行的结果
            result = await job.result(timeout=1)
            response["result"] = result
        except Exception as e:
            # 【核心修复点】如果任务失败、抛出异常或反序列化失败，优雅降级
            response["status"] = "failed"
            response["error"] = "后台任务执行失败，请检查 Worker 日志排查原因。"

    return response
