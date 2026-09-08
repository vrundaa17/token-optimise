from token_optimise.config import settings
from src.core.client import get_chroma_client, expand_query
from chromadb.utils import embedding_functions
import os, logging

logger = logging.getLogger("token")

_embedder = None
_tools_indexed = False
_indexed_tool_names: set = set()

TOOL_CONFIDENCE_THRESHOLD = settings.tool_confidence_threshold
REMOTE_TOOL_CONFIDENCE_THRESHOLD = settings.remote_tool_confidence_threshold


def _get_embedder():
    global _embedder
    if _embedder is None:
        _embedder = embedding_functions.SentenceTransformerEmbeddingFunction(
            model_name=settings.embedder
        )
    return _embedder



def _enrich_description(name: str, description: str) -> str:
    name_as_words = name.replace("_", " ").replace("-", " ").lower()
    return f"{name_as_words} {description}".strip()


def index_tools(tools):
    """Index tool name, description into Chroma for semantic lookup."""
    global _tools_indexed, _indexed_tool_names
    collection = get_chroma_client().get_or_create_collection(
        name="tools", embedding_function=_get_embedder()
    )
    incoming_names = {t["function"]["name"] for t in tools}

    removed = _indexed_tool_names - incoming_names
    if removed:
        collection.delete(ids=list(removed))
        logger.info(f"[TOOLS] removed {len(removed)} stale tools from index")

    enriched_docs = [
        _enrich_description(t["function"]["name"], t["function"].get("description", ""))
        for t in tools
    ]

    collection.upsert(
        ids=[t["function"]["name"] for t in tools],
        documents=enriched_docs,
        metadatas=[
            {
                "tool_name": t["function"]["name"],
                "name": t["function"]["name"],
                "server": t.get("server", ""),
            }
            for t in tools
        ],
    )

    _indexed_tool_names = incoming_names
    _tools_indexed = True
    logger.info(f"[TOOLS] indexed {len(tools)} tools")



def select_relevant_tools(tools: list[dict], query: str, top_k: int = 2, remote_tool_names: set = None) -> tuple:
    """Returns (selected_tools, expand_prompt_tokens, expand_completion_tokens)."""
    if len(tools) <= top_k:
        return tools, 0, 0

    if not _tools_indexed:
        # Index not ready yet : return top_k by position as safe fallback
        logger.warning("[TOOL_SELECT] index not ready, using positional fallback")
        return tools[:top_k], 0, 0

    # Pass all tools to expand_query [no silent cap]
    normalised, expand_prompt_tokens, expand_completion_tokens = expand_query(query, tools)

    collection = get_chroma_client().get_or_create_collection(
        name="tools", embedding_function=_get_embedder()
    )

    result = collection.query(
        query_texts=[normalised],
        n_results=min(top_k, len(tools)),
        include=["distances", "metadatas"],
    )
    selected_ids = result["ids"][0]
    distances = result["distances"][0]

    confident_ids = []
    for tool_id, distance in zip(selected_ids, distances):
        similarity = 1 - distance
        is_remote = remote_tool_names and tool_id in remote_tool_names
        threshold = (
            REMOTE_TOOL_CONFIDENCE_THRESHOLD if is_remote else TOOL_CONFIDENCE_THRESHOLD
        )
        if similarity >= threshold:
            confident_ids.append(tool_id)
            logger.info(
                f"[TOOL_SELECT] {tool_id} | sim={similarity:.3f} | CONFIDENT"
                f"{' (remote)' if is_remote else ''}"
            )
        else:
            logger.info(
                f"[TOOL_SELECT] {tool_id} | sim={similarity:.3f} | BELOW THRESHOLD"
            )

    if not confident_ids:
        logger.warning(f"[TOOL_SELECT] no tool met threshold for: '{query}'")
        return [], expand_prompt_tokens, expand_completion_tokens

    return (
        [t for t in tools if t["function"]["name"] in confident_ids],
        expand_prompt_tokens,
        expand_completion_tokens,
    )