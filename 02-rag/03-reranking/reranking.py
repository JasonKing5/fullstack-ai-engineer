import os

from dotenv import load_dotenv
from llama_index.core import (
    QueryBundle,
    Settings,
    SimpleDirectoryReader,
    StorageContext,
    VectorStoreIndex,
)
from llama_index.core.node_parser import MarkdownNodeParser
from llama_index.embeddings.openai import OpenAIEmbedding
from llama_index.llms.openai import OpenAI
from llama_index.postprocessor.cohere_rerank import CohereRerank
from llama_index.vector_stores.qdrant import QdrantVectorStore
from qdrant_client import QdrantClient

load_dotenv()

openai_api_key = os.getenv("OPENAI_API_KEY")
openai_base_url = os.getenv("OPENAI_BASE_URL")
model_name = os.getenv("MODEL_NAME")
qdrant_url = os.getenv("QDRANT_URL")
qdrant_api_key = os.getenv("QDRANT_API_KEY")
cohere_api_key = os.getenv("COHERE_API_KEY")


# Init qdrant connect
client = QdrantClient(
    location=qdrant_url,
    api_key=qdrant_api_key,
)


# Create a collection
collection_name = "financial_reports"


# Init vector store
vector_store = QdrantVectorStore(
    client=client,
    collection_name=collection_name,
    enable_hybrid=True,
    batch_size=20,
    fastembed_sparse_model="Qdrant/bm25",
)


# embed_model is always needed (used for query embedding during retrieval)
Settings.embed_model = OpenAIEmbedding(
    api_key=openai_api_key,
    api_base=openai_base_url,
    model=model_name,
)

# Load index: skip ingestion if collection already exists
if client.collection_exists(collection_name):
    print(
        f"✅ Collection '{collection_name}' exists, loading from Qdrant (no OpenAI calls)..."
    )
    index = VectorStoreIndex.from_vector_store(vector_store)
else:
    print(f"📥 First run: indexing documents into '{collection_name}'...")
    documents = SimpleDirectoryReader("./data-tsla/").load_data()

    # MarkdownNodeParser splits by headings and table boundaries,
    # keeping table headers and data rows in the same node.
    # This prevents BM25 from losing "Q4-2025" column context.
    parser = MarkdownNodeParser()
    nodes = parser.get_nodes_from_documents(documents)
    print(f"   → {len(nodes)} nodes parsed from {len(documents)} document(s)")

    storage_context = StorageContext.from_defaults(vector_store=vector_store)
    index = VectorStoreIndex(
        nodes,
        storage_context=storage_context,
        show_progress=True,
    )
    print(f"✅ Indexed to Qdrant collection '{collection_name}'")


# Create retriever
retriever = index.as_retriever(
    vector_store_query_mode="hybrid",
    similarity_top_k=20,
    sparse_top_k=20,
    dense_top_k=20,
    alpha=0.3,
)


# query = (
#     "What was Tesla's automotive gross margin excluding regulatory credits in Q1-2026?"
# )
query = "In which new U.S. cities did Tesla launch unsupervised Robotaxi service in April 2026?"
query_bundle = QueryBundle(query)

print(f"\n🔍 [Stage A] Hybrid search query（alpha=0.3）：'{query}'")
print("*" * 100)

retrieved_nodes = retriever.retrieve(query)


for i, node in enumerate(retrieved_nodes[:5]):
    score_str = f"{node.score:.4f}" if node.score is not None else "N/A"
    print(f"result {i + 1} (score: {score_str}):")
    print(f"  {node.text[:800]}...")
    print("*" * 100)


print(f"\n🔍 [Stage B] Reranking to Top-5：'{query}'")
print("*" * 100)

cohere_rerank = CohereRerank(
    api_key=cohere_api_key,
    top_n=5,
    # model="rerank-multilingual-v3.0",
)

reranked_nodes = cohere_rerank.postprocess_nodes(
    retrieved_nodes, query_bundle=query_bundle
)


for i, node in enumerate(reranked_nodes[:5]):
    score_str = f"{node.score:.4f}" if node.score is not None else "N/A"
    print(f"result {i + 1} (Cohere Score: {score_str}):")
    print(f"  {node.text[:800]}...")
    print("*" * 100)
