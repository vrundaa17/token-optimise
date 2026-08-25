#!/bin/bash
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

# Warn user to quit Claude Desktop 
echo ""
echo "IMPORTANT: Claude Desktop must be fully quit before continuing."
echo "   On Mac: press Cmd+Q on Claude Desktop"
echo ""
read -p "   Have you quit Claude Desktop? (y/n): " QUIT_CONFIRM
if [[ "$QUIT_CONFIRM" != "y" && "$QUIT_CONFIRM" != "Y" ]]; then
    echo "   Please quit Claude Desktop first, then run start.sh again."
    exit 1
fi

# Kill any leftover server processes
pkill -f "src/mcp/server.py" 2>/dev/null || true
pkill -f "server_http.py" 2>/dev/null || true
pkill -f "streamlit" 2>/dev/null || true
sleep 1
echo "Old processes cleared"

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

# Ensure filesystem + memory exist as base downstream servers
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

# Remove stale backup if exists
backup_path = config_path.replace(".json", "") + ".token_optim_backup.json"
if os.path.exists(backup_path):
    os.remove(backup_path)
    print("  Removed stale backup")

# Register token + wick
config["mcpServers"]["token"] = {
    "command": npx_path,
    "args": ["mcp-remote", "http://127.0.0.1:8000/mcp/"]
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

# Launch dashboard 
echo ""
echo "---------------------------------------------------------"
echo "   Starting TOM Dashboard..."
echo "---------------------------------------------------------"
echo ""
echo "   Dashboard : http://localhost:8501"
echo "   API       : http://localhost:8000"
echo ""
echo "   Now open Claude Desktop."
echo "   You should see 'token' in Settings → Developer."
echo ""
echo "   Press Ctrl+C to stop."
echo "---------------------------------------------------------"
echo ""

$PYTHON "$PROJECT_ROOT/src/mcp/server_http.py" &
HTTP_PID=$!

trap "kill $HTTP_PID 2>/dev/null; echo 'Dashboard stopped.'" SIGINT SIGTERM

wait $HTTP_PID