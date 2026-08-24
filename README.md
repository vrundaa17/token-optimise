# Token-Optimised MCP Server

A middleware MCP server that sits between Claude Desktop and downstream MCP servers to reduce token consumption through semantic caching, dynamic tool selection, and response trimming.

**Status:** Production-ready | **Model:** Claude Haiku 4.5 Extended | **LLM Backend:** Groq / Llama 3.3 70B

---

## 🎯 What Problem This Solves

Every Claude Desktop session re-sends the full tool schema for every connected MCP server. With 23+ tools registered, that's **thousands of tokens injected into each prompt** — even when the query only needs one tool.

This project optimises at three levels:

1. **Semantic Tool Selection** — Only send tools relevant to the current query via ChromaDB similarity search
2. **Semantic Caching** — Skip LLM/tool calls entirely for repeated or similar queries (similarity ≥ 0.8)
3. **Response Trimming** — Truncate verbose tool responses to ≤500 tokens before entering context window

**Result:** ~15-18% average token reduction per query

---

## 📁 Project Structure
```
.
├── README.md                       
├── config.py                      # Settings & env loading
├── start.sh                       # One-command setup
├── requirements.txt               # Python dependencies
├── remote_servers.json            # Remote MCP URLs
│
├── src/
│ ├── front.py                     # Streamlit dashboard
│ ├── core/
│ │ ├── cache.py                   # Semantic cache
│ │ ├── trim.py                    # Response trimmer
│ │ ├── tool_selection.py          # Tool selection
│ │ ├── client.py                  # Groq/Claude client
│ │ ├── document_search.py         # RAG (index + search)
│ │ └── db.py                      # SQLite audit logging
│ │
│ └── mcp/
│ ├── server.py                    # Main MCP server
│ └── server_http.py               # FastAPI + metrics
│
└── storage/
├── chroma_db/                     # ChromaDB persistent store
└── token_audit.db                 # SQLite audit logs
```


---

## Our Test Case

 1. list files on /Users/../Desktop
 2. list files on /Users/../Desktop  

 3. index /Users/../Desktop/leave_policy.pdf doc_id leave
 4. what is the leave policy?
 5. what is the leave policy?                   
 6. read a file                  


---

## 🏗️ System Architecture

```
Claude Desktop
│
▼
┌────────────────────────────────────────────────────────┐
│ Token-Optimised MCP Server  │
│ ┌─────────────────────────────────────────────────────┐│
│ │ Exposed Tools ││
│ │ • find_tool (orchestrator) ││
│ │ • index_document / ask_document ││
│ │ • search_all_documents / index_documents_folder ││
│ └─────────────────────────────────────────────────────┘│
│ ┌─────────────────────────────────────────────────────┐│
│ │ Optimization Layer ││
│ │ ┌──────────────┐ ┌──────────────────────────────┐ ││
│ │ │ Semantic │ │ Tool Selection │ ││
│ │ │ Cache │ │ (ChromaDB → top-k tools) │ ││
│ │ │ (sim ≥ 0.8) │ │ │ ││
│ │ └──────────────┘ └──────────────────────────────┘ ││
│ │ ┌──────────────┐ ┌──────────────────────────────┐ ││
│ │ │ Response │ │ Token Audit│ ││
│ │ │ Trimmer │ │ (SQLite audit log) │ ││
│ │ │ (≤500 tok) │ │ │ ││
│ │ └──────────────┘ └──────────────────────────────┘ ││
│ └─────────────────────────────────────────────────────┘│
└────────────┬──────────────────┬──────────────────────────┘
│ │
▼ ▼
┌─────────────┐ ┌──────────────┐
│ Filesystem │ │ Memory MCP │
│ MCP │ │ (remote) │
│ (14 tools) │ │ (9 tools) │
└─────────────┘ └──────────────┘
```


---

## 🔧 How Each Component Works

### 1. **find_tool** (Main Orchestrator)

Entry point for all file/memory operations. When you use `find_tool`:

1. Check cache — if similar query was asked before (similarity ≥ 0.8), return cached answer instantly
2. Select relevant tools — query ChromaDB to find the most relevant downstream tool (only 1)
3. Run the tool — execute it on filesystem/memory
4. Trim response — cap output at 500 tokens to save space
5. Store in cache — save answer for future similar queries
6. Log everything — record to SQLite for analytics

---

### 2. **Semantic Cache** (`core/cache.py`)

Avoids redundant tool calls for similar queries.

- Embeds your query with SentenceTransformer
- Searches past queries in ChromaDB
- If similarity score ≥ 0.8 and answer is fresh → return cached answer instantly
- Tool-specific cache lifetimes:
  - `find_tool`: 5 minutes
  - `ask_document`: 24 hours
  - `list_indexed_documents`: 1 minute
  - Others: 1 hour

**Example:** Ask "What files do I have?" → stored. Ask "Show me my files" (similar) → instant hit, zero LLM calls.

---

### 3. **Tool Selection** (`core/tool_selection.py`)

Picks the right tool from 23+ available options.

- Indexes all tool schemas (name, description, args) in ChromaDB on startup
- When query arrives, semantic search finds the most relevant tool
- Returns only that tool's schema to Claude

**Why it matters:** Without this, Claude sees all 23 tool schemas (~2000 tokens). With this, Claude sees only 1 tool (~50 tokens). Per query savings: ~1600 tokens of schema boilerplate.

---

### 4. **Response Trimmer** (`core/trim.py`)

Caps tool responses at ≤500 tokens.

- Some tools return entire file contents or large result sets
- Instead of sending 2000+ tokens of response, trim to 500
- Cuts at sentence boundaries to preserve readability
- Adds transparent note: "[Trimmed: 2000 → 500 tokens]"

---

### 5. **Token Audit** (`core/db.py`)

Logs every prompt/response to SQLite:
- Query text
- Tool used
- Cache hit/miss
- Tokens before/after trim
- Cost (₹ and $)
- Timestamp

Powers the dashboard analytics.

---

### 6. **Document Search & RAG** (`core/document_search.py`)

Index and search PDFs with semantic search.

**Exposed tools:**
- `index_document` — Load PDF, chunk, embed, store
- `ask_document` — RAG search on specific document
- `search_all_documents` — Search across all indexed docs
- `index_documents_folder` — Batch index folder of PDFs

---

### 7. **Dashboard** (`src/front.py`)

Real-time analytics Streamlit UI showing:
- Live Claude session metrics
- Token savings breakdown (schema + trim)
- Cache hit rate
- Per-tool usage stats
- Indexed documents
- Recent events log

**Access at:** `http://localhost:8501`

---

## 🚀 Quick Start

### Prerequisites
- Python 3.10+
- Node.js (for npx)
- Groq API key
- Claude Desktop (latest)

### 1. Install Dependencies
```bash
pip install -r requirements.txt
```

### 2. Configure Environment
Create `.env`:
```env
GROQ_API_KEY=your_groq_api_key_here
EMBEDDER=all-MiniLM-L6-v2
```

### 3. Run Setup
```bash
bash start.sh
```

This will:
- Detect your Claude Desktop config
- Register the  MCP server
- Register Wick tracking MCP
- Start FastAPI backend
- Launch Streamlit dashboard

### 4. Restart Claude Desktop
- Close and reopen Claude Desktop
- You'll now have `find_tool` + document search tools available

### 5. Access Dashboard
Navigate to: `http://localhost:8501`

---

## 📊 Dashboard Metrics

| Metric | What it means |
|---|---|
| **Cache Hits** | # of queries that skipped tool calls |
| **Cache Hit Rate** | % of queries that hit cache |
| **Schema Tokens Saved** | Tokens saved by showing only relevant tools |
| **Trim Tokens Saved** | Tokens saved by capping responses at 500 |
| **Total Saved** | Sum of schema + trim savings |

---

## 🐛 Troubleshooting

### Dashboard shows "Wick not running"
- Start Claude Desktop
- Ensure Wick MCP is registered in Claude config

### "Could not find npx" error
- Install Node.js: https://nodejs.org/
- Ensure `npx` is in PATH

### Cache not working
- Verify ChromaDB exists: `ls storage/chroma_db/`
- Check GROQ_API_KEY is set
- Review logs: `tail -f server.log`

### Tool selection returning wrong tools
- Check server.log for warnings
- Verify tool schemas are loading
- Re-run setup: `bash start.sh`

---

## 📖 Documentation

- `/docs/SETUP.md` — Detailed installation for your tech lead
- `/docs/QUICKSTART.md` — 5-minute quick start
- `/docs/COMPONENTS.md` — Deep dive into each component

---
