# Quick Start — 5 Minute Setup

Get Token-optimeee running in 5 minutes.

## TL;DR

```bash
# 1. Run setup
chmod +x token.sh
./token.sh start

# 2. Add your Groq API key when prompted
# Get one free at: https://console.groq.com/

# 3. Dashboard opens automatically in your browser

# 4. Open Claude Desktop and say:
"Use token:execute for every task. List 3 files from my desktop"

# 5. Watch metrics at:
http://localhost:7738
```

---

## What You Just Set Up

| Component | What It Does | Access |
|---|---|---|
| **token:execute** | Routes all tasks through TOM | Claude Desktop |
| **Semantic Cache** | Returns cached answers for similar queries | Dashboard |
| **Tool Selection** | Picks the right tool from 23+ options | Dashboard |
| **Response Trimmer** | Caps verbose responses to ≤200 tokens | Dashboard |
| **PDF RAG** | Index and search PDFs semantically | Claude Desktop |
| **Dashboard** | Real-time metrics and savings | http://localhost:7738 |

---

## First Test — Cache Hit (2 min)

1. Open Claude Desktop
2. Say: **"Use token:execute for everything. List 3 files from my desktop"**
3. Wait for response
4. Ask the same thing again: **"List 3 files from my desktop"**
5. Open dashboard → Recent Events
6. Second query should show **✅ HIT**

**What you'll see:**
- First query: ❌ MISS — calls the tool, gets result, stores in cache
- Second query: ✅ HIT — returns instantly, zero tool calls, zero tokens wasted

---

## Second Test — Schema Token Reduction (3 min)

1. Open dashboard: `http://localhost:7738`
2. Look at **Token Analysis** section
3. Compare:
   - **Schema Tokens Without TOM:** ~19,000+
   - **Schema Tokens With TOM:** ~400
   - **Reduction:** ~91%

**What this means:**
- Without TOM: Claude receives every tool schema on every call
- With TOM: Claude receives only the one relevant tool schema
- Real measured result: **91.8% schema token reduction**

---

## PDF Test (3 min)

1. Tell Claude: **"index the file at /full/path/to/file.pdf with doc_id mydoc"**
2. Ask: **"what is mydoc about"**
3. Ask the same question again
4. Dashboard shows cache hit + tokens saved

---

## Commands

| Command | What It Does |
|---|---|
| `./token.sh start` | Start TOM |
| `./token.sh stop` | Stop TOM |
| `./token.sh restart` | Restart TOM |
| `./token.sh status` | Check if running |
| `curl http://localhost:7737/health` | Check API health |
| `tail -f server_out.log` | Watch live logs |

---

## For Best Results

Add this at the start of every Claude Desktop conversation:

> Use token:execute for every task. Never call other tools directly.

Claude has its own built-in tools and may prefer them. This instruction ensures it routes through TOM consistently. See README for full explanation.

---

## Dashboard Glossary

| Metric | Meaning |
|---|---|
| **Schema Tokens Without TOM** | Tokens Claude would get with all schemas |
| **Schema Tokens With TOM** | Tokens Claude actually got (1 schema) |
| **Cache Hit Rate** | % of queries returned from cache |
| **Trim Tokens Saved** | Tokens saved by capping responses |
| **Real Groq Token Usage** | Exact token counts from Groq API |
| **Cost Saved** | Estimated savings (Sonnet 4.6 pricing) |

---

## Performance from Real Testing

| Metric | Result |
|---|---|
| Schema token reduction | 91.8% |
| Cache hit rate | 35.7% |
| Cached query time | <1 sec |
| First query time | 2-5 sec |

---
