# backend/engine/tools.py
from config import settings
from llama_index.core import VectorStoreIndex
from llama_index.embeddings.openai import OpenAIEmbedding
from llama_index.vector_stores.qdrant import QdrantVectorStore
from qdrant_client import AsyncQdrantClient, QdrantClient
from tenacity import retry, stop_after_attempt, wait_exponential

# 全局初始化大模型 Embedding
embed_model = OpenAIEmbedding(
    api_key=settings.OPENAI_API_KEY,
    api_base=settings.OPENAI_BASE_URL,
    model="text-embedding-3-small",
)


@retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=2, max=10))
async def retrieve_financial_data(company: str, query: str) -> str:
    """
    防弹检索工具：带 3 次退避重试的 Qdrant 混合检索。
    """
    client = QdrantClient(url=settings.QDRANT_URL, api_key=settings.QDRANT_API_KEY)
    aclient = AsyncQdrantClient(
        url=settings.QDRANT_URL, api_key=settings.QDRANT_API_KEY
    )

    vector_store = QdrantVectorStore(
        collection_name="financial_reports",
        client=client,
        aclient=aclient,
        enable_hybrid=True,
    )

    index = VectorStoreIndex.from_vector_store(
        vector_store=vector_store, embed_model=embed_model
    )

    # 构建检索器，利用 kwargs 限制只搜索该公司的数据
    retriever = index.as_retriever(
        similarity_top_k=4,
        sparse_top_k=4,
        vector_store_kwargs={
            "filter": {"must": [{"key": "company", "match": {"value": company}}]}
        },
    )

    nodes = await retriever.aretrieve(query)
    if not nodes:
        return f"未找到关于 {company} - {query} 的财报数据。"

    return "\n\n".join([n.get_content() for n in nodes])
