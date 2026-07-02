# backend/main.py
from contextlib import asynccontextmanager

from api.upload_router import router as upload_router
from arq import create_pool

# 导入底层基础设施
from arq import create_pool as create_redis_pool
from arq.connections import RedisSettings

# 导入业务路由和配置
from config import settings
from engine.graph import build_graph
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
from psycopg_pool import AsyncConnectionPool


# FastAPI 生命周期管理
@asynccontextmanager
async def lifespan(app: FastAPI):
    print("🚀 启动系统: 1/3 建立 Redis ARQ 连接池...")
    # 初始化异步连接池，并挂载到 app.state
    app.state.redis = await create_pool(RedisSettings.from_dsn(settings.REDIS_URL))

    print("🚀 系统启动: 2/3 建立 Postgres 数据库连接池...")
    # 配置 PostgreSQL 连接池
    app.state.pg_pool = AsyncConnectionPool(
        conninfo=settings.DATABASE_URL,
        max_size=20,
        kwargs={"autocommit": True},  # LangGraph 需要自动提交
        open=False,  # 禁止在构造时自动连接
    )
    await app.state.pg_pool.open()

    print("🚀 系统启动: 3/3 初始化 LangGraph 持久化引擎...")
    # 实例化 Checkpointer
    checkpointer = AsyncPostgresSaver(app.state.pg_pool)

    # 核心步骤：如果数据库没有 checkpointer 专属表，自动建表！
    await checkpointer.setup()

    # 编译有向图：开启持久化，并设置原生拦截器 (interrupt_before)
    graph_builder = build_graph()
    app.state.agent_graph = graph_builder.compile(
        checkpointer=checkpointer,
        interrupt_before=["publish_node"],  # 到达发布节点前挂起，等待人类
    )
    print("✅ AI 引擎编译完毕，系统准备就绪。")

    yield  # FastAPI 正常运行的时间

    print("🛑 关闭系统: 释放资源...")
    await app.state.redis.close()
    await app.state.pg_pool.close()


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
