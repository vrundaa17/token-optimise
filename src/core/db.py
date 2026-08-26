import sqlite3
import os
import logging
from config import PROJECT_ROOT

logger = logging.getLogger("token")

DB_PATH = os.path.join(PROJECT_ROOT, "storage", "token_events.db")
import time,uuid

CONVERSATION_TIMEOUT_MINUTES = 15
_current_conversation_id = None
_last_event_time = None

def _get_or_create_conversation_id():
    global _current_conversation_id, _last_event_time
    now = time.time()
    if (
        _current_conversation_id is None
        or _last_event_time is None
        or (now - _last_event_time) > CONVERSATION_TIMEOUT_MINUTES * 60
    ):
        _current_conversation_id = str(uuid.uuid4())[:8]
    _last_event_time = now
    return _current_conversation_id


import threading
_local = threading.local()

def get_thread_connection():
    if not hasattr(_local, 'conn') or _local.conn is None:
        _local.conn = get_connection()
        init_db(_local.conn)
    return _local.conn
  
    
def get_connection():
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn

def init_db(conn):
    conn.execute("""
        CREATE TABLE IF NOT EXISTS events (
            id  INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp   DATETIME DEFAULT CURRENT_TIMESTAMP,
            tool_name   TEXT NOT NULL,
            query   TEXT,
            cache_hit   INTEGER DEFAULT 0,
            cache_similarity    REAL DEFAULT 0.0,
            tokens_before_trim  INTEGER DEFAULT 0,
            tokens_after_trim   INTEGER DEFAULT 0,
            trim_saved  INTEGER DEFAULT 0,
            schema_tokens_full   INTEGER DEFAULT 0,
            schema_tokens_selected  INTEGER DEFAULT 0,
            schema_tokens_saved  INTEGER DEFAULT 0,
            groq_prompt_tokens   INTEGER DEFAULT 0,
            groq_completion_tokens INTEGER DEFAULT 0,
            doc_id   TEXT,
            success  INTEGER DEFAULT 1
        )
    """)
    try:
        conn.execute("ALTER TABLE events ADD COLUMN conversation_id TEXT")
        conn.execute("ALTER TABLE events ADD COLUMN groq_prompt_tokens INTEGER DEFAULT 0")
        conn.execute("ALTER TABLE events ADD COLUMN groq_completion_tokens INTEGER DEFAULT 0")
        conn.commit()
    except Exception:
        pass
    
    conn.commit()
    logger.info(f"[DB] initialized at {DB_PATH}")


def insert_event(**kwargs):
    conn = get_thread_connection()
    kwargs.setdefault("conversation_id", _get_or_create_conversation_id())
    fields = [
        "conversation_id",
        "tool_name", "query", "cache_hit", "cache_similarity",
        "tokens_before_trim", "tokens_after_trim", "trim_saved",
        "schema_tokens_full", "schema_tokens_selected", "schema_tokens_saved",
        "doc_id", "success",
        "groq_prompt_tokens", "groq_completion_tokens"
    ]
    data = {f: kwargs.get(f, None) for f in fields}
    placeholders = ", ".join(["?" for _ in fields])
    columns = ", ".join(fields)
    conn.execute(
        f"INSERT INTO events ({columns}) VALUES ({placeholders})",
        list(data.values())
    )
    conn.commit()
    
def close_thread_connection():
    if hasattr(_local, 'conn') and _local.conn is not None:
        _local.conn.close()
        _local.conn = None  
         
         
def get_summary(conn):
    return conn.execute("""
        SELECT
            COUNT(*) as total_calls,
            COALESCE(SUM(cache_hit), 0) as cache_hits,
            COALESCE(ROUND(AVG(cache_hit) * 100, 1), 0.0) as hit_rate_pct,
            COALESCE(SUM(trim_saved), 0) as total_trim_saved,
            COALESCE(SUM(schema_tokens_saved), 0) as total_schema_saved,
            COALESCE(SUM(trim_saved + schema_tokens_saved), 0) as total_tokens_saved
        FROM events
    """).fetchone()



def get_recent_events(conn, limit=50):
    return conn.execute("""
        SELECT * FROM events ORDER BY timestamp DESC LIMIT ?
    """, (limit,)).fetchall()


def get_tool_stats(conn):
    return conn.execute("""
        SELECT 
            tool_name,
            COUNT(*) as calls,
            SUM(cache_hit) as hits,
            SUM(trim_saved) as trim_saved,
            SUM(schema_tokens_saved) as schema_saved
        FROM events
        GROUP BY tool_name
        ORDER BY calls DESC
    """).fetchall()
    

def get_token_analysis(conn):
    rows = conn.execute("""
        SELECT 
            COUNT(*) as total_queries,
            COALESCE(SUM(schema_tokens_saved), 0) as schema_saved,
            COALESCE(SUM(schema_tokens_full), 0) as schema_full,
            COALESCE(SUM(schema_tokens_selected), 0) as schema_selected,
            COALESCE(SUM(trim_saved), 0) as trim_saved,
            COALESCE(SUM(tokens_before_trim), 0) as tokens_before_trim,
            COALESCE(SUM(tokens_after_trim), 0) as tokens_after_trim,
            COALESCE(SUM(cache_hit), 0) as cache_hits,
            COUNT(CASE WHEN cache_hit = 0 THEN 1 END) as cache_misses
        FROM events
    """).fetchone()
    
    schema_saved = rows["schema_saved"]
    schema_full = rows["schema_full"]
    schema_selected = rows["schema_selected"]
    trim_saved = rows["trim_saved"]
    tokens_before = rows["tokens_before_trim"]
    tokens_after = rows["tokens_after_trim"]
    cache_hits = rows["cache_hits"]
    cache_misses = rows["cache_misses"]
    total_queries = rows["total_queries"]
    
    total_saved = schema_saved + trim_saved
    
    actual_without= schema_full + tokens_before
    actual_with = schema_selected + tokens_after
    
    pct_saved = round((total_saved / actual_without * 100), 1) if actual_without > 0 else 0.0

    usd_per_token = 3 / 1_000_000       #sonnet4.6
    inr_per_token = usd_per_token * 84

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
        "cost_saved_usd": round(total_saved * usd_per_token, 6),
        "cost_saved_inr": round(total_saved * inr_per_token, 4)
    }
    
def get_event_count(conn) -> int:
    """Quick row count for health check."""
    row = conn.execute("SELECT COUNT(*) FROM events").fetchone()
    return row[0] if row else 0

def get_conversation_stats(conn, limit=20):
    return conn.execute("""
        SELECT
            conversation_id,
            MIN(timestamp) as started_at,
            COUNT(*) as total_calls,
            SUM(cache_hit) as cache_hits,
            SUM(trim_saved) as trim_saved,
            SUM(schema_tokens_saved) as schema_saved,
            SUM(trim_saved + schema_tokens_saved) as total_saved
        FROM events
        WHERE conversation_id IS NOT NULL
        GROUP BY conversation_id
        ORDER BY started_at DESC
        LIMIT ?
    """, (limit,)).fetchall()
    
    
def get_groq_usage(conn):
    row = conn.execute("""
            SELECT
                COALESCE(SUM(groq_prompt_tokens), 0) as total_prompt_tokens,
                COALESCE(SUM(groq_completion_tokens), 0) as total_completion_tokens,
                COALESCE(SUM(groq_prompt_tokens + groq_completion_tokens), 0) as total_groq_tokens
            FROM events
        """).fetchone()
    return dict(row)