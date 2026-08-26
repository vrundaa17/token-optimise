#!/bin/bash

# stop 
COMMAND=${1:-start}

if [[ "$COMMAND" == "stop" ]]; then
    PID_FILE="$(cd "$(dirname "$0")" && pwd)/storage/server.pid"
    if [ ! -f "$PID_FILE" ]; then
        echo "Token-optimeee is not running."
        exit 0
    fi
    PID=$(cat "$PID_FILE")
    if kill -0 "$PID" 2>/dev/null; then
        kill "$PID"
        rm "$PID_FILE"
        pkill -f "streamlit" 2>/dev/null || true
        echo "Token-optimeee stopped."
    else
        echo "Token-optimeee was not running."
        rm "$PID_FILE"
    fi
    exit 0
fi

if [[ "$COMMAND" == "status" ]]; then
    PID_FILE="$(cd "$(dirname "$0")" && pwd)/storage/server.pid"
    if [ -f "$PID_FILE" ] && kill -0 "$(cat "$PID_FILE")" 2>/dev/null; then
        echo "Token-optimeee is running (pid $(cat $PID_FILE))"
        echo "   Dashboard : http://localhost:7738"
        echo "   API       : http://localhost:7737"
    else
        echo "Token-optimeee is not running."
    fi
    exit 0
fi

if [[ "$COMMAND" == "restart" ]]; then
    "$0" stop
    sleep 2
    exec "$0" start
fi



# default: start

if [[ "$OSTYPE" == "msys"* || "$OSTYPE" == "win32"* || "$OSTYPE" == "cygwin"* ]]; then
    echo "ERROR: Windows is not yet supported. Use Mac or Linux."
    exit 1
fi

set -e

PROJECT_ROOT="$(cd "$(dirname "$0")" && pwd)"
SERVER_PATH="$PROJECT_ROOT/src/mcp/server.py"

echo "---------------------------------------------------------"
echo "   Token-Optimised MCP Server"
echo "---------------------------------------------------------"
echo ""

# Check Python is available 
if ! command -v python3 &>/dev/null; then
    echo "ERROR: Python 3 not found."
    echo "      - Install from https://python.org and try again."
    exit 1
fi
echo "Python: $(python3 --version)"

# Check Node.js / npx is available 
NPX_PATH=$(which npx 2>/dev/null)
if [ -z "$NPX_PATH" ]; then
    # try common nvm paths
    for candidate in "$HOME/.nvm/versions/node" "/usr/local/bin" "/opt/homebrew/bin"; do
        if [ -d "$candidate" ]; then
            found=$(find "$candidate" -name "npx" 2>/dev/null | head -1)
            if [ -n "$found" ]; then
                NPX_PATH="$found"
                break
            fi
        fi
    done
fi

if [ -z "$NPX_PATH" ]; then
    echo "ERROR: npx not found."
    echo "      - Install Node.js from https://nodejs.org/ and try again."
    exit 1
fi
echo "npx: $NPX_PATH"

# Create venv if it doesn't exist
if [ ! -d "$PROJECT_ROOT/venv" ]; then
    echo ""
    echo "Creating virtual environment..."
    python3 -m venv "$PROJECT_ROOT/venv"
    echo " venv created"
fi

# Always use venv python from here on
PYTHON="$PROJECT_ROOT/venv/bin/python3"

# Install packages if not already installed 
if ! $PYTHON -c "import fastmcp, chromadb, groq, streamlit, tiktoken, pymupdf" 2>/dev/null; then
    echo ""
    echo "Installing packages..."
    echo "   (First install takes 4-5 minutes — torch/sentence-transformers are large)"
    echo "   Please wait..."
    $PYTHON -m pip install --upgrade pip --quiet
    $PYTHON -m pip install -r "$PROJECT_ROOT/requirements.txt" --quiet
    echo "Packages installed"
else
    echo "Packages already installed"
fi

# Create .env if it doesn't exist 
if [ ! -f "$PROJECT_ROOT/.env" ]; then
    echo ""
    echo "No .env file found — creating one from .env.example..."
    if [ -f "$PROJECT_ROOT/.env.example" ]; then
        cp "$PROJECT_ROOT/.env.example" "$PROJECT_ROOT/.env"
        echo ""
        echo "ACTION REQUIRED:"
        echo "   Open .env and fill in your GROQ_API_KEY"
        echo "   Get your key from: https://console.groq.com/"
        echo ""
        echo "   Then run start.sh again."
        exit 1
    else
        echo "ERROR: .env.example not found."
        echo "   Create a .env file with:"
        echo "   GROQ_API_KEY=your_key_here"
        echo "   EMBEDDER=all-MiniLM-L6-v2"
        exit 1
    fi
fi

# Check GROQ_API_KEY is actually filled in 
if grep -q "GROQ_API_KEY=your_" "$PROJECT_ROOT/.env" || ! grep -q "GROQ_API_KEY=" "$PROJECT_ROOT/.env"; then
    echo ""
    echo "ERROR: GROQ_API_KEY not set in .env"
    echo "   Open .env and add your key from https://console.groq.com/"
    exit 1
fi
echo ".env ready"

# Create storage folder 
mkdir -p "$PROJECT_ROOT/storage"
echo "storage/ folder ready"

# Find Claude config path 
if [[ "$OSTYPE" == "darwin"* ]]; then
    CLAUDE_CONFIG="$HOME/Library/Application Support/Claude/claude_desktop_config.json"
elif [[ "$OSTYPE" == "msys"* || "$OSTYPE" == "win32" ]]; then
    CLAUDE_CONFIG="$APPDATA/Claude/claude_desktop_config.json"
else
    CLAUDE_CONFIG="$HOME/.config/Claude/claude_desktop_config.json"
fi


# already running? 
mkdir -p "$PROJECT_ROOT/storage"
PID_FILE="$PROJECT_ROOT/storage/server.pid"

if [ -f "$PID_FILE" ]; then
    PID=$(cat "$PID_FILE")
    if kill -0 "$PID" 2>/dev/null; then
        echo ""
        echo "Token-optimeeee is already running!"
        echo "   Dashboard : http://localhost:7738"
        echo "   To restart: double-click stop.sh first, then start.sh"
        exit 0
    else
        rm "$PID_FILE"
    fi
fi

# Kill any leftover server processes
pkill -f "server_http.py" 2>/dev/null || true
pkill -f "streamlit" 2>/dev/null || true
sleep 1
echo "Ready to start"


# Close Claude Desktop before touching config
echo "Closing Claude Desktop..."
if [[ "$OSTYPE" == "darwin"* ]]; then
    osascript -e 'quit app "Claude"' 2>/dev/null || true
elif [[ "$OSTYPE" == "linux"* ]]; then
    pkill -f "claude" 2>/dev/null || true
fi
sleep 2


# Write Claude config
node_bin=$(dirname "$NPX_PATH")
clean_path="$node_bin:/usr/local/bin:/usr/bin:/bin"

$PYTHON - <<EOF
import json, os

config_path = """$CLAUDE_CONFIG"""
server_path = """$SERVER_PATH"""
python_bin  = """$PYTHON"""
npx_path    = """$NPX_PATH"""
clean_path  = """$clean_path"""

os.makedirs(os.path.dirname(config_path), exist_ok=True)

if os.path.exists(config_path):
    with open(config_path) as f:
        config = json.load(f)
else:
    config = {}

config.setdefault("mcpServers", {})

if "filesystem" not in config["mcpServers"]:
    config["mcpServers"]["filesystem"] = {
        "command": npx_path,
        "args": ["-y", "@modelcontextprotocol/server-filesystem", os.path.expanduser("~")]
    }
    print("  Added filesystem MCP")

if "memory" not in config["mcpServers"]:
    config["mcpServers"]["memory"] = {
        "command": npx_path,
        "args": ["-y", "@modelcontextprotocol/server-memory"]
    }
    print("  Added memory MCP")

backup_path = config_path.replace(".json", "") + ".token_optim_backup.json"
if os.path.exists(backup_path):
    os.remove(backup_path)

config["mcpServers"]["token"] = {
    "command": npx_path,
    "args": ["mcp-remote", "http://127.0.0.1:7737/mcp/"]
}

config["mcpServers"]["wick"] = {
    "command": npx_path,
    "args": ["-y", "usewick-mcp"]
}

config["systemPrompt"] = (
    "You have access to a token optimizer via the 'token' MCP server.\n\n"
    "MANDATORY RULES:\n"
    "1. For ANY task — listing files, reading emails, searching Notion, querying documents, anything — "
    "always call token:execute first. Pass the full task description as the query.\n"
    "2. Never use bash, code execution, or call other MCP tools directly.\n"
    "3. token:execute will figure out the right tool and return the result. Trust it.\n"
    "4. For PDFs, call token:list_indexed_documents first, then token:ask_document.\n\n"
    "These rules have no exceptions. token:execute is always your first call."
)

with open(config_path, "w") as f:
    json.dump(config, f, indent=2)

print("Claude config updated")
EOF

#  check port free ─
if lsof -i :7737 -t &>/dev/null; then
    echo ""
    echo "ERROR: Port 7737 is already in use."
    echo "      Token-optimeeee might already be running — double-click stop.sh to stop it first."
    exit 1
fi

#  launch server in background ─
echo ""
echo "---------------------------------------------------------"
echo "   Starting Token-optimeeee..."
echo "---------------------------------------------------------"
echo ""

nohup $PYTHON "$PROJECT_ROOT/src/mcp/server_http.py" \
    > "$PROJECT_ROOT/server_out.log" 2>&1 &
HTTP_PID=$!
echo $HTTP_PID > "$PID_FILE"

echo "   Token-optimeeee started! (running in background)"
echo ""
echo "   Dashboard : http://localhost:7738"
echo "   API       : http://localhost:7737"
echo ""
echo "   Open Claude Desktop now — you should see 'token' in"
echo "   Settings → Developer → MCP Servers"
echo ""
echo "   To STOP Token-optimeeee: double-click stop.sh"
echo "---------------------------------------------------------"
echo ""
echo "   You can close this terminal — Token-optimeeee keeps running."
echo ""

# Reopen Claude Desktop
sleep 6
if [[ "$OSTYPE" == "darwin"* ]]; then
    open "http://localhost:7738"
    open -a "Claude" 2>/dev/null || echo "   (Open Claude Desktop manually)"
elif [[ "$OSTYPE" == "linux"* ]]; then
    nohup claude 2>/dev/null & true || echo "   (Open Claude Desktop manually)"
fi
# $PYTHON "$PROJECT_ROOT/src/mcp/server_http.py" &
# HTTP_PID=$!

# trap "kill $HTTP_PID 2>/dev/null; echo 'Dashboard stopped.'" SIGINT SIGTERM

# wait $HTTP_PID
# # if server crashes 
# echo ""
# echo "Server stopped. Run start.sh again to restart."