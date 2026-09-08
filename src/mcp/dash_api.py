import signal
import subprocess
import sys, atexit
import os
import time
import uvicorn
import logging
import hmac, hashlib, uuid
from collections import defaultdict

project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
sys.path.insert(0, project_root)

from fastapi import FastAPI, Header, HTTPException,Request
import psycopg2
import psycopg2.extras
import psycopg2.pool


_start_time = time.time()
logger = logging.getLogger("token")

DATABASE_URL  = os.getenv("DATABASE_URL", "")
SERVER_SECRET = os.getenv("SERVER_SECRET", "") 
ADMIN_SECRET = os.getenv("ADMIN_SECRET", "")


api = FastAPI(title="token-dashboard-api")

_pool = None
_ingest_counts = defaultdict(list)


def _get_pool():
    global _pool
    if _pool is None:
        if not DATABASE_URL:
            raise RuntimeError("DATABASE_URL environment variable is not set")
        _pool = psycopg2.pool.ThreadedConnectionPool(1, 10, DATABASE_URL, connect_timeout=5)
    return _pool



def _fetch(sql, params=()):
    pool = _get_pool()
    conn = pool.getconn()
    try:
        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        cur.execute(sql, params)
        rows = [dict(r) for r in cur.fetchall()]
        cur.close()
        return rows
    finally:
        pool.putconn(conn)


def _fetchone(sql, params=()):
    pool = _get_pool()
    conn = pool.getconn()
    try:
        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        cur.execute(sql, params)
        row = cur.fetchone()
        cur.close()
        return dict(row) if row else {}
    finally:
        pool.putconn(conn)

def _count():
    row = _fetchone("SELECT COUNT(*) AS cnt FROM events")
    return row.get("cnt", 0)

def _make_token(user_id: str) -> str:
    """Same user_id always gives same token. No DB needed."""
    return hmac.new(
        SERVER_SECRET.encode(),
        user_id.encode(),
        hashlib.sha256
    ).hexdigest()

def _is_valid_uuid(val: str) -> bool:
    try:
        uuid.UUID(val)
        return True
    except (ValueError, AttributeError):
        return False

_rate_counts = defaultdict(list)

def _rate_limit(key: str, max_per_minute: int = 60):
    now = time.time()
    window = [t for t in _rate_counts[key] if now - t < 60]
    window.append(now)
    _rate_counts[key] = window
    if len(window) > max_per_minute:
        raise HTTPException(status_code=429, detail="Too many requests")




# ------------------------------------------------------------------------------------------------------------------------------------------------------
# Auth dependency


    
def _verify_admin_token(x_admin_token: str):
    """Reject /admin/* calls that don't carry the admin secret."""
    if ADMIN_SECRET and x_admin_token != ADMIN_SECRET:
        raise HTTPException(status_code=403, detail="Forbidden")
    
# ------------------------------------------------------------------------------------------------------------------------------------------------------
# Ingest


@api.post("/register")
async def register(payload: dict, request: Request):
    user_id = payload.get("user_id", "")
    if not _is_valid_uuid(user_id):
        raise HTTPException(status_code=400, detail="Invalid request")
    _rate_limit(request.client.host, max_per_minute=10)
    token = _make_token(user_id)
    return {"token": token}


@api.post("/collect")
async def collect_event(event: dict, request: Request, x_collect_token: str = Header(default="")):
    user_id = event.get("user_id", "")
    if not _is_valid_uuid(user_id):
        raise HTTPException(status_code=400, detail="Invalid request")

    # check token matches this user_id
    expected = _make_token(user_id)
    if not hmac.compare_digest(x_collect_token, expected):
        raise HTTPException(status_code=403, detail="Forbidden")

    _rate_limit(request.client.host)
    _rate_limit(user_id)

    try:
        fields = [
            "user_id", "conversation_id",
            "tool_name", "query", "cache_hit", "cache_similarity",
            "tokens_before_trim", "tokens_after_trim", "trim_saved",
            "schema_tokens_full", "schema_tokens_selected", "schema_tokens_saved",
            "doc_id", "success",
            "groq_prompt_tokens", "groq_completion_tokens",
        ]
        data = {f: event.get(f) for f in fields}
        columns = ", ".join(fields)
        placeholders = ", ".join(["%s"] * len(fields))
        pool = _get_pool()
        conn = pool.getconn()
        try:
            cur = conn.cursor()
            cur.execute(
                f"INSERT INTO events ({columns}) VALUES ({placeholders})",
                list(data.values()),
            )
            conn.commit()
            cur.close()
        finally:
            pool.putconn(conn)
        return {"status": "ok"}
    except Exception as e:
        logger.error(f"[COLLECT] Failed: {e}")
        return {"status": "error", "detail": str(e)}


# ------------------------------------------------------------------------------------------------------------------------------------------------------
# health 

@api.get("/health")
async def health():
    uptime = int(time.time() - _start_time)
    hours = uptime // 3600
    minutes = (uptime % 3600) // 60
    seconds = uptime % 60
    try:
        total = _count()
    except Exception:
        total = 0
    return {
        "status": "ok",
        "uptime": f"{hours}h {minutes}m {seconds}s",
        "tools_indexed": "N/A",
        "sessions_active": "N/A",
        "total_events_logged": total,
        "groq": "ok" if os.getenv("GROQ_API_KEY") else "missing",
    }

# ------------------------------------------------------------------------------------------------------------------------------------------------------
# metrics 

_PERIOD_WHERE = {
    "today":     "DATE(timestamp) = CURRENT_DATE",
    "yesterday": "DATE(timestamp) = CURRENT_DATE - INTERVAL '1 day'",
    "week":      "timestamp >= NOW() - INTERVAL '7 days'",
    "all":       "1=1",
}


@api.get("/metrics/summary")
async def metrics_summary():
    return _fetchone("""
        SELECT
            COUNT(*) AS total_calls,
            COALESCE(SUM(cache_hit), 0) AS cache_hits,
            COALESCE(ROUND(AVG(cache_hit::numeric) * 100, 1), 0.0) AS hit_rate_pct,
            COALESCE(SUM(trim_saved), 0) AS total_trim_saved,
            COALESCE(SUM(schema_tokens_saved), 0) AS total_schema_saved,
            COALESCE(SUM(trim_saved + schema_tokens_saved), 0) AS total_tokens_saved
        FROM events
    """)


@api.get("/metrics/tools")
async def metrics_tools():
    return _fetch("""
        SELECT
            tool_name,
            COUNT(*) AS calls,
            SUM(cache_hit) AS hits,
            SUM(trim_saved) AS trim_saved,
            SUM(schema_tokens_saved) AS schema_saved
        FROM events
        GROUP BY tool_name
        ORDER BY calls DESC
    """)


@api.get("/metrics/events")
async def metrics_events(limit: int = 50):
    return _fetch(
        "SELECT * FROM events ORDER BY timestamp DESC LIMIT %s", (limit,)
    )


@api.get("/metrics/indexed_docs")
async def metrics_indexed_docs():
    # Cloud API has no local Chroma — return empty list
    return []


@api.get("/metrics/token_analysis")
async def token_analysis():
    rows = _fetchone("""
        SELECT
            COUNT(*) AS total_queries,
            COALESCE(SUM(schema_tokens_saved), 0) AS schema_saved,
            COALESCE(SUM(schema_tokens_full), 0) AS schema_full,
            COALESCE(SUM(schema_tokens_selected), 0) AS schema_selected,
            COALESCE(SUM(trim_saved), 0) AS trim_saved,
            COALESCE(SUM(tokens_before_trim), 0) AS tokens_before_trim,
            COALESCE(SUM(tokens_after_trim), 0) AS tokens_after_trim,
            COALESCE(SUM(cache_hit), 0) AS cache_hits,
            COUNT(CASE WHEN cache_hit = 0 THEN 1 END) AS cache_misses
        FROM events
    """)
    schema_saved    = rows.get("schema_saved", 0)
    schema_full     = rows.get("schema_full", 0)
    schema_selected = rows.get("schema_selected", 0)
    trim_saved      = rows.get("trim_saved", 0)
    tokens_before   = rows.get("tokens_before_trim", 0)
    tokens_after    = rows.get("tokens_after_trim", 0)
    total_saved     = schema_saved + trim_saved
    actual_without  = schema_full + tokens_before
    actual_with     = schema_selected + tokens_after
    pct_saved = round((total_saved / actual_without * 100), 1) if actual_without > 0 else 0.0
    return {
        "total_queries": rows.get("total_queries", 0),
        "cache_hits": rows.get("cache_hits", 0),
        "cache_misses": rows.get("cache_misses", 0),
        "schema_tokens_without_tom": schema_full,
        "schema_tokens_with_tom": schema_selected,
        "schema_saved": schema_saved,
        "tokens_before_trim": tokens_before,
        "tokens_after_trim": tokens_after,
        "trim_saved": trim_saved,
        "total_saved": total_saved,
        "actual_without_tom": actual_without,
        "actual_with_tom": actual_with,
        "pct_saved": pct_saved,
    }


@api.get("/metrics/groq_usage")
async def groq_usage():
    return _fetchone("""
        SELECT
            COALESCE(SUM(groq_prompt_tokens), 0)   AS total_prompt_tokens,
            COALESCE(SUM(groq_completion_tokens), 0) AS total_completion_tokens,
            COALESCE(SUM(groq_prompt_tokens + groq_completion_tokens), 0) AS total_groq_tokens
        FROM events
    """)


@api.get("/metrics/conversations")
async def conversations():
    return _fetch("""
        SELECT
            conversation_id,
            MIN(timestamp) AS started_at,
            COUNT(*) AS total_calls,
            SUM(cache_hit) AS cache_hits,
            SUM(trim_saved) AS trim_saved,
            SUM(schema_tokens_saved) AS schema_saved,
            SUM(trim_saved + schema_tokens_saved) AS total_saved
        FROM events
        WHERE conversation_id IS NOT NULL
        GROUP BY conversation_id
        ORDER BY started_at DESC
        LIMIT 20
    """)


@api.get("/metrics/timeseries")
async def timeseries(hours: int = 24):
    # Use explicit cast to avoid INTERVAL format injection
    return _fetch("""
        SELECT
            to_char(date_trunc('hour', timestamp), 'YYYY-MM-DD HH24:00') AS hour,
            COUNT(*) AS total_calls,
            COALESCE(SUM(cache_hit), 0) AS cache_hits,
            COALESCE(SUM(schema_tokens_saved), 0) AS schema_saved,
            COALESCE(SUM(trim_saved), 0) AS trim_saved,
            COALESCE(SUM(groq_prompt_tokens + groq_completion_tokens), 0) AS groq_tokens
        FROM events
        WHERE timestamp >= NOW() - (%(hours)s || ' hours')::interval
        GROUP BY date_trunc('hour', timestamp)
        ORDER BY date_trunc('hour', timestamp) ASC
    """, {"hours": str(int(hours))})


@api.get("/metrics/period")
async def period_summary(period: str = "today"):
    where = _PERIOD_WHERE.get(period, "1=1")
    return _fetchone(f"""
        SELECT
            COUNT(*) AS total_calls,
            COALESCE(SUM(cache_hit), 0) AS cache_hits,
            COALESCE(SUM(schema_tokens_saved + trim_saved), 0) AS total_saved,
            COALESCE(SUM(groq_prompt_tokens), 0) AS groq_prompt,
            COALESCE(SUM(groq_completion_tokens), 0) AS groq_completion
        FROM events
        WHERE {where}
    """)


# ------------------------------------------------------------------------------------------------------------------------------------------------------
# Admin Endpoints

@api.get("/admin/overview")
async def admin_overview(x_admin_token: str = Header(default="")):
    _verify_admin_token(x_admin_token)
    return _fetchone("""
        SELECT
            COUNT(DISTINCT user_id) FILTER (WHERE user_id IS NOT NULL) AS total_users,
            COUNT(*) AS total_calls,
            COALESCE(SUM(cache_hit), 0) AS total_cache_hits,
            COALESCE(ROUND(AVG(cache_hit::numeric) * 100, 1), 0.0) AS hit_rate_pct,
            COALESCE(SUM(trim_saved + schema_tokens_saved), 0) AS total_tokens_saved,
            COALESCE(SUM(groq_prompt_tokens + groq_completion_tokens), 0) AS total_groq_tokens,
            COUNT(CASE WHEN DATE(timestamp) = CURRENT_DATE THEN 1 END) AS calls_today,
            COUNT(DISTINCT user_id) FILTER (WHERE user_id IS NOT NULL AND DATE(timestamp) = CURRENT_DATE) AS active_users_today
        FROM events
    """)


@api.get("/admin/users")
async def admin_users(x_admin_token: str = Header(default="")):
    _verify_admin_token(x_admin_token)
    return _fetch("""
        SELECT
            user_id,
            COUNT(*) AS total_calls,
            COALESCE(SUM(cache_hit), 0) AS cache_hits,
            COALESCE(ROUND(AVG(cache_hit::numeric) * 100, 1), 0.0) AS hit_rate_pct,
            COALESCE(SUM(trim_saved + schema_tokens_saved), 0) AS tokens_saved,
            COALESCE(SUM(groq_prompt_tokens), 0) AS groq_prompt_tokens,
            COALESCE(SUM(groq_completion_tokens), 0) AS groq_completion_tokens,
            MIN(timestamp) AS first_seen,
            MAX(timestamp) AS last_seen
        FROM events
        WHERE user_id IS NOT NULL AND user_id != 'unknown'
        GROUP BY user_id
        ORDER BY total_calls DESC
    """)


@api.get("/admin/user/{user_id}")
async def admin_user_drilldown(user_id: str,x_admin_token: str = Header(default="")):
    _verify_admin_token(x_admin_token)
    summary = _fetchone("""
        SELECT
            COUNT(*) AS total_calls,
            COALESCE(SUM(cache_hit), 0) AS cache_hits,
            COALESCE(SUM(trim_saved + schema_tokens_saved), 0) AS tokens_saved,
            COALESCE(SUM(groq_prompt_tokens), 0) AS groq_prompt_tokens,
            COALESCE(SUM(groq_completion_tokens), 0) AS groq_completion_tokens,
            MIN(timestamp) AS first_seen,
            MAX(timestamp) AS last_seen
        FROM events WHERE user_id = %s
    """, (user_id,))
    tools = _fetch("""
        SELECT tool_name, COUNT(*) AS calls, SUM(cache_hit) AS hits
        FROM events WHERE user_id = %s
        GROUP BY tool_name ORDER BY calls DESC
    """, (user_id,))
    events = _fetch("""
        SELECT timestamp, tool_name, query, cache_hit, trim_saved, schema_tokens_saved, success
        FROM events WHERE user_id = %s
        ORDER BY timestamp DESC LIMIT 50
    """, (user_id,))
    return {"summary": summary, "tools": tools, "recent_events": events}


@api.get("/admin/timeseries")
async def admin_timeseries(hours: int = 24,x_admin_token: str = Header(default="")):
    _verify_admin_token(x_admin_token)
    return _fetch("""
        SELECT
            to_char(date_trunc('hour', timestamp), 'YYYY-MM-DD HH24:00') AS hour,
            COUNT(DISTINCT user_id) AS active_users,
            COUNT(*) AS total_calls,
            COALESCE(SUM(cache_hit), 0) AS cache_hits,
            COALESCE(SUM(trim_saved + schema_tokens_saved), 0) AS tokens_saved
        FROM events
        WHERE timestamp >= NOW() - (%(hours)s || ' hours')::interval
        GROUP BY date_trunc('hour', timestamp)
        ORDER BY date_trunc('hour', timestamp) ASC
    """, {"hours": str(int(hours))})


@api.get("/admin/events")
async def admin_events(limit: int = 100,x_admin_token : str = Header(default="")):
    _verify_admin_token(x_admin_token)
    return _fetch("""
        SELECT user_id, timestamp, tool_name, query, cache_hit,
               trim_saved, schema_tokens_saved, success
        FROM events
        ORDER BY timestamp DESC LIMIT %s
    """, (limit,))


#------------------------------------------------------------------------------------------------------------------------------------------------------
# Shutdown

@api.post("/shutdown")
async def shutdown():
    os.kill(os.getpid(), signal.SIGTERM)
    return {"status": "shutting down"}



# ------------------------------------------------------------------------------------------------------------------------------------------------------
# Entry 

if __name__ == "__main__":
    admin_path = os.path.join(project_root, "src", "admin_front.py")
    admin_proc = subprocess.Popen(
        [
            sys.executable, "-m", "streamlit", "run", admin_path,
            "--server.port", "7738",
            "--server.headless", "true",
        ],
        cwd=project_root,
    )
    logger.info(f"[LAUNCHER] Admin dashboard started (pid {admin_proc.pid})")

    def _kill_admin():
        if admin_proc.poll() is None:
            admin_proc.terminate()

    atexit.register(_kill_admin)

    uvicorn.run(api, host="0.0.0.0", port=7737, workers=1)
    
