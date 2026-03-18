import pandas as pd
import streamlit as st
import plotly.express as px
from datetime import datetime

from scraper import run_scrape
from banding import get_banding, BANDING_ORDER, BANDING_COLOURS

st.set_page_config(
    page_title="Compliance Monitor Dashboard",
    page_icon="📡",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ── Session state ──────────────────────────────────────────────────────────────
if "data" not in st.session_state:
    st.session_state.data = []
if "last_refresh" not in st.session_state:
    st.session_state.last_refresh = None
if "is_scraping" not in st.session_state:
    st.session_state.is_scraping = False

# ── Helpers ────────────────────────────────────────────────────────────────────
def load_data() -> pd.DataFrame:
    if not st.session_state.data:
        return pd.DataFrame()
    df = pd.DataFrame(st.session_state.data)
    df["banding"] = df.apply(lambda r: get_banding(r["jurisdiction"], r["area"]), axis=1)
    df["banding_order"] = df["banding"].map(BANDING_ORDER).fillna(99)
    df["banding_colour"] = df["banding"].map(BANDING_COLOURS).fillna("#cccccc")
    df["fixable_label"] = df["fixable"].map({True: "✅ Action needed", False: "⏳ Self-resolving"})
    return df.sort_values(["banding_order", "area", "jurisdiction"])


def do_scrape():
    st.session_state.is_scraping = True
    try:
        rows = run_scrape()
        st.session_state.data = rows
        st.session_state.last_refresh = datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S UTC")
    except Exception as e:
        st.error(f"Scrape failed: {e}")
    finally:
        st.session_state.is_scraping = False


# ── Sidebar ────────────────────────────────────────────────────────────────────
with st.sidebar:
    st.title("📡 Compliance Monitor")
    st.markdown("---")

    if st.button("🔃 Refresh Now", use_container_width=True, type="primary"):
        with st.spinner("Scraping Distill — this takes 2-3 minutes, please wait…"):
            do_scrape()

    if st.session_state.last_refresh:
        st.caption(f"Last refresh: {st.session_state.last_refresh}")
    else:
        st.caption("No data loaded yet — click Refresh Now")

    st.markdown("---")
    st.subheader("Filters")

    df_all = load_data()

    areas = ["All"] + sorted(df_all["area"].unique().tolist()) if not df_all.empty else ["All"]
    sel_area = st.selectbox("Compliance Area", areas)

    bandings = ["All", "1. High", "2. Medium", "3. Low", "4. Lowest"]
    sel_banding = st.selectbox("Min. Banding", bandings)

    jurisdictions = ["All"] + sorted(df_all["jurisdiction"].dropna().unique().tolist()) if not df_all.empty else ["All"]
    sel_juris = st.selectbox("Jurisdiction", jurisdictions)

    error_types = ["All"] + sorted(df_all["error_type"].unique().tolist()) if not df_all.empty else ["All"]
    sel_etype = st.selectbox("Error Type", error_types)

    fixable_opts = ["All", "✅ Action needed", "⏳ Self-resolving"]
    sel_fixable = st.selectbox("Fixability", fixable_opts)


# ── Main page ──────────────────────────────────────────────────────────────────
st.title("📡 Compliance Monitor Dashboard")
st.caption("Live error feed — Financial Services · Gambling Compliance · Payments Compliance")

if st.session_state.is_scraping:
    st.warning("⏳ Scraping in progress — please wait…")
    st.stop()

df = load_data()

if df.empty:
    st.info("No data loaded yet. Click **Refresh Now** in the sidebar to fetch live errors.")
    st.stop()

# ── Apply filters ──────────────────────────────────────────────────────────────
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

# ── KPIs ───────────────────────────────────────────────────────────────────────
total = len(df)
col1, col2, col3, col4, col5 = st.columns(5)
col1.metric("Total Errors", total)
col2.metric("🔴 High Priority", len(df[df["banding"] == "1. High"]))
col3.metric("🟠 Medium", len(df[df["banding"] == "2. Medium"]))
col4.metric("✅ Action Needed", len(df[df["fixable"] == True]))
col5.metric("⏳ Self-Resolving", len(df[df["fixable"] == False]))

st.markdown("---")

# ── Charts ─────────────────────────────────────────────────────────────────────
chart_col1, chart_col2 = st.columns(2)

with chart_col1:
    st.subheader("Errors by Area & Banding")
    area_band = df.groupby(["area", "banding"]).size().reset_index(name="count")
    area_band["banding_order"] = area_band["banding"].map(BANDING_ORDER)
    area_band = area_band.sort_values("banding_order")
    fig1 = px.bar(area_band, x="area", y="count", color="banding",
        color_discrete_map=BANDING_COLOURS,
        category_orders={"banding": ["1. High", "2. Medium", "3. Low", "4. Lowest"]},
        barmode="stack", labels={"area": "Area", "count": "Errors", "banding": "Banding"})
    fig1.update_layout(height=350, margin=dict(t=20, b=20))
    st.plotly_chart(fig1, use_container_width=True)

with chart_col2:
    st.subheader("Top 20 Jurisdictions")
    top_j = df.groupby(["jurisdiction", "banding"]).size().reset_index(name="count").sort_values("count", ascending=False).head(20)
    fig2 = px.bar(top_j, x="count", y="jurisdiction", color="banding",
        color_discrete_map=BANDING_COLOURS, orientation="h",
        labels={"jurisdiction": "", "count": "Errors", "banding": "Banding"})
    fig2.update_layout(height=400, margin=dict(t=20, b=20), yaxis={"categoryorder": "total ascending"})
    st.plotly_chart(fig2, use_container_width=True)

# ── Error type pie ─────────────────────────────────────────────────────────────
st.subheader("Error Type Breakdown")
etype_counts = df["error_type"].value_counts().reset_index()
etype_counts.columns = ["Error Type", "Count"]
et_col1, et_col2 = st.columns([1, 2])
with et_col1:
    fig3 = px.pie(etype_counts, names="Error Type", values="Count", hole=0.4)
    fig3.update_layout(height=300, margin=dict(t=20, b=20))
    st.plotly_chart(fig3, use_container_width=True)
with et_col2:
    st.dataframe(etype_counts, use_container_width=True, hide_index=True)

st.markdown("---")

# ── Detail table ───────────────────────────────────────────────────────────────
st.subheader(f"📋 Error Details ({total} errors)")

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

csv = df_display.to_csv(index=False)
st.download_button(
    label="⬇️ Download as CSV",
    data=csv,
    file_name=f"compliance_errors_{datetime.utcnow().strftime('%Y%m%d_%H%M')}.csv",
    mime="text/csv",
)
