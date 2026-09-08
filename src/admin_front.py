import streamlit as st
import requests
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
from streamlit_autorefresh import st_autorefresh
import os



API_BASE = os.getenv("ADMIN_API_BASE", "http://localhost:7737")
ADMIN_SECRET = os.getenv("ADMIN_SECRET", "")

# Shared pricing constants 
GROQ_PRICING = {"input": 0.59 / 1_000_000, "output": 0.79 / 1_000_000}
CLAUDE_MODELS = {
    "Haiku 3.5":  0.80,
    "Sonnet 3.5": 3.00,
    "Sonnet 4.6": 3.00,
    "Opus 4":    15.00,
}

st.set_page_config(
    page_title="Token-Optime Admin",
    page_icon="🦾",
    layout="wide",
    initial_sidebar_state="collapsed",
)
st_autorefresh(interval=60000, key="admin_refresh")
st.markdown("""
<style>
    .stMetric { background: #1a1d27; border-radius: 12px; padding: 15px; border: 1px solid #2d2d3d; }
</style>
""", unsafe_allow_html=True)



def fetch(endpoint):
    try:
        headers = {"X-Admin-Token": ADMIN_SECRET} if ADMIN_SECRET else {}
        r = requests.get(f"{API_BASE}{endpoint}", headers=headers, timeout=5)
        r.raise_for_status()
        return r.json()
    except Exception as e:
        st.warning(f"Could not load {endpoint}: {e}")
        return None


st.title("🦾 Token-Optime Admin Dashboard")



health = fetch("/health")
if health:
    st.success(
        f"● Live  |  Uptime: {health.get('uptime', '?')}  |  "
        f"Total Events: {health.get('total_events_logged', 0)}"
    )
else:
    st.error("● Server Offline")

st.divider()


# ------------------------------------------------------------------------------------------------------------------------------------------------------
# Platform overview

overview = fetch("/admin/overview")
if overview:
    st.subheader("🏷️ Platform Overview")
    o1, o2, o3, o4, o5, o6 = st.columns(6)
    o1.metric("Total Users", overview.get("total_users", 0))
    o2.metric("Total Calls", overview.get("total_calls", 0))
    o3.metric("Cache Hit Rate", f"{overview.get('hit_rate_pct', 0)}%")
    o4.metric("Tokens Saved", f"{overview.get('total_tokens_saved', 0):,}")
    o5.metric("Calls Today", overview.get("calls_today", 0))
    o6.metric("Active Users Today", overview.get("active_users_today", 0))

    gp = overview.get("total_groq_tokens", 0) or 0
    groq_cost_usd = gp * GROQ_PRICING["input"]
    st.caption(f"🤿 Platform Groq Cost: ${groq_cost_usd:.4f}")

st.divider()

# ------------------------------------------------------------------------------------------------------------------------------------------------------
# Platform timeseries

st.subheader("🎯 Platform Activity Over Time")
ts_col, _ = st.columns([2, 6])
with ts_col:
    ts_hours = st.selectbox(
        "Window:",
        [6, 24, 48, 168],
        format_func=lambda x: {6: "Last 6h", 24: "Last 24h", 48: "Last 48h", 168: "Last 7 days"}[x],
    )

ts_data = fetch(f"/admin/timeseries?hours={ts_hours}")
if ts_data and len(ts_data) > 0:
    df_ts = pd.DataFrame(ts_data)
    df_ts["hour"] = pd.to_datetime(df_ts["hour"])
    col1, col2 = st.columns(2)
    with col1:
        fig1 = px.line(df_ts, x="hour", y="total_calls", title="Total Calls per Hour",
                       color_discrete_sequence=["#4f9cf9"])
        fig1.update_layout(paper_bgcolor="#0f1117", plot_bgcolor="#1a1d27",
                           font_color="#e0e0e0", height=260, margin=dict(t=40, b=10))
        st.plotly_chart(fig1, use_container_width=True)
    with col2:
        if "active_users" in df_ts.columns:
            fig2 = px.line(df_ts, x="hour", y="active_users", title="Active Users per Hour",
                           color_discrete_sequence=["#4fca7a"])
            fig2.update_layout(paper_bgcolor="#0f1117", plot_bgcolor="#1a1d27",
                               font_color="#e0e0e0", height=260, margin=dict(t=40, b=10))
            st.plotly_chart(fig2, use_container_width=True)
else:
    st.info("Not enough data yet.")

st.divider()


# ------------------------------------------------------------------------------------------------------------------------------------------------------
# All users

st.subheader("👩‍💻 All Users")
users = fetch("/admin/users")
if users:
    df_users = pd.DataFrame(users)
    df_users["groq_cost_usd"] = (
        df_users["groq_prompt_tokens"] * GROQ_PRICING["input"]
        + df_users["groq_completion_tokens"] * GROQ_PRICING["output"]
    ).round(6)

    fig_users = px.bar(
        df_users.head(10), x="user_id", y="total_calls",
        color="tokens_saved", color_continuous_scale="Blues",
        title="Top 10 Users by Calls",
    )
    fig_users.update_layout(paper_bgcolor="#0f1117", plot_bgcolor="#1a1d27",
                            font_color="#e0e0e0", height=300, margin=dict(t=40, b=10))
    st.plotly_chart(fig_users, use_container_width=True)

    display_cols = [c for c in
                    ["user_id", "total_calls", "cache_hits", "hit_rate_pct",
                     "tokens_saved", "groq_cost_usd", "first_seen", "last_seen"]
                    if c in df_users.columns]
    st.dataframe(df_users[display_cols], use_container_width=True, hide_index=True)

st.divider()


# ------------------------------------------------------------------------------------------------------------------------------------------------------
# User drilldown

st.subheader("📝 User Drilldown")
if users:
    user_ids = [u["user_id"] for u in users]
    selected_user = st.selectbox("Select a user:", user_ids)

    if selected_user:
        drilldown = fetch(f"/admin/user/{selected_user}")
        if drilldown:
            s = drilldown.get("summary", {})
            d1, d2, d3, d4 = st.columns(4)
            d1.metric("Total Calls",  s.get("total_calls", 0))
            d2.metric("Cache Hits",   s.get("cache_hits", 0))
            d3.metric("Tokens Saved", f"{s.get('tokens_saved', 0):,}")
            d4.metric("First Seen",   str(s.get("first_seen", ""))[:10])

            tools = drilldown.get("tools", [])
            if tools:
                df_tools = pd.DataFrame(tools)
                fig_t = px.bar(df_tools, x="tool_name", y="calls",
                               title=f"Tool Usage — {selected_user}",
                               color_discrete_sequence=["#f97b4f"])
                fig_t.update_layout(paper_bgcolor="#0f1117", plot_bgcolor="#1a1d27",
                                    font_color="#e0e0e0", height=260, margin=dict(t=40, b=10))
                st.plotly_chart(fig_t, use_container_width=True)

            events = drilldown.get("recent_events", [])
            if events:
                st.caption("Last 50 events")
                df_ev = pd.DataFrame(events)
                if "cache_hit" in df_ev.columns:
                    df_ev["cache_hit"] = df_ev["cache_hit"].apply(
                        lambda x: "✅ HIT" if x else "❌ MISS"
                    )
                st.dataframe(df_ev, use_container_width=True, hide_index=True)

st.divider()


# ------------------------------------------------------------------------------------------------------------------------------------------------------
# Platform cache performance

st.subheader("🪄 Platform Cache Performance")
summary = fetch("/metrics/summary")
if summary:
    s1, s2, s3, s4 = st.columns(4)
    s1.metric("Total Calls",    summary.get("total_calls", 0))
    s2.metric("Cache Hits",     summary.get("cache_hits", 0))
    s3.metric("Cache Hit Rate", f"{summary.get('hit_rate_pct', 0)}%")
    s4.metric("Tokens Saved",   f"{summary.get('total_tokens_saved', 0):,}")

    hits   = summary.get("cache_hits", 0)
    misses = summary.get("total_calls", 0) - hits
    if hits > 0 or misses > 0:
        fig_cache = go.Figure(go.Pie(
            labels=["Cache Hits", "Cache Misses"],
            values=[hits, misses],
            hole=0.5,
            marker_colors=["#4fca7a", "#f97b4f"],
        ))
        fig_cache.update_layout(paper_bgcolor="#0f1117", plot_bgcolor="#0f1117",
                                font_color="#e0e0e0", height=280, margin=dict(t=20, b=20))
        st.plotly_chart(fig_cache, use_container_width=True)

st.divider()


# ------------------------------------------------------------------------------------------------------------------------------------------------------
# Platform tool usage

st.subheader("🔧 Platform Tool Usage")
tool_stats = fetch("/metrics/tools")
if tool_stats:
    df_tools = pd.DataFrame(tool_stats)
    fig_tools = px.bar(
        df_tools, x="tool_name", y="calls", color="hits",
        color_continuous_scale="Blues",
    )
    fig_tools.update_layout(paper_bgcolor="#0f1117", plot_bgcolor="#1a1d27",
                            font_color="#e0e0e0", height=300, margin=dict(t=20, b=20))
    st.plotly_chart(fig_tools, use_container_width=True)
    st.dataframe(df_tools, use_container_width=True, hide_index=True)

st.divider()


# ------------------------------------------------------------------------------------------------------------------------------------------------------
# Live event feed

st.subheader("💿 Live Event Feed")
feed_col, _ = st.columns([2, 6])
with feed_col:
    feed_mode = st.selectbox("Show events for:", ["All Users", "Specific User"])

if feed_mode == "All Users":
    events_data = fetch("/admin/events?limit=100")
    if events_data:
        df_all = pd.DataFrame(events_data)
        if "cache_hit" in df_all.columns:
            df_all["cache_hit"] = df_all["cache_hit"].apply(lambda x: "✅ HIT" if x else "❌ MISS")
        if "success" in df_all.columns:
            df_all["success"] = df_all["success"].apply(lambda x: "✅" if x else "❌")
        st.dataframe(df_all, use_container_width=True, hide_index=True)
    else:
        st.info("No events yet.")
else:
    if users:
        user_ids = [u["user_id"] for u in users]
        selected = st.selectbox("Pick a user:", user_ids, key="feed_user")
        drilldown = fetch(f"/admin/user/{selected}")
        if drilldown:
            events = drilldown.get("recent_events", [])
            if events:
                df_ev = pd.DataFrame(events)
                if "cache_hit" in df_ev.columns:
                    df_ev["cache_hit"] = df_ev["cache_hit"].apply(
                        lambda x: "✅ HIT" if x else "❌ MISS"
                    )
                if "success" in df_ev.columns:
                    df_ev["success"] = df_ev["success"].apply(lambda x: "✅" if x else "❌")
                st.dataframe(df_ev, use_container_width=True, hide_index=True)
            else:
                st.info("No events for this user yet.")
    else:
        st.info("No users found.")