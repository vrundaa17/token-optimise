import signal,subprocess,atexit
import sys,uvicorn
import os
project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
sys.path.insert(0, project_root)

from fastapi import FastAPI
import logging
from src.core.db import get_connection, init_db, get_summary, get_recent_events, get_tool_stats, get_token_analysis,get_conversation_stats
from src.core.document_search import list_index_doc


_dash_conn = get_connection()
init_db(_dash_conn)

api = FastAPI(title="token")

logger = logging.getLogger("token")


@api.get("/health")
async def health():
    return {"status": "ok", "server": "token-optim", "version": "1.0"}

@api.get("/metrics/summary")
async def metrics_summary():
    row = get_summary(_dash_conn)
    return {
        "total_calls": row["total_calls"],
        "cache_hits": row["cache_hits"],
        "hit_rate_pct": row["hit_rate_pct"],
        "total_trim_saved": row["total_trim_saved"],
        "total_schema_saved": row["total_schema_saved"],
        "total_tokens_saved": row["total_tokens_saved"]
    }

@api.get("/metrics/tools")
async def metrics_tools():
    rows = get_tool_stats(_dash_conn)
    return [dict(r) for r in rows]

@api.get("/metrics/events")
async def metrics_events(limit: int = 50):
    rows = get_recent_events(_dash_conn, limit)
    return [dict(r) for r in rows]

@api.get("/metrics/indexed_docs")
async def metrics_indexed_docs():
    docs = list_index_doc()
    return [{"doc_id": k, "source": v} for k, v in docs.items()]


@api.get("/metrics/token_analysis")
async def token_analysis():
    return get_token_analysis(_dash_conn)

@api.get("/metrics/conversations")
def conversations():
    conn = get_connection()
    rows = get_conversation_stats(conn, limit=20)
    return [dict(r) for r in rows]



if __name__ == "__main__":    
    front_path = os.path.join(project_root, "src", "front.py")

    streamlit_proc = subprocess.Popen(
        [sys.executable, "-m", "streamlit", "run", front_path,
         "--server.port", "8501", "--server.headless", "true"],
        cwd=project_root
    )
    print(f"[LAUNCHER] Streamlit started (pid {streamlit_proc.pid}) | http://localhost:8501")

    def _kill_streamlit():
        if streamlit_proc.poll() is None:
            streamlit_proc.terminate()
            print("[LAUNCHER] Streamlit stopped")

    atexit.register(_kill_streamlit)

    def _forward_signal(signum, frame):
        _kill_streamlit()
        sys.exit(0)

    signal.signal(signal.SIGTERM, _forward_signal)
    signal.signal(signal.SIGINT, _forward_signal)

    print("[LAUNCHER] FastAPI started → http://localhost:8000")
    uvicorn.run(api, host="0.0.0.0", port=8000)