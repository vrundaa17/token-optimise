import sys, os
project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
if project_root not in sys.path:
    sys.path.insert(0, project_root)

import signal,subprocess,atexit
import uvicorn
import time
from fastapi import FastAPI
from fastmcp.utilities.lifespan import combine_lifespans
import logging, contextlib

import src.core.db as db
from src.core.document_search import list_index_doc
from src.mcp.server import _persistent_sessions
from src.mcp.server import app as mcp_app
from token_optimise.config import settings
from src.core.client import get_chroma_client

    

_start_time = time.time()

# Initialise DB schema once
db.init_db_once()

logger = logging.getLogger("token")


@contextlib.asynccontextmanager
async def _dashboard_lifespan(app: FastAPI):
    yield


mcp_http = mcp_app.http_app(path="/", transport="streamable-http")
api = FastAPI(
    title="token",
    lifespan=combine_lifespans(_dashboard_lifespan, mcp_http.lifespan),
)
api.mount("/mcp", mcp_http)


#------------------------------------------------------------------------------------------------------------------------------------------------------
# Endpoints : with get_db()

@api.get("/health")
async def health():
    uptime = int(time.time() - _start_time)
    hours = uptime // 3600
    minutes = (uptime % 3600) // 60
    seconds = uptime % 60

    tools_indexed = 0
    try:
        collection = get_chroma_client().get_or_create_collection("tools")
        tools_indexed = collection.count()
    except Exception:
        pass
    
    sessions_active = len(_persistent_sessions)

    total_events = 0
    try:
        with db.get_db() as conn:
            total_events = db.get_event_count(conn)
    except Exception:
        pass

    _KEY_VARS = ["GROQ_API_KEY", "OPENAI_API_KEY", "ANTHROPIC_API_KEY", "DEEPSEEK_API_KEY"]
    active_provider = next((k for k in _KEY_VARS if os.getenv(k)), None)

    return {
        "status": "ok",
        "uptime": f"{hours}h {minutes}m {seconds}s",
        "tools_indexed": tools_indexed,
        "sessions_active": sessions_active,
        "total_events_logged": total_events,
        "llm_model": os.getenv("LLM_MODEL", settings.llm_model),
        "provider": active_provider.replace("_API_KEY", "").lower() if active_provider else "none — check .env",
    }
        


@api.get("/metrics/summary")
async def metrics_summary():
    with db.get_db() as conn:
        return db.get_summary(conn)


@api.get("/metrics/tools")
async def metrics_tools():
    with db.get_db() as conn:
        return db.get_tool_stats(conn)


@api.get("/metrics/events")
async def metrics_events(limit: int = 50):
    with db.get_db() as conn:
        return db.get_recent_events(conn, limit)
    

@api.get("/metrics/indexed_docs")
async def metrics_indexed_docs():
    docs = list_index_doc()
    return [{"doc_id": k, "source": v} for k, v in docs.items()]


@api.get("/metrics/token_analysis")
async def token_analysis():
    with db.get_db() as conn:
        return db.get_token_analysis(conn)


@api.get("/metrics/groq_usage")
async def groq_usage():
    with db.get_db() as conn:
        return db.get_groq_usage(conn)


@api.get("/metrics/conversations")
async def conversations():
    with db.get_db() as conn:
        return db.get_conversation_stats(conn, limit=20)


@api.get("/metrics/timeseries")
async def timeseries(hours: int = 24):
    with db.get_db() as conn:
        return db.get_timeseries(conn, hours)


@api.get("/metrics/period")
async def period_summary(period: str = "today"):
    with db.get_db() as conn:
        return db.get_period_summary(conn, period)
    

@api.post("/shutdown")
async def shutdown():
    os.kill(os.getpid(), signal.SIGTERM)
    return {"status": "shutting down"}


#------------------------------------------------------------------------------------------------------------------------------------------------------
# Entry Point

if __name__ == "__main__":
    front_path = os.path.join(project_root, "src", "front.py")

    streamlit_proc = subprocess.Popen(
        [
            sys.executable, "-m", "streamlit", "run", front_path,
            "--server.port", str(settings.dashboard_port),
            "--server.headless", "true",
        ],
        cwd=project_root,
    )
    logger.info(
        f"[LAUNCHER] Streamlit started (pid {streamlit_proc.pid}) "
        f"| http://localhost:{settings.dashboard_port}"
    )

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

    logger.info(f"[LAUNCHER] FastAPI starting — http://localhost:{settings.api_port}")
    uvicorn.run(api, host="127.0.0.1", port=settings.api_port, workers=1)