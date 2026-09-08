import os
import time
import uuid
import logging
import threading
import sqlite3
import requests
from contextlib import contextmanager
import urllib3
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

from token_optimise.config import settings

logger = logging.getLogger("token")

_storage_dir = os.environ.get(
    "TOKEN_STORAGE_DIR",
    os.path.join(os.path.expanduser("~"), ".token_optimise", "storage")
)
DB_PATH = os.path.join(_storage_dir, "token_events.db")
INGEST_URL = settings.token_ingest_url


CONVERSATION_TIMEOUT_MINUTES = 15
_current_conversation_id = None
_last_event_time = None
_conv_lock = threading.Lock()
_cached_collect_token: str = ""

def _get_or_create_conversation_id() -> str:
    global _current_conversation_id, _last_event_time
    with _conv_lock:
        now = time.time()
        if (
            _current_conversation_id is None
            or _last_event_time is None
            or (now - _last_event_time) > CONVERSATION_TIMEOUT_MINUTES * 60
        ):
            _current_conversation_id = str(uuid.uuid4())
        _last_event_time = now
        return _current_conversation_id


def get_connection() -> sqlite3.Connection:
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn


@contextmanager
def get_db():
    conn = get_connection()
    try:
        yield conn
    finally:
        conn.close()


def init_db(conn):
    conn.execute("""
        CREATE TABLE IF NOT EXISTS events (
            id  INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id     TEXT,
            timestamp   DATETIME DEFAULT CURRENT_TIMESTAMP,
            conversation_id     TEXT,
            tool_name   TEXT NOT NULL,
            query   TEXT,
            cache_hit   INTEGER DEFAULT 0,
            cache_similarity    REAL DEFAULT 0.0,
            tokens_before_trim  INTEGER DEFAULT 0,
            tokens_after_trim   INTEGER DEFAULT 0,
            trim_saved  INTEGER DEFAULT 0,
            schema_tokens_full   INTEGER DEFAULT 0,
            schema_tokens_selected INTEGER DEFAULT 0,
            schema_tokens_saved INTEGER DEFAULT 0,
            groq_prompt_tokens INTEGER DEFAULT 0,
            groq_completion_tokens  INTEGER DEFAULT 0,
            doc_id  TEXT,
            success INTEGER DEFAULT 1
        )
    """)
    for col in ["user_id", "conversation_id"]:
        try:
            conn.execute(f"ALTER TABLE events ADD COLUMN {col} TEXT")
        except Exception:
            pass
    conn.commit()
    logger.info(f"[DB] SQLite ready at {DB_PATH}")



def init_db_once() -> None:
    """Call once at server startup."""
    with get_db() as conn:
        init_db(conn)




def _post_to_cloud(data: dict):
    """Send event to AWS /collect endpoint."""
    if not INGEST_URL:
        return
    try:
        global _cached_collect_token
        if not _cached_collect_token:
            _env_path = os.path.join(
                os.path.expanduser("~"), ".token_optimise", ".env"
            )
            if os.path.exists(_env_path):
                with open(_env_path) as _f:
                    for _line in _f:
                        _line = _line.strip()
                        if _line.startswith("COLLECT_TOKEN="):
                            _cached_collect_token = _line.split("=", 1)[1].strip()
                            break

        if not _cached_collect_token:
            logger.debug("[DB] No COLLECT_TOKEN yet — skipping cloud ingest")
            return

        headers = {"X-Collect-Token": _cached_collect_token}
        requests.post(INGEST_URL, json=data, timeout=3, headers=headers, verify=False)
    except Exception as e:
        logger.warning(f"[DB] Cloud ingest failed (local SQLite has it): {e}")




def insert_event(**kwargs): 
    _uid = os.getenv("TOKEN_USER_ID", "")
    try:
        import uuid as _uuid_mod
        _uuid_mod.UUID(_uid)          
    except (ValueError, AttributeError):
        _uid = None                   
    kwargs.setdefault("user_id", _uid)
    kwargs.setdefault("conversation_id", _get_or_create_conversation_id())

    fields = [
        "user_id", "conversation_id",
        "tool_name", "query", "cache_hit", "cache_similarity",
        "tokens_before_trim", "tokens_after_trim", "trim_saved",
        "schema_tokens_full", "schema_tokens_selected", "schema_tokens_saved",
        "doc_id", "success",
        "groq_prompt_tokens", "groq_completion_tokens",
    ]

    data = {f: kwargs.get(f, None) for f in fields}

    # always write to local SQLite
    with get_db() as conn:
        placeholders = ", ".join(["?" for _ in fields])
        columns = ", ".join(fields)
        conn.execute(
            f"INSERT INTO events ({columns}) VALUES ({placeholders})",
            list(data.values()),
        )
        conn.commit()


    _post_to_cloud(data)
        
        
def _fetchall(conn, sql, params=()):
    rows = conn.execute(sql, params).fetchall()
    return [dict(r) for r in rows]



def _fetchone(conn, sql, params=()):
    row = conn.execute(sql, params).fetchone()
    return dict(row) if row else {}

         
def get_summary(conn):
    return _fetchone(conn, """
        SELECT
            COUNT(*) as total_calls,
            COALESCE(SUM(cache_hit), 0) as cache_hits,
            COALESCE(ROUND(AVG(cache_hit) * 100, 1), 0.0) as hit_rate_pct,
            COALESCE(SUM(trim_saved), 0) as total_trim_saved,
            COALESCE(SUM(schema_tokens_saved), 0) as total_schema_saved,
            COALESCE(SUM(trim_saved + schema_tokens_saved), 0) as total_tokens_saved
        FROM events
    """)



def get_recent_events(conn, limit=50):
    return _fetchall(
        conn, "SELECT * FROM events ORDER BY timestamp DESC LIMIT ?", (limit,)
    )

def get_tool_stats(conn):
    return _fetchall(conn,"""
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
    

def get_token_analysis(conn):
    rows = _fetchone(conn, """
        SELECT 
            COUNT(*) AS total_queries,
            COALESCE(SUM(schema_tokens_saved), 0) AS schema_saved,
            COALESCE(SUM(schema_tokens_full), 0) AS schema_full,
            COALESCE(SUM(schema_tokens_selected), 0) AS schema_selected,
            COALESCE(SUM(trim_saved), 0) AS trim_saved,
            COALESCE(SUM(tokens_before_trim), 0) AS tokens_before_trim,
            COALESCE(SUM(tokens_after_trim), 0) AS tokens_after_trim,
            COALESCE(SUM(cache_hit), 0) AS cache_hits,
            COUNT(CASE WHEN cache_hit = 0 THEN 1 END) as cache_misses
        FROM events
    """)
    
    schema_saved = rows.get("schema_saved",0)
    schema_full = rows.get("schema_full",0)
    schema_selected = rows.get("schema_selected",0)
    trim_saved = rows.get("trim_saved",0)
    tokens_before = rows.get("tokens_before_trim",0)
    tokens_after = rows.get("tokens_after_trim",0)
    cache_hits = rows.get("cache_hits",0)
    cache_misses = rows.get("cache_misses",0)
    total_queries = rows.get("total_queries",0)
    
    total_saved = schema_saved + trim_saved
    
    actual_without= schema_full + tokens_before
    actual_with = schema_selected + tokens_after
    
    pct_saved = round((total_saved / actual_without * 100), 1) if actual_without > 0 else 0.0

    return {
        "total_queries": total_queries,
        "cache_hits": cache_hits,
        "cache_misses": cache_misses,
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
    
def get_event_count(conn) -> int:
    """Quick row count for health check."""
    row = _fetchone(conn, "SELECT COUNT(*) AS cnt FROM events")
    return row.get("cnt", 0)

def get_conversation_stats(conn, limit=20):
    return _fetchall(conn, """
        SELECT
            conversation_id,
            MIN(timestamp) AS started_at,
            COUNT(*) AS total_calls,
            SUM(cache_hit)  AS cache_hits,
            SUM(trim_saved) AS trim_saved,
            SUM(schema_tokens_saved) AS schema_saved,
            SUM(trim_saved + schema_tokens_saved) AS total_saved
        FROM events
        WHERE conversation_id IS NOT NULL
        GROUP BY conversation_id
        ORDER BY started_at DESC
        LIMIT ?
    """, (limit,))

    
    
def get_groq_usage(conn):
    return _fetchone(conn, """
        SELECT
            COALESCE(SUM(groq_prompt_tokens), 0) AS total_prompt_tokens,
            COALESCE(SUM(groq_completion_tokens), 0)  AS total_completion_tokens,
            COALESCE(SUM(groq_prompt_tokens + groq_completion_tokens), 0) AS total_groq_tokens
        FROM events
    """)


def get_timeseries(conn, hours: int = 24):
    return _fetchall(conn, """
        SELECT
            strftime('%Y-%m-%d %H:00', timestamp) AS hour,
            COUNT(*) AS total_calls,
            COALESCE(SUM(cache_hit), 0)  AS cache_hits,
            COALESCE(SUM(schema_tokens_saved), 0) AS schema_saved,
            COALESCE(SUM(trim_saved), 0) AS trim_saved,
            COALESCE(SUM(groq_prompt_tokens + groq_completion_tokens), 0) AS groq_tokens
        FROM events
        WHERE timestamp >= datetime('now', ? || ' hours')
        GROUP BY hour
        ORDER BY hour ASC
    """, (f"-{hours}",))
    

    
def get_period_summary(conn, period: str = "today"):
    _safe = {
        "today": "date(timestamp) = date('now')",
        "yesterday": "date(timestamp) = date('now', '-1 day')",
        "week": "timestamp >= datetime('now', '-7 days')",
        "all": "1=1",
    }
    where = _safe.get(period, "1=1")
    return _fetchone(conn, f"""
        SELECT
            COUNT(*) AS total_calls,
            COALESCE(SUM(cache_hit), 0) AS cache_hits,
            COALESCE(SUM(schema_tokens_saved + trim_saved), 0) AS total_saved,
            COALESCE(SUM(groq_prompt_tokens), 0)  AS groq_prompt,
            COALESCE(SUM(groq_completion_tokens), 0) AS groq_completion
        FROM events
        WHERE {where}
    """)