# Quick Start — 5 Minute Setup

Get Token-Optimised MCP running in 5 minutes.

## TL;DR

```bash
# 1. Install
pip install -r requirements.txt

# 2. Configure
echo "GROQ_API_KEY=your_key_here" > .env

# 3. Run
bash start.sh

# 4. Open Claude Desktop and ask:
"Use find_tool to list my files"

# 5. Watch metrics at:
http://localhost:8501
```

---

## What You Just Set Up

| Component | What It Does | Access |
|---|---|---|
| **find_tool** | Smart file/memory operations | Claude Desktop |
| **Semantic Cache** | Avoids redundant tool calls | Dashboard |
| **Tool Selection** | Picks right tool automatically | Dashboard (metrics) |
| **Response Trimmer** | Caps responses at 500 tokens | Dashboard (metrics) |
| **Token Audit** | Tracks every prompt/response | Dashboard (events) |
| **Dashboard** | Real-time metrics UI | http://localhost:8501 |

---

## First Test (2 min)

### Test: Cache Hit

1. Open Claude Desktop
2. Ask: **"List 3 files from my Deesktop"**
3. Wait for response ✓
4. Immediately ask: **"List the files on my Desktop"**
5. Check dashboard → Recent Events
6. Look for **"✅ HIT"** on second query

**What you'll see:**
- First query: ❌ MISS (new query, calls tool)
- Second query: ✅ HIT (cached answer, zero tool calls)
- Token savings shown in dashboard

---

## Second Test (3 min)

### Test: Schema Token Reduction

1. Open dashboard: `http://localhost:8501`
2. Look for **"Token Analysis"** section
3. Compare:
   - **Schema Tokens Without :** ~2,100
   - **Schema Tokens With :** ~75
   - **Total Saved:** ~2,025 tokens

**What this means:**
- Without optimization: Claude sees all 23 tool schemas
- With optimization: Claude sees only the 1 relevant tool
- Per query: You save ~2,000 tokens of boilerplate

---

## Common Commands

| Command | What It Does |
|---|---|
| `bash start.sh` | Start everything |
| `curl http://localhost:8000/health` | Check if API is alive |
| `tail -f server.log` | Watch live logs |
| `http://localhost:8501` | Open dashboard |
| `Ctrl+C` | Stop everything |

---

## What Happens Next

### Automatic

- Every tool call is logged to SQLite
- Every response is cached in ChromaDB
- Metrics auto-refresh every 60 seconds
- Cache hits automatically reduce tokens

### Manual

- Adjust cache TTLs in `core/cache.py`
- Configure allowed directories in `start.sh`
- Add more downstream MCP servers
- Index PDFs with `index_document` tool

---

## Dashboard Glossary

| Metric | Meaning |
|---|---|
| **Cache Hits** | # of queries that skipped tool calls |
| **Cache Hit Rate** | % of queries that hit cache |
| **Schema Tokens Saved** | Tokens saved by only showing relevant tools |
| **Trim Tokens Saved** | Tokens saved by capping responses |
| **Total Saved** | Sum of schema + trim savings |

---

## Performance Expectations

| Metric | Expected |
|---|---|
| First query time | 2-5 sec (normal) |
| Cached query time | <1 sec (instant) |
| Tokens per query | 1,800-2,500 (baseline) |
| Tokens saved per query | 300-2,000 (varies) |
| Cache hit rate | 30-50% (after warmup) |

---
