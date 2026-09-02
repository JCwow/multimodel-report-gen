import os
from langchain_community.embeddings import FastEmbedEmbeddings
from langchain_qdrant import QdrantVectorStore
from qdrant_client import QdrantClient
from qdrant_client.http.models import Distance, VectorParams

QDRANT_HOST = os.getenv("QDRANT_HOST", "localhost")
QDRANT_PORT = int(os.getenv("QDRANT_PORT", 6333))
COLLECTION_NAME = "meeting_reports"

# 初始化輕量免 API Key 的 FastEmbed
embeddings = FastEmbedEmbeddings(model_name="BAAI/bge-small-en-v1.5")

client = QdrantClient(host=QDRANT_HOST, port=QDRANT_PORT)

# 確保 Collection 存在
collections = client.get_collections().collections
if not any(c.name == COLLECTION_NAME for c in collections):
    client.create_collection(
        collection_name=COLLECTION_NAME,
        vectors_config=VectorParams(size=384, distance=Distance.COSINE),
    )

vector_store = QdrantVectorStore(
    client=client,
    collection_name=COLLECTION_NAME,
    embedding=embeddings,
)

def index_report(report_text: str, metadata: dict):
    """將生成的會議報告向量化並儲存"""
    vector_store.add_texts(
        texts=[report_text],
        metadatas=[metadata]
    )

def search_reports(query: str, limit: int = 3):
    """搜尋歷史會議記錄"""
    results = vector_store.similarity_search(query, k=limit)
    return [{"content": doc.page_content, "metadata": doc.metadata} for doc in results]