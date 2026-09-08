# 🦾 Token-Optimise

A middleware MCP server that sits between Claude Desktop and your downstream MCP servers — reducing token consumption through semantic caching, dynamic tool selection, and response trimming.

---

## 🎯 What Problem This Solves

Every Claude Desktop session sends the full schema of every connected MCP tool with every prompt. With 23+ tools registered, that's thousands of tokens injected per query — even when only one tool is needed.

Token-Optimise optimises at three levels:

1. **Semantic Tool Selection** — Only the most relevant tool schema is sent to Claude per query (ChromaDB similarity search)
2. **Semantic Caching** — Repeated or similar queries skip tool calls entirely and return cached answers (similarity ≥ 0.8)
3. **Response Trimming** — Verbose tool responses are trimmed before entering the context window

**Real result from testing:** 91.8% schema token reduction per call.


---

## 📁 Project Structure
```
.
├── README.md                       
├── config.py                      # Settings & env loading
├── requirements.txt               # Python dependencies
├── Dockerfile                     # For EC2 dashboard deployment
├── pyproject.toml                 # PyPI package definition
│
├── token_optimise/
│ ├── init.py
│ ├── main.py                      # Entry point (pip install)
│ └── config.py                    # Settings & env loading
|
├── src/
│ ├── front.py                     # Streamlit dashboard
│ ├── admin_front.py               # Admin dashboard
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
│ ├── server_http.py               # FastAPI + metrics
│ └── dash_api.py                  # Lightweight API for EC2 deployment
|
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
┌──────────────────────────────────────────────────────────┐
│ Token-Optimised MCP Server                               │
│ ┌─────────────────────────────────────────────────────┐  │
│ │ Exposed Tools                                       │  │
│ │ • find_tool (orchestrator)                          │  │
│ │ • index_document / ask_document                     │  │
│ │ • search_all_documents / index_documents_folder     │  │
│ └─────────────────────────────────────────────────────┘  │
│ ┌─────────────────────────────────────────────────────┐  │
│ │ Optimization Layer                                  │  │
│ │ ┌──────────────┐ ┌──────────────────────────────┐   │  │
│ │ │ Semantic     │ │ Tool Selection               │   │  │
│ │ │ Cache        │ │ (ChromaDB → top-k tools)     │   │  │
│ │ │ (sim ≥ 0.8)  │ │                              │   │  │
│ │ └──────────────┘ └──────────────────────────────┘   │  │
│ │ ┌──────────────┐ ┌──────────────────────────────┐   │  │
│ │ │ Response     │ │ Token Audit                  │   │  │
│ │ │ Trimmer      │ │ (SQLite audit log)           │   │  │
│ │ │ (≤500 tok)   │ │                              │   │  │
│ │ └──────────────┘ └──────────────────────────────┘   │  │
│ └─────────────────────────────────────────────────────┘  │
└────────────┬──────────────────┬──────────────────────────┘
             │                  │
             ▼                  ▼
      ┌─────────────┐    ┌──────────────┐
      │ Filesystem  │    │ Memory MCP   │
      │ MCP         │    │ (remote)     │
      │ (14 tools)  │    │ (9 tools)    │
      └─────────────┘    └──────────────┘
```



---


## 🚀 Install — One Command

### Prerequisites
- Python 3.10+
- Node.js + npx
- An API key from any supported provider (or Ollama for local, no key needed)
- Claude Desktop (latest)


### New users — two commands

```bash
pip install token-optimise
token-optimise
```

The installer will:
- Ask which AI provider you want to use
- Ask for your API key
- Ask which folder it can access on your machine
- Write the MCP config into Claude Desktop automatically
- Start the server in the background


### Switch provider later

```bash
token-optimise --change-provider
```

Then restart with `token-optimise`.



## 📊 Dashboard

### Local (your metrics only)
http://localhost:7738


---

## 🔧 Ports

| Service | Port |
|---|---|
| FastAPI / MCP | 7737 |
| Streamlit Dashboard | 7738 |

These are intentionally non-default to avoid conflicts with other projects.

---

## 💬 For Best Results — Tell Claude to Use Token-Optimise

Claude Desktop has its own built-in tools (memory, web search) that it may prefer by default. For consistent routing through Token-optimise:


> Add this to Settings → Instructions for Claude:
```
You have access to a token MCP server. Follow these rules strictly:
For ALL tasks — files, Gmail, Notion, memory, or anything else — always use token:execute first before calling any other tool.
For PDF questions always call token:list_indexed_documents first then token:ask_document.
After every response call token:wick_track.

DOCUMENT/PDF TASKS:
- ALWAYS call list_indexed_docs first, then ask_document immediately.
- NEVER ask the user for clarification.

AFTER EVERY RESPONSE: Call wick_track.
```

You can start your conversation with : 
> Use token:execute for every task. Never call other tools directly.

For PDF tasks specifically:
> First call token:list_indexed_documents, then token:ask_document.

**Why is this needed?** Claude decides which tool to call — Token-Optimise can't force it. The system prompt in the config nudges Claude, but an explicit instruction in the chat is the most reliable way to ensure Token-Optimise is used. This is an honest limitation of how Claude Desktop works, not a bug in Token-Optimise.

---
# Dashboard Metrics

| Metric | What it means |
|--------|--------------|
| Schema Tokens — Estimated Baseline | Tokens Claude would receive with all tool schemas |
| Schema Tokens — With Token-Optimise | Tokens Claude actually received (1 selected schema) |
| Total Tokens Saved | Schema savings + response trim savings |
| Cache Hit Rate | % of queries that returned cached answers |
| Groq Cost (actual ✅) | Real measured cost at Groq pricing |
| Claude Cost Saved (estimated ⚠️) | Range across Haiku→Opus (model unknown) |
| Live USD/INR Rate | Fetched live every hour |



---

## 🐛 Troubleshooting

**Server not starting**
```bash
cat ~/.token_optimise/server.log
```

**Port 7737 in use**
```bash
lsof -i :7737
kill <PID>
token-optimise
```

**Claude not using token:execute**
- Check Settings → Developer → MCP Servers — `token` should show green
- Add explicit instruction at start of conversation

**Dashboard offline**
```bash
token-optimise
```
**Want to change your API key or provider**
```bash
token-optimise --change-provider
```

**Check your current config**
```bash
cat ~/.token_optimise/.env
```



---

## ⚠️ Known Limitations

- **Claude's built-in tools take priority** — memory and web search bypass Token-Optimise because Claude prefers its native tools
- **Cost estimates are approximate** — based on Sonnet 4.6 pricing; varies by model
- **PDF files only** — document indexing supports PDF format only


---
