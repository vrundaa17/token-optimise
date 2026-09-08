import os, sys, signal, threading

PROVIDERS = {
    "1": ("Groq (free, recommended)", "groq", "GROQ_API_KEY", "https://console.groq.com", "groq/llama-3.3-70b-versatile"),
    "2": ("OpenAI", "openai", "OPENAI_API_KEY", "https://platform.openai.com/api-keys", "openai/gpt-4o-mini"),
    "3": ("Anthropic / Claude", "anthropic", "ANTHROPIC_API_KEY", "https://console.anthropic.com", "anthropic/claude-3-5-haiku-20241022"),
    "4": ("DeepSeek","deepseek", "DEEPSEEK_API_KEY", "https://platform.deepseek.com", "deepseek/deepseek-chat"),
    "5": ("Ollama (local, no key)",   "ollama", "", "", "ollama/llama3"),
}

def _bootstrap_env():
    token_dir = os.path.join(os.path.expanduser("~"), ".token_optimise")
    env_path = os.path.join(token_dir, ".env")

    if not os.path.exists(env_path):
        print()
        print("🦾 Token-Optime — First-time setup")
        print("=" * 40)
        print("Choose your AI provider:")
        for k, (label, *_) in PROVIDERS.items():
            print(f"  {k}. {label}")
        print()
        choice = input("Enter number [1]: ").strip() or "1"
        label, provider, key_var, key_url, default_model = PROVIDERS.get(choice, PROVIDERS["1"])

        api_key = ""
        if key_var:
            print(f"\nGet your key at: {key_url}")
            api_key = input(f"Paste your {key_var}: ").strip()
            if not api_key:
                print("❌ No key entered. Exiting.")
                sys.exit(1)

            print(f"\nWhich folder should Token-Optime have access to?")
            print(f"  Press Enter to use your home folder ({os.path.expanduser('~')})")
            print(f"  Or type a full path like /Users/yourname/Documents")
            allowed = input("Folder path: ").strip()
            if not allowed:
                allowed = os.path.expanduser("~")

            while not os.path.isdir(allowed):
                print(f"❌ '{allowed}' is not a valid folder path. Try again or press Enter for home folder.")
                allowed = input("Folder path: ").strip()
                if not allowed:
                    allowed = os.path.expanduser("~")
                    break

        os.makedirs(token_dir, exist_ok=True)
        with open(env_path, "w") as f:
            if api_key:
                f.write(f"{key_var}={api_key}\n")
            f.write(f"ALLOWED_DIR={allowed}\n")
            f.write("EMBEDDER=all-MiniLM-L6-v2\n")
            f.write(f"LLM_MODEL={default_model}\n")

        print(f"✅ Saved to {env_path}")
        print()

        # Telemetry — only on first-time setup, non-blocking
        try:
            from token_optimise.config import settings as _s
            import uuid as _uuid
            _uid_path = os.path.join(token_dir, "user_id")
            
            if os.path.exists(_uid_path):
                _uid = open(_uid_path).read().strip()
            else:
                _uid = str(_uuid.uuid4())
                os.makedirs(token_dir, exist_ok=True)
                with open(_uid_path, "w") as _f:
                    _f.write(_uid)
                    
            if _s.token_ingest_url:
                
                def _register():
                    try:
                        __import__("requests").post(
                            _s.token_ingest_url.replace("/collect", "/register"),
                            json={"user_id": _uid}, timeout=5
                        )
                    except Exception:
                        pass
                threading.Thread(target=_register, daemon=True).start()
        except Exception:
            pass


    # Load env file into os.environ — runs every time
    with open(env_path) as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, _, v = line.partition("=")
            k = k.strip()
            if k not in os.environ:
                os.environ[k] = v.strip()

_bootstrap_env()


import json
import shutil
import subprocess
import time
import importlib.util
from token_optimise.config import CLAUDE_BACKUP_SUFFIX, settings

HOME = os.path.expanduser("~")
TOKEN_DIR = os.path.join(HOME, ".token_optimise")
USER_ID_FILE = os.path.join(TOKEN_DIR, "user_id")
STORAGE_DIR = os.path.join(TOKEN_DIR, "storage")
USER_ENV_FILE = os.path.join(TOKEN_DIR, ".env")

if sys.platform == "darwin":
    CLAUDE_CONFIG = os.path.join(
        HOME, "Library", "Application Support", "Claude", "claude_desktop_config.json"
    )
elif sys.platform == "win32":
    CLAUDE_CONFIG = os.path.join(
        os.environ.get("APPDATA", ""), "Claude", "claude_desktop_config.json"
    )
else:
    CLAUDE_CONFIG = os.path.join(HOME, ".config", "Claude", "claude_desktop_config.json")


def register_user(user_id: str, ingest_url: str) -> str:
    import requests as _req

    register_url = ingest_url.replace("/collect", "/register")
    try:
        r = _req.post(register_url, json={"user_id": user_id}, timeout=5)
        token = r.json().get("token", "")
    except Exception as e:
        print(f"[TOKEN] Could not reach registration server: {e}")
        print("[TOKEN] Telemetry disabled — will retry on next run.")
        return ""

    if token:
        os.makedirs(TOKEN_DIR, exist_ok=True)
        existing = {}
        if os.path.exists(USER_ENV_FILE):
            with open(USER_ENV_FILE) as f:
                for line in f:
                    line = line.strip()
                    if "=" in line and not line.startswith("#"):
                        k, _, v = line.partition("=")
                        existing[k.strip()] = v.strip()
        existing["COLLECT_TOKEN"] = token
        with open(USER_ENV_FILE, "w") as f:
            for k, v in existing.items():
                f.write(f"{k}={v}\n")
        print("[TOKEN] Registered successfully.")

    return token


def get_or_create_user_id() -> str:
    import uuid
    os.makedirs(TOKEN_DIR, exist_ok=True)
    if os.path.exists(USER_ID_FILE):
        with open(USER_ID_FILE) as f:
            uid = f.read().strip()
            if uid:
                return uid
    uid = str(uuid.uuid4())
    with open(USER_ID_FILE, "w") as f:
        f.write(uid)
    print(f"[TOKEN] New user ID created: {uid}")
    return uid


def save_api_key(key_var: str, api_key: str) -> None:
    os.makedirs(TOKEN_DIR, exist_ok=True)
    existing = {}
    if os.path.exists(USER_ENV_FILE):
        with open(USER_ENV_FILE) as f:
            for line in f:
                line = line.strip()
                if "=" in line and not line.startswith("#"):
                    k, _, v = line.partition("=")
                    existing[k.strip()] = v.strip()
    existing[key_var] = api_key
    with open(USER_ENV_FILE, "w") as f:
        for k, v in existing.items():
            f.write(f"{k}={v}\n")
    print(f"[TOKEN] {key_var} saved to {USER_ENV_FILE}")

def change_provider() -> None:
    """Let the user switch to a different AI provider."""
    print()
    print("🔄 Change AI Provider")
    print("=" * 40)
    print("Choose your new AI provider:")
    for k, (label, *_) in PROVIDERS.items():
        print(f"  {k}. {label}")
    print()
    choice = input("Enter number [1]: ").strip() or "1"
    label, provider, key_var, key_url, default_model = PROVIDERS.get(choice, PROVIDERS["1"])

    api_key = ""
    if key_var:
        print(f"\nGet your key at: {key_url}")
        api_key = input(f"Paste your {key_var}: ").strip()
        if not api_key:
            print("❌ No key entered. Aborting.")
            return

    # Read existing .env, strip ALL old provider keys and LLM_MODEL, keep the rest
    existing = {}
    if os.path.exists(USER_ENV_FILE):
        with open(USER_ENV_FILE) as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                k, _, v = line.partition("=")
                existing[k.strip()] = v.strip()

    # Remove all old provider keys and old model
    for old_key in ("GROQ_API_KEY", "OPENAI_API_KEY", "ANTHROPIC_API_KEY", "DEEPSEEK_API_KEY", "LLM_MODEL"):
        existing.pop(old_key, None)

    # Write new provider
    if api_key:
        existing[key_var] = api_key
    existing["LLM_MODEL"] = default_model

    os.makedirs(TOKEN_DIR, exist_ok=True)
    with open(USER_ENV_FILE, "w") as f:
        for k, v in existing.items():
            f.write(f"{k}={v}\n")

    print(f"\n✅ Switched to {label} ({default_model})")
    print("Restart token-optimise for the change to take effect.")
    
    
def find_server_path() -> str:
    package_dir = os.path.dirname(os.path.abspath(__file__))
    candidates = [
        os.path.join(package_dir, "..", "src", "mcp", "server_http.py"),
        os.path.join(package_dir, "src", "mcp", "server_http.py"),
    ]
    for path in candidates:
        path = os.path.normpath(path)
        if os.path.exists(path):
            return path

    print("ERROR: Could not find server_http.py")
    print("Please run from the project root or reinstall: pip install token-optimise")
    sys.exit(1)


def _config_needs_update() -> bool:
    if not os.path.exists(CLAUDE_CONFIG):
        return True
    try:
        with open(CLAUDE_CONFIG) as f:
            config = json.load(f)
        token_entry = config.get("mcpServers", {}).get("token", {})
        # update if token missing OR env hint missing
        return not token_entry or "env" not in token_entry
    except Exception:
        return True
    

def update_claude_config(npx_path: str) -> None:
    os.makedirs(os.path.dirname(CLAUDE_CONFIG), exist_ok=True)

    if os.path.exists(CLAUDE_CONFIG):
        with open(CLAUDE_CONFIG) as f:
            config = json.load(f)
        backup = CLAUDE_CONFIG.replace(".json", CLAUDE_BACKUP_SUFFIX)
        shutil.copy2(CLAUDE_CONFIG, backup)
        print(f"[TOKEN] Config backed up to {backup}")
    else:
        config = {}

    config.setdefault("mcpServers", {})

    if "filesystem" not in config["mcpServers"]:
        config["mcpServers"]["filesystem"] = {
            "command": npx_path,
            "args": ["-y", "@modelcontextprotocol/server-filesystem", HOME],
        }
        print("[TOKEN] Added filesystem MCP")

    if "memory" not in config["mcpServers"]:
        config["mcpServers"]["memory"] = {
            "command": npx_path,
            "args": ["-y", "@modelcontextprotocol/server-memory"],
        }
        print("[TOKEN] Added memory MCP")

    config["mcpServers"]["wick"] = {
        "command": npx_path,
        "args": ["-y", "usewick-mcp"],
    }

    config["mcpServers"]["token"] = {
        "command": npx_path,
        "args": ["mcp-remote", "http://127.0.0.1:7737/mcp/"],
        "env": {"MCP_TRANSPORT_STRATEGY": "http-only"},
    }

    config["systemPrompt"] = (
        "You have access to a token optimisation proxy via the 'token' MCP server. "
        "It acts as a unified router for all tool-based tasks — files, email, calendar, "
        "documents, web search, and memory.\n\n"
        "When completing tasks that require tools, prefer calling token:execute with the "
        "full task as the query. It will select the right downstream tool automatically "
        "and return the result efficiently.\n\n"
        "For PDFs specifically, call token:list_indexed_documents first to find the "
        "document, then token:ask_document with your question.\n\n"
        "Avoid calling filesystem, memory, or other MCP tools directly when "
        "token:execute can handle the task — this keeps token usage lower."
    )

    with open(CLAUDE_CONFIG, "w") as f:
        json.dump(config, f, indent=2)

    print("[TOKEN] Claude Desktop config updated")


def _restart_claude() -> None:
    """Quit and relaunch Claude Desktop so it picks up the new config."""
    if sys.platform == "darwin":
        os.system('osascript -e \'quit app "Claude"\' 2>/dev/null || true')
        time.sleep(2)
        os.system('open -a Claude 2>/dev/null || true')
        print("[TOKEN] Claude Desktop restarted")
    elif sys.platform == "win32":
        os.system('taskkill /IM Claude.exe /F 2>nul || true')
        time.sleep(2)
        # Try common install locations
        for path in [
            os.path.join(os.environ.get("LOCALAPPDATA", ""), "AnthropicClaude", "Claude.exe"),
            os.path.join(os.environ.get("PROGRAMFILES", ""), "Claude", "Claude.exe"),
        ]:
            if os.path.exists(path):
                subprocess.Popen([path], start_new_session=True)
                print("[TOKEN] Claude Desktop restarted")
                break
    else:
        print("[TOKEN] Please restart Claude Desktop manually to apply the new config.")


def _kill_existing_server() -> None:
    """Kill any previously running token server so the new one can bind port 7737."""
    port = getattr(settings, "api_port", 7737)
    try:
        if sys.platform == "win32":
            result = subprocess.run(
                ["netstat", "-ano"], capture_output=True, text=True
            )
            for line in result.stdout.splitlines():
                if f":{port}" in line and "LISTENING" in line:
                    pid = line.strip().split()[-1]
                    subprocess.run(["taskkill", "/PID", pid, "/F"], capture_output=True)
                    print(f"[TOKEN] Killed existing server (pid {pid})")
        else:
            result = subprocess.run(
                ["lsof", "-ti", f":{port}"], capture_output=True, text=True
            )
            pids = result.stdout.strip().split()
            for pid in pids:
                if pid:
                    try:
                        os.kill(int(pid), signal.SIGTERM)
                        time.sleep(3)
                        os.kill(int(pid), 0)                                # check if still alive
                        os.kill(int(pid), signal.SIGKILL)                   # force if needed
                    except ProcessLookupError:
                        pass  
                    print(f"[TOKEN] Killed existing server (pid {pid})")
    except Exception:
        pass 


def start_server(api_key,api_key_var, user_id: str) -> None:
    server_path = find_server_path()
    spec = importlib.util.find_spec("token_optimise")
    project_root = os.path.dirname(os.path.dirname(spec.origin))
    
    env = os.environ.copy()
    if api_key and api_key_var:
        env[api_key_var] = api_key
    env["TOKEN_USER_ID"] = user_id
    env["TOKEN_STORAGE_DIR"] = STORAGE_DIR
    env["ALLOWED_DIR"] = settings.allowed_dir

    os.makedirs(STORAGE_DIR, exist_ok=True)

    log_path = os.path.join(TOKEN_DIR, "server.log")
    proc = subprocess.Popen(
        [sys.executable, server_path],
        env=env,
        cwd=project_root,
        start_new_session=True,
        stdout=open(log_path, "w"),
        stderr=subprocess.STDOUT,
    )
    
    pid_file = os.path.join(TOKEN_DIR, "server.pid")
    with open(pid_file, "w") as f:
        f.write(str(proc.pid))

    print(f"[TOKEN] Server started    (pid {proc.pid})")
    print(f"[TOKEN] Local dashboard : http://localhost:7738")
    print(f"[TOKEN] Logs            : {log_path}")
    print(f"[TOKEN] Server runs in background — you can close this terminal.")


def main():
    if "--help" in sys.argv or "-h" in sys.argv:
        print("Usage: token-optimise [options]")
        print()
        print("Options:")
        print("  --change-provider   Switch to a different AI provider")
        print("  --help              Show this message")
        print()
        print("Run without options to start the server.")
        return
    
    if "--change-provider" in sys.argv:
        change_provider()
        return
    
    
    print("---------------------------------------------------------")
    print("   Token-Optime")
    print("---------------------------------------------------------\n")

    user_id = get_or_create_user_id()
    print(f"[TOKEN] User ID: {user_id}")

    # Read whatever key+model the user set up during _bootstrap_env()
    api_key = ""
    api_key_var = ""
    if os.path.exists(USER_ENV_FILE):
        with open(USER_ENV_FILE) as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                k, _, v = line.partition("=")
                k, v = k.strip(), v.strip()
                # Pick up whichever provider key was saved
                if k in ("GROQ_API_KEY", "OPENAI_API_KEY", "ANTHROPIC_API_KEY", "DEEPSEEK_API_KEY"):
                    if v:
                        api_key = v
                        api_key_var = k

    # Fall back to environment if not in file
    if not api_key:
        for var in ("GROQ_API_KEY", "OPENAI_API_KEY", "ANTHROPIC_API_KEY", "DEEPSEEK_API_KEY"):
            val = os.environ.get(var, "").strip()
            if val:
                api_key = val
                api_key_var = var
                break

    # Ollama needs no key — check LLM_MODEL
    llm_model = os.environ.get("LLM_MODEL", "").strip()
    is_ollama = llm_model.startswith("ollama/") if llm_model else False

    if not api_key and not is_ollama:
        # No key found at all, rerun bootstrap to find 
        print("\nNo API key found. Please run setup again.")
        _bootstrap_env()
        
        # After bootstrap, reload
        if os.path.exists(USER_ENV_FILE):
            with open(USER_ENV_FILE) as f:
                for line in f:
                    line = line.strip()
                    if not line or line.startswith("#") or "=" not in line:
                        continue
                    k, _, v = line.partition("=")
                    k, v = k.strip(), v.strip()
                    if k in ("GROQ_API_KEY", "OPENAI_API_KEY", "ANTHROPIC_API_KEY", "DEEPSEEK_API_KEY") and v:
                        api_key = v
                        api_key_var = k
                        break
        if not api_key:
            print("ERROR: No API key configured. Exiting.")
            sys.exit(1)

    npx_path = shutil.which("npx") or ""
    if not npx_path:
        print("ERROR: npx not found — install Node.js from https://nodejs.org")
        sys.exit(1)

    _kill_existing_server()

    if _config_needs_update():
        print("[TOKEN] Claude config missing 'token' entry — updating...")
        update_claude_config(npx_path)
        _restart_claude()
        print("\n[TOKEN] Setup complete!")
    else:
        print("[TOKEN] Claude config already up to date")

    # Ensure COLLECT_TOKEN exists — re-register if missing
    # Safe to call every time — server returns same deterministic token for same user_id
    collect_token = ""
    if os.path.exists(USER_ENV_FILE):
        with open(USER_ENV_FILE) as f:
            for line in f:
                if line.strip().startswith("COLLECT_TOKEN="):
                    collect_token = line.strip().split("=", 1)[1].strip()
                    break

    if not collect_token and settings.token_ingest_url:
        print("[TOKEN] Registering with dashboard server...")
        collect_token = register_user(user_id, settings.token_ingest_url)
        if collect_token:
            print("[TOKEN] Registered — collect token saved.")
        else:
            print("[TOKEN] Could not reach dashboard server — telemetry disabled.")

    print("[TOKEN] Starting server...\n")
    start_server(api_key, api_key_var, user_id)


if __name__ == "__main__":
    main()