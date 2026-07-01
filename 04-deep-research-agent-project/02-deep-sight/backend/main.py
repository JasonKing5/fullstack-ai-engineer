# backend/main.py
from contextlib import asynccontextmanager

from api.upload_router import router as upload_router
from arq import create_pool
from arq.connections import RedisSettings
from config import settings
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware


# FastAPI 生命周期管理
@asynccontextmanager
async def lifespan(app: FastAPI):
    print("🚀 启动系统: 初始化全局 Redis ARQ 连接池...")
    # 初始化异步连接池，并挂载到 app.state
    app.state.redis = await create_pool(RedisSettings.from_dsn(settings.REDIS_URL))

    yield  # 这里是 FastAPI 正常运行的时间

    print("🛑 关闭系统: 释放资源...")
    app.state.redis.close()
    await app.state.redis.wait_closed()


app = FastAPI(title="Enterprise AI Agent API", lifespan=lifespan)

# CORS 配置
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3001"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 注册子路由
app.include_router(upload_router)
