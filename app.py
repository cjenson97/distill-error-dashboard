"""
Compliance Monitor Dashboard
Reads live error data from three Distill watchlists and displays them
broken down by area, jurisdiction, and priority banding.

Run with:
    streamlit run app.py
"""

import time
import threading
import pandas as pd
import streamlit as st
import plotly.express as px
import plotly.graph_objects as go
from datetime import datetime

from scraper import run_scrape
from banding import get_banding, BANDING_ORDER, BANDING_COLOURS

# ─── Page config ──────────────────────────────────────────────────────────────
st.set_page_config(
    page_title="Compliance Monitor Dashboard",
    page_icon="📡",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ─── Session state ─────────────────────────────────────────────────────────────
if "data" not in st.session_state:
    st.session_state.data = []
if "last_refresh" not in st.session_state:
    st.session_state.last_refresh = None
if "loading" not in st.session_state:
    st.session_state.loading = False

# ─── Helpers ───────────────────────────────────────────────────────────────────

def load_data() -> pd.DataFrame:
    raw = st.session_state.data
    if not raw:
        return pd.DataFrame()

    df = pd.DataFrame(raw)

    # Add banding column
    df["banding"] = df.apply(
        lambda r: get_banding(r["jurisdiction"], r["area"]), axis=1
    )
    df["banding_order"] = df["banding"].map(BANDING_ORDER).fillna(99)
    df["banding_colour"] = df["banding"].map(BANDING_COLOURS).fillna("#cccccc")

    # Fixable flag as readable text
    df["fixable_label"] = df["fixable"].map({True: "✅ Action needed", False: "⏳ Self-resolving"})

    return df.sort_values(["banding_order", "area", "jurisdiction"])


def refresh_data():
    """Trigger a scrape and store results in session state."""
    st.session_state.loading = True
    try:
        # Pass your Chrome user-data-dir here if you want to reuse browser session
        # e.g. user_data_dir = r"C:\Users\YOU\AppData\Local\Google\Chrome\User Data"
        user_data_dir = None
        rows = run_scrape(user_data_dir)
        st.session_state.data = rows
        st.session_state.last_refresh = datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S UTC")
    except Exception as e:
        st.error(f"Scrape failed: {e}")
    finally:
        st.session_state.loading = False


# ─── Sidebar ───────────────────────────────────────────────────────────────────
with st.sidebar:
    st.image("https://distill.io/assets/images/logo.svg", width=120)
    st.title("Compliance Monitor")
    st.markdown("---")

    # Auto-refresh settings
    auto_refresh = st.checkbox("🔄 Auto-refresh", value=True)
    refresh_mins = st.slider("Refresh interval (minutes)", 5, 60, 15, 5)

    if st.button("🔃 Refresh Now", use_container_width=True, type="primary"):
        with st.spinner("Scraping Distill…"):
            refresh_data()

    if st.session_state.last_refresh:
        st.caption(f"Last refresh: {st.session_state.last_refresh}")

    st.markdown("---")

    # Filters (populated after data loads)
    st.subheader("Filters")

    df_all = load_data()

    areas = ["All"] + sorted(df_all["area"].unique().tolist()) if not df_all.empty else ["All"]
    sel_area = st.selectbox("Compliance Area", areas)

    bandings = ["All", "1. High", "2. Medium", "3. Low", "4. Lowest"]
    sel_banding = st.selectbox("Min. Banding (FS/PC)", bandings)

    jurisdictions = ["All"] + sorted(df_all["jurisdiction"].dropna().unique().tolist()) if not df_all.empty else ["All"]
    sel_juris = st.selectbox("Jurisdiction", jurisdictions)

    error_types = ["All"] + sorted(df_all["error_type"].unique().tolist()) if not df_all.empty else ["All"]
    sel_etype = st.selectbox("Error Type", error_types)

    fixable_opts = ["All", "✅ Action needed", "⏳ Self-resolving"]
    sel_fixable = st.selectbox("Fixability", fixable_opts)


# ─── Auto-refresh trigger ──────────────────────────────────────────────────────
if auto_refresh and not st.session_state.loading:
    last = st.session_state.last_refresh
    needs_refresh = last is None or (
        (datetime.utcnow() - datetime.strptime(last, "%Y-%m-%d %H:%M:%S UTC")).seconds
        > refresh_mins * 60
    )
    if needs_refresh:
        with st.spinner("Auto-refreshing…"):
            refresh_data()
        st.rerun()

# ─── Apply filters ─────────────────────────────────────────────────────────────
df = load_data()

if not df.empty:
    if sel_area != "All":
        df = df[df["area"] == sel_area]
    if sel_banding != "All":
        df = df[df["banding_order"] <= BANDING_ORDER[sel_banding]]
    if sel_juris != "All":
        df = df[df["jurisdiction"] == sel_juris]
    if sel_etype != "All":
        df = df[df["error_type"] == sel_etype]
    if sel_fixable != "All":
        df = df[df["fixable_label"] == sel_fixable]

# ─── Main page ─────────────────────────────────────────────────────────────────
st.title("📡 Compliance Monitor Dashboard")
st.caption("Live error feed from Distill watchlists — Financial Services · Gambling Compliance · Payments Compliance")

if df.empty and not st.session_state.loading:
    st.info("No data loaded yet. Click **Refresh Now** in the sidebar to fetch live errors.")
    st.stop()

if st.session_state.loading:
    st.warning("⏳ Loading data from Distill…")
    st.stop()

# ── KPI row ────────────────────────────────────────────────────────────────────
total     = len(df)
high_band = len(df[df["banding"] == "1. High"])
actionable = len(df[df["fixable"] == True])
self_resolve = len(df[df["fixable"] == False])

col1, col2, col3, col4, col5 = st.columns(5)
col1.metric("Total Errors", total)
col2.metric("🔴 High Priority", high_band)
col3.metric("🟠 Medium", len(df[df["banding"] == "2. Medium"]))
col4.metric("✅ Action Needed", actionable)
col5.metric("⏳ Self-Resolving", self_resolve)

st.markdown("---")

# ── Charts row ─────────────────────────────────────────────────────────────────
chart_col1, chart_col2 = st.columns(2)

with chart_col1:
    st.subheader("Errors by Compliance Area & Banding")
    if not df.empty:
        area_band = (
            df.groupby(["area", "banding"])
            .size()
            .reset_index(name="count")
        )
        area_band["banding_order"] = area_band["banding"].map(BANDING_ORDER)
        area_band = area_band.sort_values("banding_order")
        fig1 = px.bar(
            area_band, x="area", y="count", color="banding",
            color_discrete_map=BANDING_COLOURS,
            category_orders={"banding": ["1. High", "2. Medium", "3. Low", "4. Lowest"]},
            labels={"area": "Area", "count": "Errors", "banding": "Banding"},
            barmode="stack",
        )
        fig1.update_layout(height=350, margin=dict(t=20, b=20))
        st.plotly_chart(fig1, use_container_width=True)

with chart_col2:
    st.subheader("Top 20 Jurisdictions by Error Count")
    if not df.empty:
        top_j = (
            df.groupby(["jurisdiction", "banding"])
            .size()
            .reset_index(name="count")
            .sort_values("count", ascending=False)
            .head(20)
        )
        fig2 = px.bar(
            top_j, x="count", y="jurisdiction", color="banding",
            color_discrete_map=BANDING_COLOURS,
            orientation="h",
            labels={"jurisdiction": "", "count": "Errors", "banding": "Banding"},
        )
        fig2.update_layout(height=400, margin=dict(t=20, b=20), yaxis={"categoryorder": "total ascending"})
        st.plotly_chart(fig2, use_container_width=True)

# ── Error type breakdown ────────────────────────────────────────────────────────
st.subheader("Error Type Breakdown")
if not df.empty:
    etype_counts = df["error_type"].value_counts().reset_index()
    etype_counts.columns = ["Error Type", "Count"]
    fig3 = px.pie(etype_counts, names="Error Type", values="Count", hole=0.4)
    fig3.update_layout(height=300, margin=dict(t=20, b=20))
    et_col1, et_col2 = st.columns([1, 2])
    with et_col1:
        st.plotly_chart(fig3, use_container_width=True)
    with et_col2:
        st.dataframe(etype_counts, use_container_width=True, hide_index=True)

st.markdown("---")

# ── Detail table ───────────────────────────────────────────────────────────────
st.subheader(f"📋 Error Details ({total} errors)")

if not df.empty:
    display_cols = {
        "area": "Area",
        "jurisdiction": "Jurisdiction",
        "banding": "Banding",
        "title": "Monitor Title",
        "error_type": "Error Type",
        "explanation": "Plain English Explanation",
        "fixable_label": "Fixability",
        "snippet": "Snippet",
        "freq": "Check Frequency",
        "last_checked": "Last Checked",
        "monitor_status": "Monitor Status",
    }

    df_display = df.rename(columns=display_cols)[list(display_cols.values())]

    st.dataframe(
        df_display,
        use_container_width=True,
        hide_index=True,
        column_config={
            "Banding": st.column_config.TextColumn(width="small"),
            "Plain English Explanation": st.column_config.TextColumn(width="large"),
            "Snippet": st.column_config.TextColumn(width="medium"),
        }
    )

    # Download button
    csv = df_display.to_csv(index=False)
    st.download_button(
        label="⬇️ Download as CSV",
        data=csv,
        file_name=f"compliance_errors_{datetime.utcnow().strftime('%Y%m%d_%H%M')}.csv",
        mime="text/csv",
    )
