import hashlib, time, os, logging
from src.core.client import get_chroma_client
from chromadb.utils import embedding_functions
from token_optimise.config import settings

logger = logging.getLogger("token")


TTL_BY_TOOL = {
    "execute": 300,
    "ask_document": 86400,
    "search_all_documents": 86400,
    "list_indexed_documents": 60,
    "index_document": 0,   
    "index_documents_folder": 0,
}
TTL_DEFAULT = 3600

_cache_collection = None

def _get_cache():
    global _cache_collection
    if _cache_collection is None:
        embedder = embedding_functions.SentenceTransformerEmbeddingFunction(
            model_name=settings.embedder
        )
        _cache_collection = get_chroma_client().get_or_create_collection(
            name="semantic_cache", embedding_function=embedder
        )
    return _cache_collection



def check_cache(query: str, tool_name: str = ""):
    """Returns (answer, similarity). answer is None on miss or expiry."""
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
            if ttl == 0:
                return None, similarity
            age = time.time() - cached_at
            if age > ttl:
                logger.info(
                    f"[CACHE] EXPIRED for '{tool_name}' | age={int(age)}s ttl={ttl}s"
                )
                return None, similarity
            logger.info(f"[CACHE] HIT for '{tool_name}' | sim={similarity:.3f} age={int(age)}s")
            return meta["answer"], similarity
        return None, similarity
    except Exception as e:
        logger.warning(f"[CACHE] check failed: {e}", exc_info=True)
        return None, 0.0


def check_cache_exact(key: str, tool_name: str = ""):
    try:
        result = _get_cache().get(ids=[key], include=["metadatas"])
        if not result["ids"]:
            return None, 0.0
        meta = result["metadatas"][0]
        cached_at = meta.get("cached_at", 0)
        ttl = TTL_BY_TOOL.get(tool_name, TTL_DEFAULT)
        if ttl == 0:
            return None, 1.0
        age = time.time() - cached_at
        if age > ttl:
            logger.info(f"[CACHE] EXPIRED (exact) for '{tool_name}' | age={int(age)}s")
            return None, 1.0
        logger.info(f"[CACHE] HIT (exact) for '{tool_name}'")
        return meta["answer"], 1.0
    except Exception as e:
        logger.warning(f"[CACHE] exact check failed: {e}")
        return None, 0.0
    
    
    

def store_answer(query, answer,tool_name):
    query_id = hashlib.sha256(query.strip().lower().encode()).hexdigest()
    try:
        _get_cache().upsert(
            ids=[query_id],
            documents=[query],
            metadatas=[{"answer": answer, "cached_at": time.time(), "tool_name": tool_name}],
        )
    except Exception as e:
        logger.warning(f"[CACHE] store failed: {e}")
        

def store_answer_exact(key: str, answer: str, tool_name: str) -> None:
    """Store by exact key (no embedding). Used for doc queries."""
    try:
        _get_cache().upsert(
            ids=[key],
            documents=[key],  
            metadatas=[{"answer": answer, "cached_at": time.time(), "tool_name": tool_name}],
        )
    except Exception as e:
        logger.warning(f"[CACHE] exact store failed: {e}")



def cleanup_cache():
    try:
        all_entries = _get_cache().get(include=["metadatas"])
        now = time.time()
        expired_ids = []
        for id_, meta in zip(all_entries["ids"], all_entries["metadatas"]):
            tool_name = meta.get("tool_name", "")
            ttl = TTL_BY_TOOL.get(tool_name, TTL_DEFAULT)
            if ttl == 0:
                continue
            if now - meta.get("cached_at", 0) > ttl:
                expired_ids.append(id_)
        if expired_ids:
            _get_cache().delete(ids=expired_ids)
            logger.info(f"[CACHE] cleaned up {len(expired_ids)} expired entries")
        return len(expired_ids)
    except Exception as e:
        logger.warning(f"[CACHE] cleanup failed: {e}")
        return 0