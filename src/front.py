import streamlit as st
import requests
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
from streamlit_autorefresh import st_autorefresh
import json, os

from token_optimise.config import settings 



API_BASE = os.getenv("API_BASE", f"http://localhost:{settings.api_port}")
_BASELINE_PATH = os.path.join(
    os.path.expanduser("~"), ".token_optimise", "storage", "wick_baseline.json"
)

# Shared pricing 
GROQ_PRICING = {
    "input":  0.59 / 1_000_000,
    "output": 0.79 / 1_000_000,
}
CLAUDE_MODELS = {
    "Haiku 3.5":  0.80,
    "Sonnet 3.5": 3.00,
    "Sonnet 4.6": 3.00,
    "Opus 4":    15.00,
}


st.set_page_config(
    page_title="Token-Optime",
    page_icon="🦾",
    layout="wide",
    initial_sidebar_state="collapsed",
)

st_autorefresh(interval=60000, key="dashboard_refresh")

st.markdown("""
<style>
    .stMetric {
        background: #1a1d27;
        border-radius: 12px;
        padding: 15px;
        border: 1px solid #2d2d3d;
    }
    .estimate-note {
        color: #888;
        font-size: 0.75rem;
        margin-top: -10px;
        margin-bottom: 10px;
    }
</style>
""", unsafe_allow_html=True)


# ------------------------------------------------------------------------------------------------------------------------------------------------------
#  helpers 

def fetch(endpoint):
    try:
        r = requests.get(f"{API_BASE}{endpoint}", timeout=5)
        r.raise_for_status()
        return r.json()
    except requests.exceptions.ConnectionError:
        return None
    except Exception as e:
        st.warning(f"Could not load {endpoint}: {e}")
        return None


@st.cache_data(ttl=3600)
def get_live_inr_rate():
    """Fetch live USD/INR rate. Falls back to 84 if unavailable."""
    try:
        r = requests.get("https://api.frankfurter.app/latest?from=USD&to=INR", timeout=4)
        r.raise_for_status()
        rate = r.json()["rates"]["INR"]
        return round(rate, 2), True
    except Exception:
        return 84.0, False




def save_wick_baseline(wick):
    os.makedirs(os.path.dirname(_BASELINE_PATH), exist_ok=True)
    with open(_BASELINE_PATH, "w") as f:
        json.dump({
            "tokens":   wick.get("totalTokens", 0),
            "cost_usd": wick.get("totalCostUSD", 0),
            "cost_inr": wick.get("totalCostINR", 0),
            "turns":    wick.get("totalTurns", 0),
        }, f)


def get_wick_delta(wick):
    if not os.path.exists(_BASELINE_PATH):
        return None
    with open(_BASELINE_PATH) as f:
        baseline = json.load(f)
    return {
        "tokens": wick.get("totalTokens", 0) - baseline["tokens"],
        "cost_usd": wick.get("totalCostUSD", 0) - baseline["cost_usd"],
        "turns": wick.get("totalTurns", 0) - baseline["turns"],
        "cost_inr": wick.get("totalCostINR", 0) - baseline["cost_inr"],
    }


def fetch_wick():
    try:
        r = requests.get("http://localhost:6789/api/summary", timeout=3)
        r.raise_for_status()
        return r.json()
    except Exception:
        return None


# ------------------------------------------------------------------------------------------------------------------------------------------------------
#  header 
st.title("🦾 Token-Optime")
st.caption("Real-time analytics dashboard — auto refreshes every 60s")

health = fetch("/health")
if health:
    col_status, col_btn = st.columns([6, 1])
    with col_status:
        st.success(
            f"● Live  |  Uptime: {health.get('uptime', '?')}  |  "
            f"Tools indexed: {health.get('tools_indexed', 0)}  |  "
            f"Sessions active: {health.get('sessions_active', 0)}"
        )
    with col_btn:
        if st.button("⏹ Stop"):
            try:
                requests.post(f"{API_BASE}/shutdown", timeout=2)
                st.warning("Shutting down...")
            except Exception:
                pass
else:
    st.error("● Offline — run ./token.sh start")

st.divider()

# ------------------------------------------------------------------------------------------------------------------------------------------------------
# live INR rate 
inr_rate, rate_is_live = get_live_inr_rate()
if rate_is_live:
    st.caption(f"💱 Live USD/INR rate: ₹{inr_rate} (refreshes hourly)")
else:
    st.caption(f"💱 USD/INR rate: ₹{inr_rate} (fallback — could not fetch live rate)")

st.divider()


# ------------------------------------------------------------------------------------------------------------------------------------------------------
#  period selector 

st.subheader("📅 Period Summary")
period_col, _ = st.columns([2, 6])
with period_col:
    period_choice = st.selectbox(
        "Show data for:",
        ["today", "yesterday", "week", "all"],
        format_func=lambda x: {
            "today": "Today", "yesterday": "Yesterday",
            "week": "Last 7 Days", "all": "All Time",
        }[x],
    )

period_data = fetch(f"/metrics/period?period={period_choice}")
if period_data:
    p1, p2, p3, p4, p5 = st.columns(5)
    p1.metric("Total Calls",  period_data.get("total_calls", 0))
    p2.metric("Cache Hits",   period_data.get("cache_hits", 0))

    total_calls = period_data.get("total_calls", 1) or 1
    cache_hits  = period_data.get("cache_hits", 0)
    hit_rate    = round(cache_hits / total_calls * 100, 1)
    p3.metric("Cache Hit Rate", f"{hit_rate}%")
    p4.metric("Tokens Saved",   f"{period_data.get('total_saved', 0):,}")

    gp = period_data.get("groq_prompt", 0) or 0
    gc = period_data.get("groq_completion", 0) or 0
    groq_cost_usd = (gp * GROQ_PRICING["input"]) + (gc * GROQ_PRICING["output"])
    groq_cost_inr = groq_cost_usd * inr_rate
    p5.metric("Groq Cost (actual)", f"₹{groq_cost_inr:.4f} / ${groq_cost_usd:.6f}")

st.divider()


# ------------------------------------------------------------------------------------------------------------------------------------------------------
# Live session (wick)

wick = fetch_wick()
if wick:
    if not os.path.exists(_BASELINE_PATH):
        save_wick_baseline(wick)
    delta = get_wick_delta(wick)

    st.subheader("🔥 Live Session (Wick)")
    w1, w2, w3, w4 = st.columns(4)
    tokens_delta   = delta["tokens"] if delta else 0
    cost_inr_delta = delta["cost_inr"] if delta else 0.0
    cost_usd_delta = delta["cost_usd"] if delta else 0.0
    turns_delta    = delta["turns"]    if delta else 0

    w1.metric("Tokens Used", f"{wick.get('totalTokens', 0):,}",
              delta=f"+{tokens_delta:,} this session" if tokens_delta else None)
    w2.metric("Cost (₹)", f"₹{wick.get('totalCostINR', 0):.2f}",
              delta=f"+₹{cost_inr_delta:.2f}" if cost_inr_delta else None)
    w3.metric("Cost ($)", f"${wick.get('totalCostUSD', 0):.4f}",
              delta=f"+${cost_usd_delta:.4f}" if cost_usd_delta else None)
    w4.metric("Turns", wick.get("totalTurns", 0),
              delta=f"+{turns_delta}" if turns_delta else None)

    if st.button("🔄 Reset Session Baseline"):
        save_wick_baseline(wick)
        st.success("Session reset!")
else:
    st.info("Wick not running — open Claude Desktop to see live session data.")

st.divider()

# Token analysis
analysis  = fetch("/metrics/token_analysis")
groq_data = fetch("/metrics/groq_usage")

if analysis:
    st.subheader("📊 Token Analysis")

    groq_total_cost_usd = 0.0
    groq_total_cost_inr = 0.0
    if groq_data:
        gp_total = groq_data.get("total_prompt_tokens", 0) or 0
        gc_total = groq_data.get("total_completion_tokens", 0) or 0
        groq_total_cost_usd = (gp_total * GROQ_PRICING["input"]) + (gc_total * GROQ_PRICING["output"])
        groq_total_cost_inr = groq_total_cost_usd * inr_rate

    tokens_saved = analysis.get("total_saved", 0)
    claude_costs = {
        model: round(tokens_saved * (price / 1_000_000), 6)
        for model, price in CLAUDE_MODELS.items()
    }
    cheapest_model = min(CLAUDE_MODELS, key=CLAUDE_MODELS.get)
    priciest_model = max(CLAUDE_MODELS, key=CLAUDE_MODELS.get)
    cost_range_usd = f"${claude_costs[cheapest_model]:.4f} – ${claude_costs[priciest_model]:.4f}"
    cost_range_inr = (
        f"₹{claude_costs[cheapest_model] * inr_rate:.2f} – "
        f"₹{claude_costs[priciest_model] * inr_rate:.2f}"
    )

    a1, a2, a3, a4 = st.columns(4)
    a1.metric("Schema Tokens — Estimated Baseline", f"{analysis['schema_tokens_without_tom']:,}")
    a2.metric("Schema Tokens — With TOM",           f"{analysis['schema_tokens_with_tom']:,}")
    a3.metric("Total Tokens Saved",                 f"{analysis['total_saved']:,}")
    a4.metric("Reduction",                          f"{analysis['pct_saved']}%")

    st.markdown(
        "<p class='estimate-note'>⚠️ 'Estimated Baseline' = sum of all tool schemas. "
        "Actual Claude context may differ. Reduction % is relative to this estimate.</p>",
        unsafe_allow_html=True,
    )

    b1, b2, b3, b4 = st.columns(4)
    b1.metric("Response Tokens Before Trim", f"{analysis['tokens_before_trim']:,}")
    b2.metric("Response Tokens After Trim",  f"{analysis['tokens_after_trim']:,}")

    if groq_data:
        b3.metric(
            "Groq Cost (actual ✅)",
            f"₹{groq_total_cost_inr:.4f}",
            help=f"${groq_total_cost_usd:.6f}",
        )
    b4.metric(
        "Claude Cost Saved (estimated ⚠️)",
        cost_range_inr,
        help=f"{cost_range_usd} — depends on which Claude model you use.",
    )

    st.markdown(
        "<p class='estimate-note'>✅ Groq cost = real measured cost ($0.59/$0.79 per 1M tokens). "
        f"⚠️ Claude cost saved = estimate across models. "
        f"💱 Rate: ₹{inr_rate}/$ ({'live' if rate_is_live else 'fallback'}).</p>",
        unsafe_allow_html=True,
    )

    df_savings = pd.DataFrame({
        "Source": ["Schema Trimming", "Response Trimming"],
        "Tokens Saved": [analysis["schema_saved"], analysis["trim_saved"]],
    })
    fig = px.bar(
        df_savings, x="Source", y="Tokens Saved", color="Source",
        color_discrete_sequence=["#4f9cf9", "#f97b4f"],
        title="Token Savings Breakdown",
    )
    fig.update_layout(paper_bgcolor="#0f1117", plot_bgcolor="#1a1d27",
                      font_color="#e0e0e0", height=250,
                      showlegend=False, margin=dict(t=40, b=10))
    st.plotly_chart(fig, use_container_width=True)

st.divider()


# ------------------------------------------------------------------------------------------------------------------------------------------------------
#  groq usage detail 

if groq_data:
    st.subheader("🤖 Groq Token Usage (Real API Counts ✅)")
    st.caption("Exact token counts returned by Groq API — not estimates")
    g1, g2, g3, g4, g5 = st.columns(5)
    g1.metric("Prompt Tokens",     f"{groq_data['total_prompt_tokens']:,}")
    g2.metric("Completion Tokens", f"{groq_data['total_completion_tokens']:,}")
    g3.metric("Total Groq Tokens", f"{groq_data['total_groq_tokens']:,}")
    g4.metric("Groq Cost ($)",     f"${groq_total_cost_usd:.6f}")
    g5.metric("Groq Cost (₹)",     f"₹{groq_total_cost_inr:.4f}")

st.divider()


# ------------------------------------------------------------------------------------------------------------------------------------------------------
#  time series 

st.subheader("📈 Activity Over Time")
ts_col, _ = st.columns([2, 6])
with ts_col:
    ts_hours = st.selectbox(
        "Window:", [6, 24, 48, 168],
        format_func=lambda x: {6: "Last 6h", 24: "Last 24h", 48: "Last 48h", 168: "Last 7 days"}[x],
    )

ts_data = fetch(f"/metrics/timeseries?hours={ts_hours}")
if ts_data and len(ts_data) > 0:
    df_ts = pd.DataFrame(ts_data)
    df_ts["hour"] = pd.to_datetime(df_ts["hour"])

    fig_ts1 = px.line(df_ts, x="hour", y="total_calls", title="Queries per Hour",
                      labels={"hour": "Time", "total_calls": "Queries"},
                      color_discrete_sequence=["#4f9cf9"])
    fig_ts1.update_layout(paper_bgcolor="#0f1117", plot_bgcolor="#1a1d27",
                          font_color="#e0e0e0", height=260, margin=dict(t=40, b=10))

    fig_ts2 = px.line(df_ts, x="hour", y=["schema_saved", "trim_saved"],
                      title="Tokens Saved per Hour",
                      labels={"hour": "Time", "value": "Tokens", "variable": "Type"},
                      color_discrete_sequence=["#4f9cf9", "#f97b4f"])
    fig_ts2.update_layout(paper_bgcolor="#0f1117", plot_bgcolor="#1a1d27",
                          font_color="#e0e0e0", height=260, margin=dict(t=40, b=10))

    col_ts1, col_ts2 = st.columns(2)
    with col_ts1:
        st.plotly_chart(fig_ts1, use_container_width=True)
    with col_ts2:
        st.plotly_chart(fig_ts2, use_container_width=True)
else:
    st.info("Not enough data yet — make a few queries in Claude Desktop first.")

st.divider()


# ------------------------------------------------------------------------------------------------------------------------------------------------------
#  overall summary 

summary = fetch("/metrics/summary")
if summary:
    st.subheader("Overall Summary (All Time)")
    c1, c2, c3, c4, c5 = st.columns(5)
    c1.metric("Total Calls",         summary["total_calls"])
    c2.metric("Cache Hits",          summary["cache_hits"])
    c3.metric("Cache Hit Rate",      f"{summary['hit_rate_pct']}%")
    c4.metric("Trim Tokens Saved",   f"{summary['total_trim_saved']:,}")
    c5.metric("Schema Tokens Saved", f"{summary['total_schema_saved']:,}")

    trim   = summary["total_trim_saved"] or 0
    schema = summary["total_schema_saved"] or 0
    if trim > 0 or schema > 0:
        fig_pie = go.Figure(go.Pie(
            labels=["Trim Savings", "Schema Savings"],
            values=[trim, schema],
            hole=0.5,
            marker_colors=["#4f9cf9", "#4fca7a"],
        ))
        fig_pie.update_layout(paper_bgcolor="#0f1117", plot_bgcolor="#0f1117",
                              font_color="#e0e0e0", height=300, margin=dict(t=20, b=20))
        st.plotly_chart(fig_pie, use_container_width=True)

st.divider()


# ------------------------------------------------------------------------------------------------------------------------------------------------------
#  tool usage 

tool_stats = fetch("/metrics/tools")
if tool_stats and len(tool_stats) > 0:
    st.subheader("Tool Usage")
    df_tools = pd.DataFrame(tool_stats)
    fig_tools = px.bar(
        df_tools, x="tool_name", y="calls", color="hits",
        labels={"tool_name": "Tool", "calls": "Total Calls", "hits": "Cache Hits"},
        color_continuous_scale="Blues",
    )
    fig_tools.update_layout(paper_bgcolor="#0f1117", plot_bgcolor="#1a1d27",
                            font_color="#e0e0e0", height=300, margin=dict(t=20, b=20))
    st.plotly_chart(fig_tools, use_container_width=True)

st.divider()


# ------------------------------------------------------------------------------------------------------------------------------------------------------
#  indexed documents 

docs = fetch("/metrics/indexed_docs")
if docs is not None:
    st.subheader(f"Indexed Documents ({len(docs)})")
    if docs:
        st.dataframe(pd.DataFrame(docs), use_container_width=True, hide_index=True)
    else:
        st.info("No documents indexed yet.")

st.divider()


# ------------------------------------------------------------------------------------------------------------------------------------------------------
#  per-conversation breakdown 

conv_data = fetch("/metrics/conversations")
if conv_data:
    st.subheader("💬 Per-Conversation Breakdown")
    st.caption("15-min idle gap = new conversation")
    df_conv = pd.DataFrame(conv_data)
    for col in ["total_saved", "trim_saved", "schema_saved", "cache_hits", "total_calls"]:
        if col in df_conv.columns:
            df_conv[col] = df_conv[col].fillna(0).astype(int)
    display_cols = [c for c in
                    ["conversation_id", "started_at", "total_calls",
                     "cache_hits", "trim_saved", "schema_saved", "total_saved"]
                    if c in df_conv.columns]
    st.dataframe(df_conv[display_cols], use_container_width=True, hide_index=True)

    if len(df_conv) > 1:
        fig_conv = px.bar(
            df_conv, x="conversation_id", y="total_saved", color="total_saved",
            labels={"conversation_id": "Conversation", "total_saved": "Tokens Saved"},
            color_continuous_scale="Blues",
        )
        fig_conv.update_layout(paper_bgcolor="#0f1117", plot_bgcolor="#1a1d27",
                               font_color="#e0e0e0", height=280,
                               showlegend=False, margin=dict(t=10, b=10))
        st.plotly_chart(fig_conv, use_container_width=True)

st.divider()


# ------------------------------------------------------------------------------------------------------------------------------------------------------
#  recent events 

events = fetch("/metrics/events?limit=50")
if events and len(events) > 0:
    st.subheader("Recent Events")
    df_ev = pd.DataFrame(events)
    if "cache_hit" in df_ev.columns:
        df_ev["cache_hit"] = df_ev["cache_hit"].apply(lambda x: "✅ HIT" if x else "❌ MISS")
    if "success" in df_ev.columns:
        df_ev["success"] = df_ev["success"].apply(lambda x: "✅" if x else "❌")
    for col in ["trim_saved", "schema_tokens_saved"]:
        if col in df_ev.columns:
            df_ev[col] = df_ev[col].fillna(0).astype(int)
    display_cols = [c for c in
                    ["timestamp", "tool_name", "query", "cache_hit",
                     "cache_similarity", "trim_saved", "schema_tokens_saved", "success"]
                    if c in df_ev.columns]
    st.dataframe(df_ev[display_cols], use_container_width=True, hide_index=True)
else:
    st.info("No events yet. Start using Token-Optime in Claude Desktop.")
    
    