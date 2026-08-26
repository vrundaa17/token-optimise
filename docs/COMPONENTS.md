
**Config hijacking:** On startup, TOM reads `claude_desktop_config.json`, moves all existing MCP servers into its own internal downstream list, and replaces them with just `token` in the config. This way Claude Desktop only sees TOM — all other MCPs are proxied through it. On shutdown, the original config is restored.

---

## 2. Semantic Cache (`src/core/cache.py`)

Avoids redundant tool calls for similar queries.

**How it works:**
- Every query is embedded with SentenceTransformer (`all-MiniLM-L6-v2`)
- Embedding is searched against past queries in ChromaDB
- If similarity ≥ 0.8 AND answer is fresh → return cached answer, skip everything else
- New answers are stored after every successful tool call

**TTL per tool:**
| Tool | Cache lifetime |
|---|---|
| `execute` | 5 minutes |
| `ask_document` | 24 hours |
| `search_all_documents` | 24 hours |
| `list_indexed_documents` | 1 minute |
| Default | 1 hour |

**Why similarity not exact match:**
"List my files" and "Show files on desktop" are different strings but same intent. Exact match would miss this. Semantic similarity catches it.

---

## 3. Tool Selection (`src/core/tool_selection.py`)

Picks the right downstream tool from 23+ options using semantic search.

**How it works:**
1. On startup, all tool names + descriptions are embedded and stored in ChromaDB
2. When a query arrives, it's rewritten by Groq to better match tool terminology (`expand_query`)
3. ChromaDB similarity search finds the top-k most relevant tools
4. Only tools above confidence threshold (0.30) are returned
5. Only the selected tool's schema is sent — not all 23

**Why this saves tokens:**
- Full schema of 23 tools: ~19,000 tokens
- Single selected tool schema: ~400 tokens
- **Saving: 91.8% per call**

**Confidence threshold:** `0.30` — tools below this score are rejected and a "no tool found" message is returned instead of a bad guess.

---

## 4. Response Trimmer (`src/core/trim.py`)

Caps verbose tool responses before they enter Claude's context window.

**How it works:**
- Counts tokens using tiktoken (`cl100k_base`)
- If response is under 200 tokens → pass through unchanged
- If response is plain text over 200 tokens → cut at sentence boundary, add trim note
- If response is JSON → attempt to trim list items, otherwise pass through to preserve structure

**Why 200 tokens:**
Most useful tool responses (file lists, memory reads, search results) fit in 200 tokens. Anything longer is usually noise — full file contents, raw API dumps, verbose logs.

---

## 5. Groq Client (`src/core/client.py`)

Handles all LLM calls — argument filling and query expansion.

**`fill_args_llm`** — given a user query and a tool schema, asks Groq to fill in the correct arguments as JSON. Returns exact token counts from Groq API for real measurement.

**`expand_query`** — rewrites the user query using tool terminology to improve semantic matching accuracy.

**Model used:** `openai/gpt-oss-20b` via Groq (free tier)

**Real token counting:** Every Groq API response includes `usage.prompt_tokens` and `usage.completion_tokens` — these are logged to SQLite and shown in the dashboard as exact counts, not estimates.

---

## 6. PDF RAG Pipeline (`src/core/document_search.py`)

Index and search PDF documents semantically.

**Indexing flow:**
```
          PDF file
              │
              ▼
PyMuPDF (extract text per page)
              │
              ▼
RecursiveCharacterTextSplitter (chunk_size=1200, overlap=200)
              │
              ▼
HuggingFace embeddings (all-MiniLM-L6-v2)
              │
              ▼
ChromaDB (persistent vector store)
```

**Search flow:**

            query
              │
              ▼
          embed query
              │
              ▼
ChromaDB similarity search (top-k chunks)
              │
              ▼
CrossEncoder reranker (ms-marco-MiniLM-L-6-v2)
              │
              ▼
return top 3 reranked chunks with page numbers
```


**Why reranking:** Initial embedding search returns candidates by similarity. Reranking re-scores them by relevance to the exact query — gives more accurate answers especially for long documents.

---

## 7. Event Logger (`src/core/db.py`)

SQLite database that logs every tool call with full metrics.

**Schema:**
| Column | What it stores |
|---|---|
| `tool_name` | Which tool was called |
| `query` | The user query |
| `cache_hit` | 1 if cache hit, 0 if miss |
| `cache_similarity` | Similarity score of cache lookup |
| `tokens_before_trim` | Response tokens before trimming |
| `tokens_after_trim` | Response tokens after trimming |
| `trim_saved` | Tokens saved by trimming |
| `schema_tokens_full` | Tokens of all schemas combined |
| `schema_tokens_selected` | Tokens of selected schema only |
| `schema_tokens_saved` | Difference (actual saving) |
| `groq_prompt_tokens` | Real prompt tokens from Groq API |
| `groq_completion_tokens` | Real completion tokens from Groq API |
| `conversation_id` | Groups events into conversations (15min gap = new conversation) |
| `success` | 1 if tool call succeeded |

---

## 8. FastAPI Server (`src/mcp/server_http.py`)

Hosts both the MCP server and the REST API for the dashboard.

**Endpoints:**
| Endpoint | What it returns |
|---|---|
| `GET /health` | Server status, uptime, tools indexed |
| `GET /metrics/summary` | Total calls, cache hits, tokens saved |
| `GET /metrics/token_analysis` | Full token savings breakdown |
| `GET /metrics/tools` | Per-tool usage stats |
| `GET /metrics/events` | Recent event log |
| `GET /metrics/indexed_docs` | List of indexed PDFs |
| `GET /metrics/conversations` | Per-conversation token savings |
| `GET /metrics/groq_usage` | Real Groq token counts |
| `POST /shutdown` | Gracefully stop the server |

**Ports:**
- MCP + API: `7737`
- Dashboard: `7738`

---

## 9. Dashboard (`src/front.py`)

Streamlit UI showing real-time metrics. Auto-refreshes every 5 minutes.

**Sections:**
- **Live Session** — Wick token tracking with session delta
- **Token Analysis** — Schema savings, trim savings, cost saved
- **Real Groq Usage** — Exact token counts from API
- **Overall Summary** — Cache hit rate, total savings
- **Tool Usage** — Per-tool call and cache breakdown
- **Indexed Documents** — PDFs currently indexed
- **Per-Conversation** — Token savings grouped by conversation
- **Recent Events** — Full event log with cache hit/miss

**Stop button** — calls `POST /shutdown` to gracefully stop the server without touching the terminal.