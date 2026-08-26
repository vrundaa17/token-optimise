import signal,subprocess,atexit
import sys,uvicorn
import os,time
project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
sys.path.insert(0, project_root)

from fastapi import FastAPI
from fastmcp.utilities.lifespan import combine_lifespans
import logging, contextlib
import src.core.db as db
from src.core.document_search import list_index_doc
from src.mcp.server import _persistent_sessions
from src.mcp.server import app as mcp_app
from config import settings

_start_time = time.time()

# Initialise DB schema once
def _init_db_once():
    conn = db.get_connection()
    db.init_db(conn)
    conn.close()

_init_db_once()

@contextlib.asynccontextmanager
async def _dashboard_lifespan(app: FastAPI):
    yield

mcp_http = mcp_app.http_app(path="/", transport="sse")
api = FastAPI(title="token", lifespan=combine_lifespans(_dashboard_lifespan, mcp_http.lifespan))
api.mount("/mcp", mcp_http)


logger = logging.getLogger("token")


@api.get("/health")
async def health():
    uptime = int(time.time() - _start_time)
    hours = uptime // 3600
    minutes = (uptime % 3600) // 60
    seconds = uptime % 60

    tools_indexed = 0
    try:
        from src.core.client import _chroma_client
        collection = _chroma_client.get_or_create_collection("tools")
        tools_indexed = collection.count()
    except Exception:
        pass

    sessions_active = len(_persistent_sessions)

    total_events = 0
    try:
        conn = db.get_connection()
        total_events = db.get_event_count(conn)
        conn.close()
    except Exception:
        pass

    return {
        "status": "ok",
        "uptime": f"{hours}h {minutes}m {seconds}s",
        "tools_indexed": tools_indexed,
        "sessions_active": sessions_active,
        "total_events_logged": total_events,
        "groq": "ok" if os.getenv("GROQ_API_KEY") else "missing"
    }
    


@api.get("/metrics/summary")
async def metrics_summary():
    conn = db.get_connection()
    try:
        row = db.get_summary(conn)
        return {
            "total_calls": row["total_calls"],
            "cache_hits": row["cache_hits"],
            "hit_rate_pct": row["hit_rate_pct"],
            "total_trim_saved": row["total_trim_saved"],
            "total_schema_saved": row["total_schema_saved"],
            "total_tokens_saved": row["total_tokens_saved"]
        }
    finally:
        conn.close()

@api.get("/metrics/tools")
async def metrics_tools():
    conn = db.get_connection()
    try:
        rows =db.get_tool_stats(conn)
        return [dict(r) for r in rows]
    finally:
        conn.close()

@api.get("/metrics/events")
async def metrics_events(limit: int = 50):
    conn = db.get_connection()
    try:
        rows = db.get_recent_events(conn, limit)
        return [dict(r) for r in rows]
    finally:
        conn.close()

@api.get("/metrics/indexed_docs")
async def metrics_indexed_docs():
    docs = list_index_doc()
    return [{"doc_id": k, "source": v} for k, v in docs.items()]

@api.get("/metrics/token_analysis")
async def token_analysis():
    conn =db.get_connection()
    try:
        return db.get_token_analysis(conn)
    finally:
        conn.close()
        
@api.get("/metrics/groq_usage")
async def groq_usage():
    conn=db.get_connection()
    try:
        return db.get_groq_usage(conn)
    finally:
        conn.close()

@api.get("/metrics/conversations")
def conversations():
    conn = db.get_connection()
    try:
        rows = db.get_conversation_stats(conn, limit=20)
        return [dict(r) for r in rows]
    finally:
        conn.close()


@api.get("/shutdown")
async def shutdown():
    os.kill(os.getpid(),signal.SIGTERM)
    return {"status":"shutting down"}


if __name__ == "__main__":    
    front_path = os.path.join(project_root, "src", "front.py")

    streamlit_proc = subprocess.Popen(
        [sys.executable, "-m", "streamlit", "run", front_path,
        "--server.port", str(settings.dashboard_port), "--server.headless", "true"],
        cwd=project_root
    )
    logger.info(f"[LAUNCHER] Streamlit started (pid {streamlit_proc.pid}) | http://localhost:8501")

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

    logger.info(f"[LAUNCHER] FastAPI started - http://localhost:{settings.api_port}")
    uvicorn.run(api, host="0.0.0.0", port= settings.api_port)
    