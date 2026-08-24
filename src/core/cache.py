import hashlib, time, sys, os, logging
from core.client import _chroma_client
from chromadb.utils import embedding_functions
from config import settings, PROJECT_ROOT

logger = logging.getLogger("token")

CHROMA_PATH = os.path.join(PROJECT_ROOT, "storage", "chroma_db")
TTL_BY_TOOL = {
    "find_tool": 300,
    "ask_document": 86400,
    "search_all_documents": 86400,
    "list_indexed_documents": 60,
}
TTL_DEFAULT = 3600

_cache_collection = None

def _get_cache():
    global _cache_collection
    if _cache_collection is None:
        embedder = embedding_functions.SentenceTransformerEmbeddingFunction(model_name=settings.embedder)
        _cache_collection = _chroma_client.get_or_create_collection(name="semantic_cache", embedding_function=embedder)
    return _cache_collection

def check_cache(query: str, tool_name: str = ""):
    try:
        results = _get_cache().query(query_texts=[query], n_results=1)
        if not results["documents"][0]:
            return None, 0.0
        distance = results["distances"][0][0]
        similarity = 1 - distance
        if similarity >= 0.8:
            meta = results["metadatas"][0][0]
            cached_at = meta.get("cached_at", 0)
            ttl = TTL_BY_TOOL.get(tool_name, TTL_DEFAULT)
            if time.time() - cached_at > ttl:
                return None, similarity
            return meta['answer'], similarity
        return None, similarity
    except Exception as e:
        logger.warning(f"[CACHE] check failed: {e}")
        return None, 0.0

def store_answer(query, answer):
    query_id = hashlib.sha256(query.strip().lower().encode()).hexdigest()
    try:
        _get_cache().upsert(
            ids=[query_id],
            documents=[query],
            metadatas=[{'answer': answer, 'cached_at': time.time()}],
        )
    except Exception as e:
        logger.warning(f"[CACHE] store failed for query: {query} - {e}")

def cleanup_cache():
    try:
        all_entries = _get_cache().get(include=["metadatas"])
        now = time.time()
        expired_ids = [
            id_ for id_, meta in zip(all_entries["ids"], all_entries["metadatas"])
            if now - meta.get("cached_at", 0) > TTL_DEFAULT
        ]
        if expired_ids:
            _get_cache().delete(ids=expired_ids)
            logger.info(f"[CACHE] cleaned up {len(expired_ids)} expired entries")
        return len(expired_ids)
    except Exception as e:
        logger.warning(f"[CACHE] cleanup failed: {e}")
        return 0