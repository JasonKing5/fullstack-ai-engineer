# backend/config.py

from typing import Optional

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    # LLM Config
    OPENAI_API_KEY: str
    OPENAI_BASE_URL: str = "https://api.openai.com/v1"

    # Redis Config
    REDIS_URL: str

    # Qdrant Config
    QDRANT_URL: str
    QDRANT_API_KEY: str

    # LlamaCloud Config
    LLAMA_CLOUD_API_KEY: str

    # --- 把未来会用到，或者 .env 里已经有的字段加上，设为可选 ---
    DATABASE_URL: Optional[str] = None
    COHERE_API_KEY: Optional[str] = None

    # Pydantic V2 的标准配置写法
    model_config = SettingsConfigDict(
        env_file=".env",
        extra="ignore",  # 核心修复点：明确告诉系统忽略 .env 中未定义的额外变量！
    )


# 暴露单例配置对象
settings = Settings()
