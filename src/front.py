import streamlit as st
import requests
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
from streamlit_autorefresh import st_autorefresh
import json,os


st_autorefresh(interval=60000, key="dashboard_refresh")

API_BASE = "http://localhost:8000"

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
    except Exception as e:
        st.error(f"Failed to fetch {endpoint}: {e}")
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
else:
    st.error("● Offline")

st.divider()

# ── wick live session ─────────────────────────────────────────────────────────
wick = fetch_wick()
if wick:
    st.subheader("🔥 Live Claude Session (via Wick)")
    w1, w2, w3, w4, w5 = st.columns(5)
    w1.metric("Total Tokens Used", f"{wick.get('totalTokens', 0):,}")
    w2.metric("Cost (₹)", f"₹{wick.get('totalCostINR', 0):.2f}")
    w3.metric("Cost ($)", f"${wick.get('totalCostUSD', 0):.4f}")
    w4.metric("Sessions", wick.get('sessionCount', 0))
    w5.metric("Total Turns", wick.get('totalTurns', 0))
    
    st.divider()
    st.subheader("🎬 This Test Session")
    if st.button("Start Test Session"):
        save_wick_baseline(wick)
        st.success("Baseline saved! Run your test cases now.")

    delta = get_wick_delta(wick)
    if delta:
        d1, d2, d3,d4 = st.columns(4)
        d1.metric("Tokens This Session", f"{delta['tokens']:,}")
        d2.metric("Cost This Session (₹)", f"₹{delta['cost_inr']:.2f}")
        d3.metric("Cost This Session ($)", f"${delta['cost_usd']:.4f}")
        d4.metric("Turns This Session", delta['turns'])
    else:
        st.info("Click 'Start Test Session' to begin tracking.")
else:
    st.info("Wick not running — start Claude Desktop to see live token data.")

st.divider()

# ── token analysis ────────────────────────────────────────────────────────────
analysis = fetch("/metrics/token_analysis")
if analysis:
    st.subheader("📊 Token Analysis — Impact")
    st.caption("All numbers are real measurements  — no estimates or baselines")

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
    st.plotly_chart(fig, use_container_width=True)

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
        st.plotly_chart(fig, use_container_width=True)

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
    st.plotly_chart(fig2, use_container_width=True)

st.divider()

# ── indexed documents ─────────────────────────────────────────────────────────
docs = fetch("/metrics/indexed_docs")
if docs is not None:
    st.subheader(f"Indexed Documents ({len(docs)})")
    if docs:
        df_docs = pd.DataFrame(docs)
        st.dataframe(df_docs, use_container_width=True, hide_index=True)
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
        use_container_width=True,
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
        st.plotly_chart(fig_conv, use_container_width=True)
        
        
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
    st.dataframe(df[display_cols], use_container_width=True, hide_index=True)
else:
    st.info("No events yet. Start using Token-optimeee to see data here.")