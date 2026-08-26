# 🦾 Token-optimeee

A middleware MCP server that sits between Claude Desktop and your downstream MCP servers — reducing token consumption through semantic caching, dynamic tool selection, and response trimming.

**LLM Backend:** Groq | **Vector Store:** ChromaDB | **Dashboard:** Streamlit

---

## 🎯 What Problem This Solves

Every Claude Desktop session sends the full schema of every connected MCP tool with every prompt. With 23+ tools registered, that's thousands of tokens injected per query — even when only one tool is needed.

Token-optimeee optimises at three levels:

1. **Semantic Tool Selection** — Only the most relevant tool schema is sent to Claude per query (ChromaDB similarity search)
2. **Semantic Caching** — Repeated or similar queries skip tool calls entirely and return cached answers (similarity ≥ 0.8)
3. **Response Trimming** — Verbose tool responses are trimmed to ≤200 tokens before entering the context window

**Real result from testing:** 91.8% schema token reduction per call.

---

## 📁 Project Structure
```
.
├── README.md                       
├── config.py                      # Settings & env loading
├── start.sh                       # One-click setup and launch
├── stop.sh                        # One-click
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

## 🚀 Setup — One Command

### Prerequisites
- Python 3.10+
- Node.js + npx
- Groq API key (free at [console.groq.com](https://console.groq.com))
- Claude Desktop (latest)

### Run

## Run

```bash
chmod +x tom.sh
./token.sh start     # start
./token.sh stop      # stop
./token.sh restart   # restart
./token.sh status    # check if running
```

That's it. The script will:
- Check Python and Node are installed
- Create a virtual environment and install packages (first run: 4-5 mins)
- Create `.env` from `.env.example` and prompt you to add your Groq key
- Close Claude Desktop automatically
- Write the MCP config
- Start the server in the background (terminal can be closed)
- Open the dashboard in your browser
- Reopen Claude Desktop

### Stop

```bash
./stop.sh
```

Or click the **⏹ Stop TOM** button in the dashboard.

---

## 🔧 Ports

| Service | Port |
|---|---|
| FastAPI / MCP | 7737 |
| Streamlit Dashboard | 7738 |

These are intentionally non-default to avoid conflicts with other projects.

---

## 💬 For Best Results — Tell Claude to Use TOM

Claude Desktop has its own built-in tools (memory, web search) that it may prefer by default. For consistent routing through TOM, start each conversation with:

> Use token:execute for every task. Never call other tools directly.

For PDF tasks specifically:
> First call token:list_indexed_documents, then token:ask_document.

**Why is this needed?** Claude decides which tool to call — TOM can't force it. The system prompt in the config nudges Claude, but an explicit instruction in the chat is the most reliable way to ensure TOM is used. This is an honest limitation of how Claude Desktop works, not a bug in TOM.

---

## 📊 Dashboard

Access at `http://localhost:7738`

| Metric | What it means |
|---|---|
| **Schema Tokens Without TOM** | Tokens Claude would receive with all tool schemas |
| **Schema Tokens With TOM** | Tokens Claude actually received (1 selected schema) |
| **Total Tokens Saved** | Schema savings + response trim savings |
| **Cache Hit Rate** | % of queries that returned cached answers |
| **Real Groq Token Usage** | Exact token counts from Groq API (not estimates) |
| **Cost Saved** | Estimated savings based on Sonnet 4.6 pricing |

> **Note:** Cost estimates use Claude Sonnet 4.6 pricing ($3/1M tokens, ₹84/$). Actual cost depends on which model you use in Claude Desktop.



---

## 🐛 Troubleshooting

**TOM already running error**
./stop.sh
./start.sh

**Port 7737 in use**
```bash
lsof -i :7737
kill <PID>
```

**Claude not using token:execute**
- Check Settings → Developer → MCP Servers — `token` should show green
- Add explicit instruction at start of conversation (see above)

**Tool not found for query**
- Rephrase more specifically — e.g. "list files in /Users/name/Desktop" instead of "show my stuff"
- Check `server_out.log` for similarity scores

**Dashboard offline**
```bash
cat server_out.log | tail -50
```

---

## ⚠️ Known Limitations

- **Claude's built-in tools take priority** — memory and web search bypass TOM because Claude prefers its native tools
- **Cost estimates are approximate** — based on Sonnet 4.6 pricing; varies by model
- **Windows not supported** — Mac and Linux only
- **Tilde paths** — if a tool call fails with "file not found", use the full path e.g. `/Users/name/Desktop/file.pdf`

---

## 📖 Docs

- `docs/SETUP.md` — Detailed setup guide
- `docs/QUICKSTART.md` — 5-minute quick start