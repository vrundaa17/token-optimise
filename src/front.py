import streamlit as st
import requests
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
from streamlit_autorefresh import st_autorefresh
import json,os

from config import settings as _cfg


st_autorefresh(interval=60000, key="dashboard_refresh")

API_BASE = os.getenv("API_BASE", f"http://localhost:{_cfg.api_port}")

st.set_page_config(
    page_title="Token-optimeee",
    page_icon="🦾",
    layout="wide",
    initial_sidebar_state="collapsed"
)

st.markdown("""
<style>
    .stMetric {
        background: #1a1d27;
        border-radius: 12px;
        padding: 15px;
        border: 1px solid #2d2d3d;
    }
</style>
""", unsafe_allow_html=True)


def save_wick_baseline(wick):
    with open("storage/wick_baseline.json", "w") as f:
        json.dump({
            "tokens": wick.get("totalTokens", 0),
            "cost_usd": wick.get("totalCostUSD", 0),
            "cost_inr": wick.get("totalCostINR", 0),
            "turns": wick.get("totalTurns", 0),
        }, f)



def get_wick_delta(wick):
    if not os.path.exists("storage/wick_baseline.json"):
        return None
    with open("storage/wick_baseline.json","r") as f:
        baseline = json.load(f)
    return {
        "tokens": wick.get("totalTokens", 0) - baseline["tokens"],
        "cost_usd": wick.get("totalCostUSD", 0) - baseline["cost_usd"],
        "turns": wick.get("totalTurns", 0) - baseline["turns"],
        "cost_inr": wick.get("totalCostINR", 0) - baseline["cost_inr"],
    }

def fetch(endpoint):
    try:
        r = requests.get(f"{API_BASE}{endpoint}", timeout=5)
        r.raise_for_status()
        return r.json()
    except requests.exceptions.ConnectionError:
        return None                  # server not yet up — shown via health check banner
    except Exception as e:
        st.warning(f"Could not load {endpoint}: {e}")
        return None

def fetch_wick():
    try:
        r = requests.get("http://localhost:6789/api/summary", timeout=3)
        r.raise_for_status()
        return r.json()
    except:
        return None


# ── header ────────────────────────────────────────────────────────────────────
st.title("🦾 Token-optimeee")
st.caption("Real-time analytics dashboard — auto refreshes every 60s")


health = fetch("/health")
if health:
    st.success("● Live")
    if st.button("⏹ Stop Token-optimeeee"):
        try:
            requests.post(f"{API_BASE}/shutdown", timeout=2)
            st.warning("Token-optimeeee is shutting down...")
        except:
            st.warning("Stopping...")
else:
    st.error("● Offline")
    
    
st.divider()

# ── wick live session ─────────────────────────────────────────────────────────
wick = fetch_wick()
if wick:
    # auto-save baseline on first load if not already saved
    if not os.path.exists("storage/wick_baseline.json"):
        save_wick_baseline(wick)

    delta = get_wick_delta(wick)

    st.subheader("🔥 Live Session")
    w1, w2, w3, w4 = st.columns(4)
    
    tokens_delta = delta['tokens'] if delta else 0
    cost_inr_delta = delta['cost_inr'] if delta else 0.0
    cost_usd_delta = delta['cost_usd'] if delta else 0.0
    turns_delta = delta['turns'] if delta else 0

    w1.metric("Tokens Used", f"{wick.get('totalTokens', 0):,}", 
              delta=f"+{tokens_delta:,} this session" if tokens_delta else None)
    w2.metric("Cost (₹)", f"₹{wick.get('totalCostINR', 0):.2f}",
              delta=f"+₹{cost_inr_delta:.2f} this session" if cost_inr_delta else None)
    w3.metric("Cost ($)", f"${wick.get('totalCostUSD', 0):.4f}",
              delta=f"+${cost_usd_delta:.4f} this session" if cost_usd_delta else None)
    w4.metric("Turns", wick.get('totalTurns', 0),
              delta=f"+{turns_delta} this session" if turns_delta else None)

    col1, col2 = st.columns([1, 4])
    with col1:
        if st.button("🔄 Reset Session"):
            save_wick_baseline(wick)
            st.success("Session reset!")
else:
    st.info("Wick not running — open Claude Desktop to see live token data.")
    
st.divider()
    
# ── token analysis ────────────────────────────────────────────────────────────
analysis = fetch("/metrics/token_analysis")
if analysis:
    st.subheader("📊 Token Analysis — Impact")
    st.caption("Token counts measured with tiktoken. Cost estimates based on Claude Sonnet 4.6 pricing and Rs.84 as dollar price in India  — actual cost may vary depending on your model.")

    a1, a2, a3, a4 = st.columns(4)
    a1.metric("Schema Tokens Without ", f"{analysis['schema_tokens_without_tom']:,}")
    a2.metric("Schema Tokens With ", f"{analysis['schema_tokens_with_tom']:,}")
    a3.metric("Total Tokens Saved", f"{analysis['total_saved']:,}")
    a4.metric("Reduction", f"{analysis['pct_saved']}%")

    b1, b2, b3, b4 = st.columns(4)
    b1.metric("Response Tokens Before Trim", f"{analysis['tokens_before_trim']:,}")
    b2.metric("Response Tokens After Trim", f"{analysis['tokens_after_trim']:,}")
    b3.metric("Cost Saved (₹)", f"₹{analysis['cost_saved_inr']:.4f}")
    b4.metric("Cost Saved ($)", f"${analysis['cost_saved_usd']:.6f}")

    # real groq token usage
    groq_data = fetch("/metrics/groq_usage")
    if groq_data:
        st.divider()
        st.subheader("🤖 Real Groq Token Usage (Exact API Counts)")
        st.caption("These are actual token counts returned by Groq API — not estimates")
        g1, g2, g3 = st.columns(3)
        g1.metric("Total Prompt Tokens", f"{groq_data['total_prompt_tokens']:,}")
        g2.metric("Total Completion Tokens", f"{groq_data['total_completion_tokens']:,}")
        g3.metric("Total Groq Tokens", f"{groq_data['total_groq_tokens']:,}")

    # savings breakdown bar
    savings_data = {
        "Source": ["Schema Trimming", "Response Trimming"],
        "Tokens Saved": [
            analysis["schema_saved"],
            analysis["trim_saved"]
        ]
    }
    df_savings = pd.DataFrame(savings_data)
    fig = px.bar(df_savings, x="Source", y="Tokens Saved",
                 color="Source",
                 color_discrete_sequence=["#4f9cf9", "#f97b4f"])
    fig.update_layout(
        paper_bgcolor="#0f1117",
        plot_bgcolor="#1a1d27",
        font_color="#e0e0e0",
        height=250,
        showlegend=False,
        margin=dict(t=10, b=10)
    )
    st.plotly_chart(fig, width='stretch')

st.divider()

# ── summary metrics ───────────────────────────────────────────────────────────
summary = fetch("/metrics/summary")
if summary:
    st.subheader("Overall Summary")
    c1, c2, c3, c4, c5 = st.columns(5)
    c1.metric("Total Calls", summary["total_calls"])
    c2.metric("Cache Hits", summary["cache_hits"])
    c3.metric("Cache Hit Rate", f"{summary['hit_rate_pct']}%")
    c4.metric("Trim Tokens Saved", f"{summary['total_trim_saved']:,}")
    c5.metric("Schema Tokens Saved", f"{summary['total_schema_saved']:,}")

    st.divider()

    trim = summary["total_trim_saved"] or 0
    schema = summary["total_schema_saved"] or 0

    if trim > 0 or schema > 0:
        st.subheader("Token Savings Breakdown")
        fig = go.Figure(go.Pie(
            labels=["Trim Savings", "Schema Savings"],
            values=[trim, schema],
            hole=0.5,
            marker_colors=["#4f9cf9", "#4fca7a"]
        ))
        fig.update_layout(
            paper_bgcolor="#0f1117",
            plot_bgcolor="#0f1117",
            font_color="#e0e0e0",
            showlegend=True,
            height=300,
            margin=dict(t=20, b=20)
        )
        st.plotly_chart(fig, width='stretch')

st.divider()

# ── tool stats ────────────────────────────────────────────────────────────────
tool_stats = fetch("/metrics/tools")
if tool_stats and len(tool_stats) > 0:
    st.subheader("Tool Usage")
    df_tools = pd.DataFrame(tool_stats)
    fig2 = px.bar(
        df_tools,
        x="tool_name",
        y="calls",
        color="hits",
        labels={"tool_name": "Tool", "calls": "Total Calls", "hits": "Cache Hits"},
        color_continuous_scale="Blues"
    )
    fig2.update_layout(
        paper_bgcolor="#0f1117",
        plot_bgcolor="#1a1d27",
        font_color="#e0e0e0",
        height=300,
        margin=dict(t=20, b=20)
    )
    st.plotly_chart(fig2, width='stretch')

st.divider()

# ── indexed documents ─────────────────────────────────────────────────────────
docs = fetch("/metrics/indexed_docs")
if docs is not None:
    st.subheader(f"Indexed Documents ({len(docs)})")
    if docs:
        df_docs = pd.DataFrame(docs)
        st.dataframe(df_docs, width='stretch', hide_index=True)
    else:
        st.info("No documents indexed yet.")

st.divider()

# ── conversation breakdown ────────────────────────────────────────────────────
conv_data = fetch("/metrics/conversations")
if conv_data:
    st.subheader("💬 Per-Conversation Token Savings")
    st.caption("15-min idle gap = new conversation")
    df_conv = pd.DataFrame(conv_data)
    for col in ["total_saved", "trim_saved", "schema_saved", "cache_hits", "total_calls"]:
        if col in df_conv.columns:
            df_conv[col] = df_conv[col].fillna(0).astype(int)
    st.dataframe(
        df_conv[["conversation_id", "started_at", "total_calls", "cache_hits", "trim_saved", "schema_saved", "total_saved"]],
        width='stretch',
        hide_index=True
    )
    if len(df_conv) > 1:
        fig_conv = px.bar(
            df_conv,
            x="conversation_id",
            y="total_saved",
            color="total_saved",
            labels={"conversation_id": "Conversation", "total_saved": "Tokens Saved"},
            color_continuous_scale="Blues"
        )
        fig_conv.update_layout(
            paper_bgcolor="#0f1117",
            plot_bgcolor="#1a1d27",
            font_color="#e0e0e0",
            height=280,
            showlegend=False,
            margin=dict(t=10, b=10)
        )
        st.plotly_chart(fig_conv, width='stretch')
        
        
st.divider()       
# ── recent events ─────────────────────────────────────────────────────────────
events = fetch("/metrics/events?limit=50")
if events and len(events) > 0:
    st.subheader("Recent Events")
    df = pd.DataFrame(events)

    if "cache_hit" in df.columns:
        df["cache_hit"] = df["cache_hit"].apply(lambda x: "✅ HIT" if x else "❌ MISS")
    if "success" in df.columns:
        df["success"] = df["success"].apply(lambda x: "✅" if x else "❌")
    if "trim_saved" in df.columns:
        df["trim_saved"] = df["trim_saved"].fillna(0).astype(int)
    if "schema_tokens_saved" in df.columns:
        df["schema_tokens_saved"] = df["schema_tokens_saved"].fillna(0).astype(int)

    display_cols = ["timestamp", "tool_name", "query", "cache_hit",
                    "trim_saved", "schema_tokens_saved", "success"]
    display_cols = [c for c in display_cols if c in df.columns]
    st.dataframe(df[display_cols], width='stretch', hide_index=True)
else:
    st.info("No events yet. Start using Token-optimeee to see data here.")