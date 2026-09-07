"""Qdrant-backed meeting report index. Connection is lazy so tests and MCP
startup do not require a live database."""

from __future__ import annotations

import logging
from typing import Any

from app.config import QDRANT_HOST, QDRANT_PORT

logger = logging.getLogger(__name__)

COLLECTION_NAME = "meeting_reports"

_vector_store = None
_failed = False


def _connect():
    from langchain_community.embeddings import FastEmbedEmbeddings
    from langchain_qdrant import QdrantVectorStore
    from qdrant_client import QdrantClient
    from qdrant_client.http.models import Distance, VectorParams

    embeddings = FastEmbedEmbeddings(model_name="BAAI/bge-small-en-v1.5")
    client = QdrantClient(host=QDRANT_HOST, port=QDRANT_PORT)
    collections = client.get_collections().collections
    if not any(c.name == COLLECTION_NAME for c in collections):
        client.create_collection(
            collection_name=COLLECTION_NAME,
            vectors_config=VectorParams(size=384, distance=Distance.COSINE),
        )
    return QdrantVectorStore(
        client=client,
        collection_name=COLLECTION_NAME,
        embedding=embeddings,
    )


def get_vector_store():
    global _vector_store, _failed
    if _failed:
        return None
    if _vector_store is None:
        try:
            _vector_store = _connect()
        except Exception as exc:
            logger.warning("Qdrant unavailable: %s", exc)
            _failed = True
            return None
    return _vector_store


def index_report(report_text: str, metadata: dict):
    """將生成的會議報告向量化並儲存"""
    store = get_vector_store()
    if store is None:
        logger.warning("skip indexing; vector store unavailable")
        return
    store.add_texts(texts=[report_text], metadatas=[metadata])


def search_reports(query: str, limit: int = 3) -> list[dict[str, Any]]:
    """搜尋歷史會議記錄"""
    store = get_vector_store()
    if store is None:
        return []
    results = store.similarity_search(query, k=limit)
    return [{"content": doc.page_content, "metadata": doc.metadata} for doc in results]
