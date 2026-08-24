PROJECT_ROOT="$(cd "$(dirname "$0")" && pwd)"
SERVER_PATH="$PROJECT_ROOT/src/mcp/server.py"

if [ -f "$PROJECT_ROOT/venv/bin/python3" ]; then
    PYTHON="$PROJECT_ROOT/venv/bin/python3"
elif [ -f "$PROJECT_ROOT/venv/bin/python" ]; then
    PYTHON="$PROJECT_ROOT/venv/bin/python"
else
    PYTHON=$(which python3 || which python)
fi

NPX_PATH=$(which npx)

if [[ "$OSTYPE" == "darwin"* ]]; then
    CLAUDE_CONFIG="$HOME/Library/Application Support/Claude/claude_desktop_config.json"
elif [[ "$OSTYPE" == "msys"* || "$OSTYPE" == "win32" ]]; then
    CLAUDE_CONFIG="$APPDATA/Claude/claude_desktop_config.json"
else
    CLAUDE_CONFIG="$HOME/.config/Claude/claude_desktop_config.json"
fi

echo "Project: $PROJECT_ROOT"
echo "Python:  $PYTHON"
echo "npx:     $NPX_PATH"
echo "Config:  $CLAUDE_CONFIG"

# Write token + wick into claude config
$PYTHON - <<EOF
import json, os, shutil

config_path = """$CLAUDE_CONFIG"""
server_path = """$SERVER_PATH"""
python_bin  = """$PYTHON"""

npx_path = shutil.which("npx")
if not npx_path:
    for candidate in [
        os.path.expanduser("~/.nvm/versions/node"),
        "/usr/local/bin",
        "/opt/homebrew/bin",
    ]:
        if os.path.isdir(candidate):
            for root, dirs, files in os.walk(candidate):
                if "npx" in files:
                    npx_path = os.path.join(root, "npx")
                    break
        if npx_path:
            break

if not npx_path:
    print("ERROR: could not find npx — please install Node.js")
    exit(1)

node_bin   = os.path.dirname(npx_path)
clean_path = f"{node_bin}:/usr/local/bin:/usr/bin:/bin"

os.makedirs(os.path.dirname(config_path), exist_ok=True)

if os.path.exists(config_path):
    with open(config_path) as f:
        config = json.load(f)
else:
    config = {}

config.setdefault("mcpServers", {})

config["mcpServers"]["token"] = {
    "command": python_bin,
    "args": [server_path],
    "env": {
        "PATH": clean_path,
        "ALLOWED_DIR": os.path.expanduser("~")
    }
}
config["mcpServers"]["wick"] = {
    "command": npx_path,
    "args": ["-y", "usewick-mcp"]
}

with open(config_path, "w") as f:
    json.dump(config, f, indent=2)

print(f"Claude config updated — token + wick registered")
print(f"npx: {npx_path}")
print(f"PATH: {clean_path}")
EOF

echo ""
echo "Starting FastAPI + Streamlit dashboard..."
$PYTHON "$PROJECT_ROOT/src/mcp/server_http.py" &
HTTP_PID=$!

echo "Dashboard: http://localhost:8501"
echo "API:       http://localhost:8000"
echo ""
echo "Now open Claude Desktop (or restart it if already open)."
echo "Claude Desktop will launch the MCP server automatically."
echo ""
echo "Press Ctrl+C to stop the dashboard."


trap "kill $HTTP_PID 2>/dev/null; echo 'Dashboard stopped.'" SIGINT SIGTERM

wait $HTTP_PID