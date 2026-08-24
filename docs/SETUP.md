# Token-Optimised MCP — Setup & Installation Guide

Complete step-by-step setup for Windows, Mac, and Linux.

## Prerequisites Checklist

- [ ] Python 3.10 or higher (`python --version`)
- [ ] Node.js v16+ (`node --version` and `npm --version`)
- [ ] Groq API key (from https://console.groq.com/)
- [ ] Claude Desktop installed (latest version)
- [ ] ~1GB free disk space (for ChromaDB + SQLite)

---

## Installation Steps

### Step 1: Clone/Download the Project

```bash
# If using Git
git clone <your-repo-url>
cd token-optim

# Or if using zip
unzip token-optim.zip
cd token-optim
```

### Step 2: Create Virtual Environment (Recommended)

**On Mac/Linux:**
```bash
python3 -m venv venv
source venv/bin/activate
```

**On Windows (PowerShell):**
```powershell
python -m venv venv
.\venv\Scripts\Activate.ps1
```

**On Windows (Command Prompt):**
```cmd
python -m venv venv
venv\Scripts\activate.bat
```

### Step 3: Install Dependencies

```bash
pip install -r requirements.txt
```

Expected packages (main ones):
- fastmcp
- fastapi / uvicorn
- streamlit
- chromadb
- sentence-transformers
- groq
- tiktoken
- pydantic-settings
- mcp

This should take ~2-3 minutes.

### Step 4: Create `.env` Configuration File

Create a file named `.env` in the project root (same level as `README.md`):

```env
GROQ_API_KEY=your_groq_api_key_here
EMBEDDER=all-MiniLM-L6-v2
```

**Where to get GROQ_API_KEY:**
1. Visit https://console.groq.com/
2. Sign up / Log in
3. Navigate to API Keys
4. Generate new API key
5. Copy and paste into .env

### Step 5: Run the Setup Script

**On Mac/Linux:**
```bash
bash start.sh
```

**On Windows:**
```powershell
python start.sh  # or manually run the equivalent
```

What this does:
1. Locates your Claude Desktop config file
2. Detects Python path and Node.js path
3. Registers the "token" MCP server
4. Registers the "wick" MCP server (for tracking)
5. Starts the FastAPI backend
6. Launches the Streamlit dashboard

### Step 6: Restart Claude Desktop

- Close Claude Desktop completely
- Reopen Claude Desktop
- Wait 3-5 seconds for MCP server to connect

### Step 7: Verify Installation

#### Test 1: Check Dashboard
Open browser: http://localhost:8501
Should see: "Token-optimeee" dashboard with live metrics


#### Test 2: Check API Health
```bash
curl http://localhost:8000/health
Expected response: {"status": "ok"}
```

#### Test 3: Use find_tool in Claude
Open Claude Desktop and try:
"Use find_tool to list my files"


If successful, you should see the tool execute.

---

## Troubleshooting Setup

### Issue: "ModuleNotFoundError: No module named 'fastmcp'"

**Solution:**
```bash
pip install fastmcp --upgrade
```

### Issue: "Could not find npx"

**Solution:**
1. Install Node.js from https://nodejs.org/
2. Restart terminal
3. Verify: `which npx` (Mac/Linux) or `where npx` (Windows)
4. Re-run: `bash start.sh`

### Issue: "GROQ_API_KEY not found"

**Solution:**
- Verify `.env` file exists in project root
- Verify format: `GROQ_API_KEY=gsk_...`
- No quotes needed
- Restart Python process

### Issue: "Could not locate Claude Desktop config"

**Solution:**
Manually create config file:

**Mac:**
```bash
mkdir -p ~/Library/Application\ Support/Claude
# Then edit: ~/Library/Application\ Support/Claude/claude_desktop_config.json
```

**Windows:**
Navigate to: %APPDATA%\Claude
Create file: claude_desktop_config.json

**Linux:**
```bash
mkdir -p ~/.config/Claude
# Then edit: ~/.config/Claude/claude_desktop_config.json
```

Paste this template:
```json
{
  "mcpServers": {
    "token": {
      "command": "python",
      "args": ["/full/path/to/project/src/mcp/server.py"],
      "env": {
        "ALLOWED_DIR": "/home/your_user",
        "PATH": "/usr/local/bin:/usr/bin:/bin"
      }
    }
  }
}
```

Replace `/full/path/to/project` with actual project path.

### Issue: Dashboard shows "Wick not running"

**Solution:**
- Ensure Claude Desktop is running
- Open any conversation in Claude
- Wait 10 seconds for Wick to initialize
- Refresh dashboard (F5)

If still not working:
```bash
# Check if Claude config has Wick registered
cat ~/Library/Application\ Support/Claude/claude_desktop_config.json

# Should include:
# "wick": {
#   "command": "npx",
#   "args": ["-y", "usewick-mcp"]
# }
```

### Issue: "Address already in use" (port 8000 or 8501)

**Solution:**
Kill existing process:

**Mac/Linux:**
```bash
lsof -i :8000  # Find process using port 8000
kill -9 <PID>
```

**Windows:**
```powershell
netstat -ano | findstr :8000
taskkill /PID <PID> /F
```

Then restart: `bash start.sh`

### Issue: Slow startup (>30 seconds)

**Solution:**
- First run downloads sentence-transformer model (~130MB) — normal
- Subsequent runs should be <5 seconds
- Check disk space: `df -h` (Mac/Linux) or `Get-Volume` (Windows)

---

## Verify Each Component

### 1. Verify Python Environment
```bash
python --version
which python  # or 'where python' on Windows
pip list | grep -E "fastmcp|chromadb|streamlit"
```

### 2. Verify Node.js
```bash
node --version
npm --version
npx --version
```

### 3. Verify Groq API Key
```bash
python -c "from config import settings; print(settings.groq_api_key[:10])"
```

Should print first 10 chars of your API key.

### 4. Verify ChromaDB Storage
```bash
ls -la storage/chroma_db  # Mac/Linux
dir storage\chroma_db     # Windows
```

Should contain `chroma.sqlite3` file.

### 5. Verify Claude Config
```bash
# Mac
cat ~/Library/Application\ Support/Claude/claude_desktop_config.json | python -m json.tool

# Linux
cat ~/.config/Claude/claude_desktop_config.json | python -m json.tool

# Windows
type %APPDATA%\Claude\claude_desktop_config.json
```

Should show `"token"` and `"wick"` servers registered.

---

## Getting Help

- Check logs: `tail -f server.log` (Mac/Linux)
- API health: `curl http://localhost:8000/health`
- Dashboard: `http://localhost:8501`
- Review config: `cat config.py`