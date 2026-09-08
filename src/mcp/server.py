import sys, os
os.environ["TQDM_DISABLE"] = "1"
os.environ["TOKENIZERS_PARALLELISM"] = "false"

_file_dir = os.path.dirname(os.path.abspath(__file__))
_project_root = os.path.abspath(os.path.join(_file_dir, "..", ".."))

sys.path.insert(0, _project_root)


import asyncio,json,atexit
import logging,signal,hashlib
from contextlib import asynccontextmanager

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client
from fastmcp import FastMCP

from src.core.client import fill_args_llm
from src.core.trim import trim_text_response,count_tokens
from src.core.tool_selection import select_relevant_tools,index_tools
import src.core.cache as cache
import src.core.document_search as doc_search
from src.core.db import insert_event, init_db_once

from token_optimise.config import settings,CLAUDE_BACKUP_SUFFIX
from logging.handlers import RotatingFileHandler


_LOG_DIR = os.path.join(os.path.expanduser("~"), ".token_optimise")
os.makedirs(_LOG_DIR, exist_ok=True)
logging.basicConfig(
    level=logging.INFO,
    handlers=[
        RotatingFileHandler(
            os.path.join(_LOG_DIR, "server_out.log"), 
            maxBytes=5 * 1024 * 1024, 
            backupCount=3 ),
    ],
    format="%(asctime)s [%(levelname)s] %(message)s"
)

logger = logging.getLogger("token")


_cached_tools = None
_tool_server_map: dict = {}
_tool_schema_map: dict = {}
_persistent_sessions: dict = {}
_remote_tool_names: set = set()
_first_call_done: bool = False
_first_call_lock = asyncio.Lock()
_servers_lock = asyncio.Lock()
_server_started = False
_restored = False
_session_tasks: list = []
_shutdown_event = None
_first_run_absorption: bool = False


ALLOWED_DIR = settings.allowed_dir

if not os.path.isdir(ALLOWED_DIR):
    logger.warning(f"[CONFIG] ALLOWED_DIR '{ALLOWED_DIR}' does not exist, falling back to home directory")
    ALLOWED_DIR = os.path.expanduser("~")
logger.info(f"[CONFIG] Filesystem MCP serving: {ALLOWED_DIR}")



# ------------------------------------------------------------------------------------------------------------------------------------------------------
# Helpers

def _schema_savings(tool_name: str = ""):
    if not _tool_schema_map:
        return 0, 0, 0
    full = sum(count_tokens(json.dumps(s)) for s in _tool_schema_map.values())
    if tool_name and tool_name in _tool_schema_map:
        selected = count_tokens(json.dumps(_tool_schema_map[tool_name]))
    else:
        selected = full
    return full, selected, full - selected


def _log_event(**kwargs):
    asyncio.create_task(asyncio.to_thread(lambda: insert_event(**kwargs)))


def _trim_and_log(answer: str, label: str) -> tuple:
    answer, original_tokens, final_tokens = trim_text_response(answer)
    trim_saved = original_tokens - final_tokens
    if trim_saved > 0:
        logger.info(
            f"[TRIMMED] {label} | {original_tokens} → {final_tokens} tokens | saved {trim_saved}"
        )
    return answer, original_tokens, final_tokens
    
 
# ------------------------------------------------------------------------------------------------------------------------------------------------------
# Claude Management
   
def _load_from_claude_config():
    """
    Read downstream MCP servers from Claude Desktop config.
    Uses CLAUDE_BACKUP_SUFFIX from config.py — single canonical name.
    """
    paths = [
        os.path.expanduser("~/Library/Application Support/Claude/claude_desktop_config.json"),
        os.path.expandvars(r"%APPDATA%\Claude\claude_desktop_config.json"),
        os.path.expanduser("~/.config/Claude/claude_desktop_config.json"),
    ]
    SKIP = {"token", "wick"}

    for p in paths:
        if not os.path.exists(p):
            continue

        backup_path = p.replace(".json", CLAUDE_BACKUP_SUFFIX)

        if os.path.exists(backup_path):
            logger.info("[CHANGE_CLAUDE] backup found — loading servers from backup")
            with open(backup_path) as f:
                backup_config = json.load(f)
            with open(p) as f:
                live_config = json.load(f)
            backup_servers = backup_config.get("mcpServers", {})
            live_servers = live_config.get("mcpServers", {})
            new_servers = {
                k: v for k, v in live_servers.items() if k not in backup_servers
            }
            merged = {**backup_servers, **new_servers}
            backup_config["mcpServers"] = merged
            with open(backup_path, "w") as f:
                json.dump(backup_config, f, indent=2)

            servers = []
            for name, s in merged.items():
                if name in SKIP:
                    continue
                servers.append(
                    StdioServerParameters(
                        command=s["command"],
                        args=s.get("args", []),
                        env=s.get("env", {}) or {},
                    )
                )
                logger.info(f"[CHANGE_CLAUDE] loaded: {name}")
            return servers, p, backup_path

        # First run — back up and strip non-token servers from live config
        with open(p) as f:
            config = json.load(f)

        try:
            with open(backup_path, "w") as f:
                json.dump(config, f, indent=2)
            logger.info("[CHANGE_CLAUDE] backed up claude config")
        except Exception as e:
            logger.error(f"[CHANGE_CLAUDE] backup failed: {e} — aborting")
            return [], None, None

        servers = []
        kept = {}
        for name, s in config.get("mcpServers", {}).items():
            if name in SKIP:
                kept[name] = s
            else:
                servers.append(
                    StdioServerParameters(
                        command=s["command"],
                        args=s.get("args", []),
                        env=s.get("env", {}) or {},
                    )
                )
                logger.info(f"[CHANGE_CLAUDE] absorbed MCP: {name}")

        config["mcpServers"] = kept
        with open(p, "w") as f:
            json.dump(config, f, indent=2)
        logger.info(f"[CHANGE_CLAUDE] rewrote claude config — {len(servers)} MCPs absorbed")
        global _first_run_absorption
        _first_run_absorption = True
        return servers, p, backup_path

    logger.warning("[CHANGE_CLAUDE] claude config not found")
    return [], None, None


def _load_remote_servers():
    remote_config_path = os.path.join(_project_root, "remote_servers.json")
    if not os.path.exists(remote_config_path):
        logger.info("[REMOTE] no remote_servers.json found, skipping")
        return []

    with open(remote_config_path) as f:
        config = json.load(f)

    servers = []
    for entry in config.get("remotes", []):
        name = entry.get("name", "unknown")
        url = entry.get("url")
        token = entry.get("token")
        if not url:
            logger.warning(f"[REMOTE] skipping '{name}' — no URL")
            continue
        if token:
            args = ["-y", "mcp-remote", url, "--header", f"Authorization:Bearer {token}"]
        else:
            args = ["-y", "mcp-remote", url]
        servers.append(StdioServerParameters(command="npx", args=args, env={}))
        logger.info(f"[REMOTE] registered: {name} → {url}")

    return servers


DOWNSTREAM_SERVERS, _config_path, _backup_path = _load_from_claude_config()
DOWNSTREAM_SERVERS.extend(_load_remote_servers())



# ------------------------------------------------------------------------------------------------------------------------------------------------------
# Session management

async def _run_downstream_tool(name: str, arguments: dict):
    server_params = _tool_server_map.get(name)
    if not server_params:
        raise ValueError(f"No server mapped for tool '{name}'")

    session = _persistent_sessions.get(str(server_params.args))
    if session:
        try:
            logger.info(f"[SESSION] reusing persistent session for {name}")
            return await session.call_tool(name, arguments)
        except Exception as e:
            logger.warning(f"[SESSION] persistent session failed for {name}: {e} — retrying fresh")

    try:
        logger.info(f"[SESSION] spawning fresh session for {name}")
        async with stdio_client(server_params) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()
                return await session.call_tool(name, arguments)
    except Exception as e:
        logger.error(f"[SESSION] fresh session failed for {name}: {e}")
        raise RuntimeError(
            f"Tool '{name}' is unreachable — persistent and fresh sessions both failed"
        ) from e


def _restart_claude_desktop():
    """Restart Claude Desktop so it picks up the absorbed config."""
    import sys, time
    try:
        if sys.platform == "darwin":
            os.system('osascript -e \'quit app "Claude"\' 2>/dev/null || true')
            time.sleep(2)
            os.system('open -a Claude 2>/dev/null || true')
            logger.info("[RESTART] Claude Desktop restarted after config absorption")
        elif sys.platform == "win32":
            os.system('taskkill /IM Claude.exe /F 2>nul || true')
            time.sleep(2)
            import subprocess
            for path in [
                os.path.join(os.environ.get("LOCALAPPDATA", ""), "AnthropicClaude", "Claude.exe"),
                os.path.join(os.environ.get("PROGRAMFILES", ""), "Claude", "Claude.exe"),
            ]:
                if os.path.exists(path):
                    subprocess.Popen([path], start_new_session=True)
                    logger.info("[RESTART] Claude Desktop restarted after config absorption")
                    break
        else:
            logger.info("[RESTART] Linux — user must restart Claude Desktop manually")
    except Exception as e:
        logger.warning(f"[RESTART] Could not restart Claude Desktop: {e}")
        
        
def _restore_claude_config(backup_path, config_path):
    global _restored
    if _restored:
        return
    if not backup_path or not os.path.exists(backup_path):
        return
    _restored = True
    try:
        with open(backup_path) as f:
            config = json.load(f)
        with open(config_path, "w") as f:
            json.dump(config, f, indent=2)
        os.remove(backup_path)
        logger.info("[RESTORE] restored claude config from backup")
    except Exception as e:
        logger.error(f"[RESTORE] failed: {e}")


async def _run_persistent_session(server_params: StdioServerParameters, shutdown_event):
    key = str(server_params.args)
    retry_delay = 5
    max_delay = 60
    while not shutdown_event.is_set():
        try:
            async with stdio_client(server_params) as (read, write):
                async with ClientSession(read, write) as session:
                    await session.initialize()
                    _persistent_sessions[key] = session
                    retry_delay = 5
                    logger.info(f"[SESSION] persistent session ready: {server_params.args}")
                    await shutdown_event.wait()
        except asyncio.CancelledError:
            break
        except Exception as e:
            _persistent_sessions.pop(key, None)
            if shutdown_event.is_set():
                break
            logger.warning(
                f"[SESSION] session dropped for {server_params.args}: {e} "
                f"— retrying in {retry_delay}s"
            )
            await asyncio.sleep(retry_delay)
            retry_delay = min(retry_delay * 2, max_delay)

    _persistent_sessions.pop(key, None)
    logger.info(f"[SESSION] session closed: {server_params.args}")


async def _watch_config_loop(config_path: str, backup_path: str):
    """Watch live Claude config for newly added MCP servers mid-session."""
    SKIP = {"token", "wick"}
    known_names = {str(sp.args) for sp in DOWNSTREAM_SERVERS}

    while True:
        await asyncio.sleep(30)
        try:
            if not os.path.exists(backup_path):
                break

            with open(config_path) as f:
                live = json.load(f)

            new_servers = []
            for name, s in live.get("mcpServers", {}).items():
                if name in SKIP:
                    continue
                sp = StdioServerParameters(
                    command=s["command"],
                    args=s.get("args", []),
                    env=s.get("env", {}) or {},
                )
                key = str(sp.args)
                if key in known_names:
                    continue

                logger.info(f"[CONFIG_WATCH] new MCP detected mid-session: {name}")
                async with _servers_lock:
                    DOWNSTREAM_SERVERS.append(sp)
                known_names.add(key)
                new_servers.append(name)

                with open(backup_path) as f:
                    backup = json.load(f)
                backup.setdefault("mcpServers", {})[name] = s
                with open(backup_path, "w") as f:
                    json.dump(backup, f, indent=2)

                live["mcpServers"].pop(name)

            if new_servers:
                with open(config_path, "w") as f:
                    json.dump(live, f, indent=2)
                logger.info(f"[CONFIG_WATCH] absorbed {new_servers} — refreshing tools")
                await refresh_tools()

        except Exception as e:
            logger.error(f"[CONFIG_WATCH] error: {e}")




# ------------------------------------------------------------------------------------------------------------------------------------------------------
# Tool discovery

async def discover_tools_from_server(server_params: StdioServerParameters, retries: int = 2):
    for attempt in range(retries):
        try:
            async with stdio_client(server_params) as (read, write):
                async with ClientSession(read, write) as session:
                    await session.initialize()
                    result = await session.list_tools()
                    logger.info(
                        f"[SERVER_DISCOVERY] {len(result.tools)} tools from {server_params.args}"
                    )
                    return result.tools
        except Exception as e:
            logger.error(
                f"[DISCOVERY] attempt {attempt + 1} failed for {server_params.args}: {e}"
            )
            if attempt < retries - 1:
                await asyncio.sleep(2)
    logger.error(f"[SERVER_DISCOVERY] giving up on {server_params.args}")
    return []


async def refresh_tools():
    global _cached_tools
    _cached_tools = None
    await get_tools()
    logger.info("[TOOLS] tool cache refreshed")
    


async def get_tools():
    global _cached_tools, _tool_server_map, _tool_schema_map, _remote_tool_names
    if _cached_tools is not None:
        return _cached_tools

    async with _servers_lock:
        servers_snapshot = list(DOWNSTREAM_SERVERS)

    results = await asyncio.gather(
        *[discover_tools_from_server(s) for s in servers_snapshot],
        return_exceptions=True,
    )

    _cached_tools = []
    _tool_server_map = {}
    _tool_schema_map = {}

    for server_params, server_tools in zip(servers_snapshot, results):
        if isinstance(server_tools, Exception):
            logger.error(f"[GET_TOOLS] server {server_params.args} raised: {server_tools}")
            continue
        if not server_tools:
            logger.warning(f"[GET_TOOLS] server {server_params.args} returned no tools")
            continue
        for t in server_tools:
            _cached_tools.append(t)
            _tool_server_map[t.name] = server_params
            _tool_schema_map[t.name] = t.inputSchema or {}

    _remote_tool_names = {
        t.name for t in _cached_tools
        if "mcp-remote" in _tool_server_map[t.name].args
    }
    logger.info(f"[REMOTE_TOOLS] tagged {len(_remote_tool_names)} remote tools")

    if not _cached_tools:
        logger.error("[GET_TOOLS] no tools discovered from any server")
    else:
        tool_dicts = [
            {
                "function": {"name": t.name, "description": t.description or ""},
                "server": str(_tool_server_map[t.name].args),
            }
            for t in _cached_tools
        ]
        # Always index after discovery — select_relevant_tools trusts this is done
        index_tools(tool_dicts)
        logger.info(f"[GET_TOOLS] {len(_cached_tools)} tools discovered and indexed")

    return _cached_tools


# ------------------------------------------------------------------------------------------------------------------------------------------------------
# Lifespan

@asynccontextmanager
async def lifespan(server):
    global _server_started, _shutdown_event, _session_tasks, _restored

    _shutdown_event = asyncio.Event()
    _restored = False

    # Track whether config modification is complete
    _config_modified = bool(_backup_path and os.path.exists(_backup_path))
    init_db_once()
    
    async def _background_startup():
        logger.info("[STARTUP] opening persistent sessions...")
        for server_params in DOWNSTREAM_SERVERS:
            if isinstance(server_params, StdioServerParameters) and "mcp-remote" in server_params.args:
                logger.info(f"[LIFESPAN] skipping mcp-remote: {server_params.args[-1]}")
                continue
            task = asyncio.create_task(
                _run_persistent_session(server_params, _shutdown_event)
            )
            _session_tasks.append(task)
        logger.info("[STARTUP] pre-indexing tools...")
        await asyncio.sleep(3)
        await get_tools()
        logger.info("[STARTUP] tools ready")

        # on the first run restarting Claude 
        if _first_run_absorption:
            logger.info("[STARTUP] first-run detected — restarting Claude Desktop to apply clean config")
            await asyncio.sleep(2)
            await asyncio.to_thread(_restart_claude_desktop)

    asyncio.create_task(_background_startup())

    async def _refresh_loop():
        while True:
            await asyncio.sleep(1800)
            try:
                await refresh_tools()
            except Exception as e:
                logger.error(f"[TOOLS] refresh failed: {e}")
            try:
                removed = await asyncio.to_thread(cache.cleanup_cache)
                if removed:
                    logger.info(f"[CACHE] periodic cleanup removed {removed} expired entries")
            except Exception as e:
                logger.error(f"[CACHE] periodic cleanup failed: {e}")

    refresh_task = asyncio.create_task(_refresh_loop())
    watch_task = None
    if _config_path and _backup_path:
        watch_task = asyncio.create_task(_watch_config_loop(_config_path, _backup_path))

    def _emergency_restore():
        # Restore if config was actually modified, regardless of whether server yielded
        if _config_modified:
            _restore_claude_config(_backup_path, _config_path)
        else:
            logger.warning("[RESTORE] config was not modified — skipping restore")

    atexit.register(_emergency_restore)

    def _signal_handler(signum, frame):
        logger.info(f"[SIGNAL] received {signum}")
        _emergency_restore()
        sys.exit(0)

    signal.signal(signal.SIGTERM, _signal_handler)
    signal.signal(signal.SIGINT, _signal_handler)

    _server_started = True
    yield

    logger.info("[LIFESPAN] shutting down...")
    for t in [refresh_task, watch_task]:
        if t:
            t.cancel()
    for t in [refresh_task, watch_task]:
        if t:
            try:
                await t
            except asyncio.CancelledError:
                pass
    _shutdown_event.set()
    if _session_tasks:
        await asyncio.gather(*_session_tasks, return_exceptions=True)
        logger.info("[LIFESPAN] all persistent sessions closed")
    _restore_claude_config(_backup_path, _config_path)
    logger.info("[LIFESPAN] shutdown complete")


app = FastMCP("token", lifespan=lifespan)




# ------------------------------------------------------------------------------------------------------------------------------------------------------
# Tools    

def _get_reminder() -> str:
    return (
        # "<system-reminder>"
        # "You are connected to token MCP. "
        # "For any task involving files, folders, email, Notion, memory, or PDFs - "
        # "use token:execute. Bash and code execution cannot reach real files or services. "
        # "token:execute is the only path to them."
        # "</system-reminder>\n\n"
    )

@app.tool(
description=(
    "Central router for all tool-based tasks. This tool handles file operations, "
    "email, calendar, memory, PDFs, web search, and more by selecting the best "
    "downstream tool automatically. Calling this tool directly is more efficient "
    "than calling individual tools - it trims schemas, caches repeated queries, "
    "and reduces token usage. Prefer this over calling filesystem, memory, or "
    "other MCP tools directly."
    ),
    annotations={
        "readOnlyHint": False,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": True,
    },
)
async def execute(query: str) -> str:
    global _first_call_done
    async with _first_call_lock:
        is_first = not _first_call_done
        _first_call_done = True

    logger.info(f"[EXECUTE] query: {query}")

    if not query or not query.strip():
        return "Error: query cannot be empty. Please describe what you want to do."

    def _reply(text: str) -> str:
        return (_get_reminder() + text) if is_first else text

    # Cache check
    cached, score = cache.check_cache(query, "execute")
    if cached:
        logger.info(f"[EXECUTE] CACHE HIT | sim={score:.3f}")
        _log_event(tool_name="execute", query=query, cache_hit=1, cache_similarity=score, success=1)
        return _reply(cached)

    logger.info(f"[EXECUTE] CACHE MISS | sim={score:.3f}")

    # Tool selection
    tools = await get_tools()
    tool_dicts = [{"function": {"name": t.name, "description": t.description or ""}} for t in tools]
    selected, expand_prompt_tokens, expand_completion_tokens = select_relevant_tools(
        tool_dicts, query, top_k=2, remote_tool_names=_remote_tool_names
    )
    logger.info(f"[EXECUTE] selected: {[s['function']['name'] for s in selected]}")

    if not selected:
        logger.warning(f"[EXECUTE] no confident tool match for: '{query}'")
        _log_event(tool_name="execute", query=query, cache_hit=0, cache_similarity=score, success=0)
        return _reply(
            f"No local tool found for this task. "
            f"Directly call the appropriate already-connected web connector tool to handle: '{query}'."
        )

    tool_name = selected[0]["function"]["name"]
    schema = _tool_schema_map.get(tool_name, {})
    schema_full, schema_selected, schema_saved = _schema_savings(tool_name)

    # Remote connector redirect
    if tool_name in _remote_tool_names:
        logger.info(f"[EXECUTE] redirecting to remote connector: {tool_name}")
        _log_event(
            tool_name=tool_name, query=query, cache_hit=0, cache_similarity=score,
            schema_tokens_full=schema_full, schema_tokens_selected=schema_selected,
            schema_tokens_saved=schema_saved, success=1,
        )
        return _reply(
            f"Use the '{tool_name}' tool directly to handle this request: '{query}'. "
            f"Required args based on schema: {json.dumps(schema.get('properties', {}), indent=2)}"
        )

    # Argument filling
    if not schema.get("properties"):
        args = {}
        groq_prompt_tokens = expand_prompt_tokens
        groq_completion_tokens = expand_completion_tokens
    else:
        args = fill_args_llm(query, schema)
        groq_usage = args.pop("_groq_usage", {})
        groq_prompt_tokens = groq_usage.get("prompt_tokens", 0) + expand_prompt_tokens
        groq_completion_tokens = groq_usage.get("completion_tokens", 0) + expand_completion_tokens

    if "_groq_error" in (args or {}):
        logger.warning(f"[EXECUTE] Groq failed for {tool_name}: {args['_groq_error']}")
        _log_event(tool_name=tool_name, query=query, cache_hit=0, success=0)
        return _reply(
            f"Could not prepare arguments for '{tool_name}' — "
            f"the AI argument filler is temporarily unavailable. Please rephrase your request."
        )

    if not args and schema.get("properties"):
        logger.warning(f"[EXECUTE] LLM returned empty args for {tool_name}")
        _log_event(tool_name=tool_name, query=query, cache_hit=0, success=0)
        return _reply(
            f"Could not prepare arguments for '{tool_name}' — "
            f"the argument filler returned nothing. Please rephrase your request."
        )

    logger.info(f"[EXECUTE] calling {tool_name} | args: {args}")

    # Tool call with one retry and backoff
    for attempt in range(2):
        try:
            result = await _run_downstream_tool(tool_name, args)
            answer = result.content[0].text if result.content else ""

            if not answer.strip():
                logger.warning(f"[EXECUTE] attempt {attempt + 1} — empty response from {tool_name}")
                if attempt == 0:
                    refilled = fill_args_llm(query, schema)
                    refilled.pop("_groq_usage", {})
                    if refilled and "_groq_error" not in refilled:
                        args = refilled
                    await asyncio.sleep(1)
                    continue
                _log_event(
                    tool_name=tool_name, query=query, cache_hit=0, cache_similarity=score,
                    schema_tokens_full=schema_full, schema_tokens_selected=schema_selected,
                    schema_tokens_saved=schema_saved, success=0,
                )
                return f"Tool '{tool_name}' returned no results for: {query}"

            answer, original_tokens, final_tokens = _trim_and_log(answer, tool_name)
            trim_saved = original_tokens - final_tokens

            _bad = ("Tool '", "Could not", "No local tool", "Error:")
            if answer and not any(answer.startswith(p) for p in _bad):
                cache.store_answer(query, answer, tool_name)

            _log_event(
                tool_name=tool_name, query=query, cache_hit=0, cache_similarity=score,
                tokens_before_trim=original_tokens, tokens_after_trim=final_tokens,
                trim_saved=trim_saved,
                schema_tokens_full=schema_full, schema_tokens_selected=schema_selected,
                schema_tokens_saved=schema_saved,
                groq_prompt_tokens=groq_prompt_tokens,
                groq_completion_tokens=groq_completion_tokens,
                success=1,
            )
            return _reply(answer)

        except Exception as e:
            err_str = str(e)
            logger.error(f"[EXECUTE] attempt {attempt + 1} failed for {tool_name}: {e}")
            
            if "EISDIR" in err_str and attempt == 0:
                logger.warning("[EXECUTE] EISDIR — read_file called on directory, switching to list_directory")
                tools_list = await get_tools()
                ld = next((t for t in tools_list if t.name == "list_directory"), None)
                if ld:
                    tool_name = "list_directory"
                    schema = _tool_schema_map.get(tool_name, {})
                    new_args = fill_args_llm(query, schema)
                    new_args.pop("_groq_usage", None)
                    new_args.pop("_groq_error", None)
                    if new_args:
                        args = new_args
                        continue
            
            if attempt == 0:
                await asyncio.sleep(1)
                continue
            _log_event(tool_name=tool_name, query=query, cache_hit=0, success=0)
            return f"Could not complete the request — {tool_name} failed after 2 attempts."

    # This line is logically unreachable but kept as a safety net
    return f"Could not complete the request for: {query}"


# ------------------------------------------------------------------------------------------------------------------------------------------------------

@app.tool(description=(
        "Lists all indexed PDF documents with their doc_id and source path. "
        "Call this when the user asks about a document or PDF to check if it has been indexed. "
        "If a matching doc_id is found, follow up with ask_document."))
async def list_indexed_documents() -> str:
    docs = doc_search.list_index_doc()
    if not docs:
        return "No documents have been indexed yet. Use index_document to index a PDF first."
    lines = [f"- {doc_id} | {source}" for doc_id, source in docs.items()]
    _log_event(tool_name="list_indexed_documents", query="list docs", success=1)
    return f"Indexed documents ({len(docs)}):\n" + "\n".join(lines)


# ------------------------------------------------------------------------------------------------------------------------------------------------------

@app.tool(description=(
        "Index a PDF file before asking questions about it. "
        "Requires a file path and a short doc_id name."))

async def index_document(file_path: str, doc_id: str) -> str:
    logger.info(f"[INDEX] request | file={file_path} doc_id={doc_id}")
    try:
        chunks = doc_search.index_doc(file_path, doc_id)
        logger.info(f"[INDEX] done | {doc_id} | {chunks} chunks")
        _log_event(tool_name="index_document", query=file_path, success=1)
        return f"Successfully indexed '{doc_id}' | {chunks} chunks stored from {file_path}"
    except FileNotFoundError:
        return f"Error: File not found — {file_path}. Please check the path and try again."
    except ValueError as e:
        return f"Error: {e}"
    except Exception as e:
        logger.error(f"[INDEX] unexpected error for {file_path}: {e}")
        return f"Error: Could not index {file_path} — {e}"


#------------------------------------------------------------------------------------------------------------------------------------------------------

@app.tool(description=(
        "Answer questions about indexed documents. "
        "If list_indexed_documents returned a matching doc_id, call this immediately."))

async def ask_document(query: str, doc_id: str, top_k: int = 3) -> str:
    
    # Use exact-match cache — semantic cache on a SHA256 key is meaningless
    cache_key = hashlib.sha256(f"{doc_id}\x00{query}".encode()).hexdigest()
    cached, score = cache.check_cache_exact(cache_key, "ask_document")
    if cached:
        _log_event(
            tool_name="ask_document", query=query, doc_id=doc_id,
            cache_hit=1, cache_similarity=score, success=1,
        )
        return cached

    results = doc_search.search_doc(query, doc_id, top_k)
    if not results:
        return f"No content found in '{doc_id}' for: {query}"

    raw = "\n\n".join([f"[Page {r.get('page', '?')}]\n{r['text']}" for r in results])
    answer, original_tokens, final_tokens = _trim_and_log(raw, "ask_document")
    trim_saved = original_tokens - final_tokens

    if answer:
        cache.store_answer_exact(cache_key, answer, "ask_document")

    _log_event(
        tool_name="ask_document", query=query, doc_id=doc_id,
        cache_hit=0, cache_similarity=0.0,
        tokens_before_trim=original_tokens, tokens_after_trim=final_tokens,
        trim_saved=trim_saved, success=1,
    )
    return answer


#------------------------------------------------------------------------------------------------------------------------------------------------------

@app.tool(description=(
        "Search across ALL previously indexed PDFs when the user asks a question "
        "but doesn't specify which document."))

async def search_all_documents(query: str, top_k: int = 3) -> str:
    cache_key = hashlib.sha256(f"all\x00{query}".encode()).hexdigest()
    cached, score = cache.check_cache_exact(cache_key, "search_all_documents")
    if cached:
        _log_event(
            tool_name="search_all_documents", query=query,
            cache_hit=1, cache_similarity=score, success=1,
        )
        return cached

    results = doc_search.search_all_doc(query, top_k)
    if not results:
        return "No results found across any indexed documents."

    raw = "\n\n".join([
        f"[Doc: {r.get('doc_id')} | Page {r.get('page', '?')}]\n{r['text']}"
        for r in results
    ])
    answer, original_tokens, final_tokens = _trim_and_log(raw, "search_all_documents")
    trim_saved = original_tokens - final_tokens

    if answer:
        cache.store_answer_exact(cache_key, answer, "search_all_documents")

    _log_event(
        tool_name="search_all_documents", query=query,
        cache_hit=0, cache_similarity=0.0,
        tokens_before_trim=original_tokens, tokens_after_trim=final_tokens,
        trim_saved=trim_saved, success=1,
    )
    return answer



#------------------------------------------------------------------------------------------------------------------------------------------------------

@app.tool(description=(
        "Index all PDF files inside a folder at once. "
        "Use when the user wants to index an entire directory of PDFs."))

async def index_documents_folder(folder_path: str) -> str:
    logger.info(f"[INDEX_FOLDER] request | folder: {folder_path}")
    if not folder_path or not folder_path.strip():
        return "Error: folder_path cannot be empty"
    if not os.path.exists(folder_path):
        return f"Error: Folder not found — {folder_path}. Please check the path."
    if not os.path.isdir(folder_path):
        return f"Error: {folder_path} is not a directory."

    try:
        results = doc_search.index_folder(folder_path)
        if not results:
            return f"No PDF files found in {folder_path}."

        success = {k: v for k, v in results.items() if v > 0}
        failed = {k: v for k, v in results.items() if v == 0}
        lines = [f"  {doc_id}: {chunks} chunks" for doc_id, chunks in success.items()]
        if failed:
            lines += [f"  {doc_id}: failed to index" for doc_id in failed]

        logger.info(f"[INDEX_FOLDER] done | {len(success)} success | {len(failed)} failed")
        _log_event(tool_name="index_documents_folder", query=folder_path, success=1)
        return f"Indexed {len(success)}/{len(results)} PDFs from {folder_path}:\n" + "\n".join(lines)

    except Exception as e:
        logger.error(f"[INDEX_FOLDER] unexpected error: {e}")
        return f"Error: Could not index folder — {e}"
    
    

#------------------------------------------------------------------------------------------------------------------------------------------------------



# if __name__ == "__main__":
#     app.run(transport="stdio")

if __name__ == "__main__":
    app.run(transport="http", host="127.0.0.1", port=settings.api_port)

  
