# backend/worker.py
import asyncio
import os

from arq.connections import RedisSettings
from config import settings
from llama_index.core import Document, StorageContext, VectorStoreIndex
from llama_index.core import Settings as LlamaSettings
from llama_index.embeddings.openai import OpenAIEmbedding
from llama_index.vector_stores.qdrant import QdrantVectorStore

# 显式引入，不依赖自动注册机制
from llama_parse import LlamaParse
from qdrant_client import AsyncQdrantClient, QdrantClient
from qdrant_client.models import (
    Distance,
    FieldCondition,
    Filter,
    MatchValue,
    PayloadSchemaType,
    SparseVectorParams,
    VectorParams,
)

# 显式配置大模型环境，支持全局代理
LlamaSettings.embed_model = OpenAIEmbedding(
    api_key=settings.OPENAI_API_KEY,
    api_base=settings.OPENAI_BASE_URL,
    model="text-embedding-3-small",
)


async def process_pdf_task(ctx, file_path: str, file_hash: str, company_name: str):
    """ARQ 异步执行节点：处理 PDF 提取与向量化"""
    print(f"[{company_name}] Worker 接收任务: file={file_path}")
    redis = ctx["redis"]
    collection_name = "financial_reports"

    try:
        # 1. 解析 PDF
        parser = LlamaParse(
            api_key=settings.LLAMA_CLOUD_API_KEY, result_type="markdown", num_workers=2
        )
        parsed_docs = await parser.aload_data(file_path)
        documents = [
            Document(
                text=doc.text, metadata={"company": company_name, "hash": file_hash}
            )
            for doc in parsed_docs
        ]

        # 2. 连接 Qdrant
        # 同步客户端，专门供 LlamaIndex 初始化检查使用
        client = QdrantClient(url=settings.QDRANT_URL, api_key=settings.QDRANT_API_KEY)
        # 异步客户端，做删除、建库操作
        aclient = AsyncQdrantClient(
            url=settings.QDRANT_URL, api_key=settings.QDRANT_API_KEY
        )
        if not await aclient.collection_exists(collection_name):
            await aclient.create_collection(
                collection_name=collection_name,
                # 稠密向量配置 (OpenAI Embedding)
                vectors_config=VectorParams(size=1536, distance=Distance.COSINE),
                # 稀疏向量配置 (支持 BM25 混合检索)
                sparse_vectors_config={"text-sparse-new": SparseVectorParams()},
            )

        # 为 company 字段建立 keyword 索引，这样才能根据公司名执行高效查询和删除
        await aclient.create_payload_index(
            collection_name=collection_name,
            field_name="company",
            field_schema="keyword",  # 指定类型为精确匹配关键字
            wait=True,  # 阻塞等待索引生效
        )

        # 3. 向量幂等覆盖策略 (按 company_name 删除旧数据)
        print(f"[{company_name}] 正在清理该公司的历史旧数据...")
        await aclient.delete(
            collection_name=collection_name,
            points_selector=Filter(
                must=[
                    FieldCondition(key="company", match=MatchValue(value=company_name))
                ]
            ),
        )

        # 4. 执行写入
        vector_store = QdrantVectorStore(
            collection_name=collection_name,
            client=client,  # 传入同步客户端供 LlamaIndex 内部检测
            aclient=aclient,  # 传入异步客户端供未来异步操作
            enable_hybrid=True,
        )

        # 包装为 StorageContext
        storage_context = StorageContext.from_defaults(vector_store=vector_store)

        # 自动使用在顶部配置好的 LlamaSettings.embed_model
        VectorStoreIndex.from_documents(documents, storage_context=storage_context)

        # 5. 标记该文件 hash 已处理，有效期 30 天
        await redis.setex(f"processed_hash:{file_hash}", 30 * 24 * 3600, "1")
        print(f"[{company_name}] 向量入库成功！")

        return {"status": "success", "company": company_name, "chunks": len(documents)}

    except Exception as e:
        print(f"[{company_name}] 处理失败: {str(e)}")
        raise e

    finally:
        # 6. 确保临时文件被清理，防 OOM 和磁盘耗尽
        if os.path.exists(file_path):
            os.remove(file_path)
            print(f"[{company_name}] 本地临时文件 {file_path} 已清理。")


# ARQ 配置入口
class WorkerSettings:
    redis_settings = RedisSettings.from_dsn(settings.REDIS_URL)
    functions = [process_pdf_task]
    max_jobs = 10  # 控制并发解析数量
