from arq import create_pool
from arq.connections import RedisSettings
from config import settings

_redis_pool = None


async def get_redis_pool():
    """获取 ARQ 风格的 Redis 连接池（支持 enqueue_job）"""
    global _redis_pool
    if _redis_pool is None:
        _redis_pool = await create_pool(RedisSettings.from_dsn(settings.REDIS_URL))
    return _redis_pool


async def close_redis_pool():
    global _redis_pool
    if _redis_pool:
        await _redis_pool.close()
        _redis_pool = None
