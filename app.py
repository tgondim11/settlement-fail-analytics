"""
Settlement Fail Analytics — Streamlit dashboard.

Visualizes the output of pipeline.py: fail rate, aging, root cause,
counterparty concentration, and estimated cost of settlement fails on
a synthetic (but reproducibly generated) trade dataset.

Run with:  streamlit run app.py
"""

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st

from pipeline import compute_analytics, generate_trades

st.set_page_config(
    page_title="Settlement Fail Analytics",
    page_icon="📉",
    layout="wide",
)


@st.cache_data
def load_data():
    df = generate_trades()
    analytics = compute_analytics(df)
    return df, analytics


df, analytics = load_data()
fails = df[df["status"] == "Failed"]

st.title("📉 Settlement Fail Analytics")
st.caption(
    "Synthetic, reproducibly-generated trade-settlement dataset "
    f"({analytics['total_trades']:,} trades, seeded) — see README for methodology."
)

# --- Filters -----------------------------------------------------------
with st.sidebar:
    st.header("Filters")
    asset_filter = st.multiselect(
        "Asset class", options=sorted(df["asset_class"].unique()), default=None
    )
    cp_filter = st.multiselect(
        "Counterparty", options=sorted(df["counterparty"].unique()), default=None
    )

view = df.copy()
if asset_filter:
    view = view[view["asset_class"].isin(asset_filter)]
if cp_filter:
    view = view[view["counterparty"].isin(cp_filter)]
view_fails = view[view["status"] == "Failed"]

filtered = bool(asset_filter or cp_filter)
if filtered:
    total_trades = len(view)
    total_fails = len(view_fails)
    fail_rate = total_fails / total_trades if total_trades else 0.0
    est_cost = view_fails["estimated_cost"].sum()
else:
    total_trades = analytics["total_trades"]
    total_fails = analytics["total_fails"]
    fail_rate = analytics["overall_fail_rate"]
    est_cost = analytics["total_estimated_cost"]

# --- KPI row -------------------------------------------------------------
c1, c2, c3, c4 = st.columns(4)
c1.metric("Total Trades", f"{total_trades:,}")
c2.metric("Total Fails", f"{total_fails:,}")
c3.metric("Fail Rate", f"{fail_rate:.2%}")
c4.metric("Estimated Cost of Fails", f"${est_cost:,.0f}")

st.divider()

# --- Row: trend + asset class breakdown ----------------------------------
col1, col2 = st.columns([2, 1])

with col1:
    st.subheader("Weekly Fail Rate Trend")
    weekly = view.copy()
    weekly["week"] = weekly["trade_date"].dt.to_period("W").apply(lambda p: p.start_time)
    trend = weekly.groupby("week")["status"].apply(lambda s: (s == "Failed").mean())
    fig = px.line(
        x=trend.index, y=trend.values, markers=True,
        labels={"x": "Week", "y": "Fail Rate"},
    )
    fig.update_yaxes(tickformat=".1%")
    st.plotly_chart(fig, use_container_width=True)

with col2:
    st.subheader("Fail Rate by Asset Class")
    by_ac = view.groupby("asset_class")["status"].apply(lambda s: (s == "Failed").mean()).sort_values()
    fig = px.bar(x=by_ac.values, y=by_ac.index, orientation="h", labels={"x": "Fail Rate", "y": ""})
    fig.update_xaxes(tickformat=".1%")
    st.plotly_chart(fig, use_container_width=True)

# --- Row: aging + root cause -----------------------------------------------
col3, col4 = st.columns(2)

with col3:
    st.subheader("Aging Distribution")
    aging_order = ["1-2 days", "3-5 days", "6-10 days", ">10 days"]
    aging = view_fails["aging_bucket"].value_counts().reindex(aging_order).fillna(0)
    fig = px.bar(x=aging.index, y=aging.values, labels={"x": "Days Late", "y": "Fail Count"})
    st.plotly_chart(fig, use_container_width=True)

with col4:
    st.subheader("Root Cause Breakdown")
    causes = view_fails["fail_reason"].value_counts()
    fig = px.pie(names=causes.index, values=causes.values, hole=0.4)
    fig.update_traces(textinfo="percent+label", showlegend=False)
    st.plotly_chart(fig, use_container_width=True)

# --- Row: top counterparties ------------------------------------------------
st.subheader("Top Counterparties by Fail Count")
top_cp = (
    view_fails.groupby("counterparty")
    .agg(fail_count=("trade_id", "count"), total_notional=("notional", "sum"),
         estimated_cost=("estimated_cost", "sum"))
    .sort_values("fail_count", ascending=False)
    .head(10)
)
fig = go.Figure(go.Bar(x=top_cp["fail_count"], y=top_cp.index, orientation="h"))
fig.update_layout(yaxis=dict(autorange="reversed"), xaxis_title="Fail Count", yaxis_title="")
st.plotly_chart(fig, use_container_width=True)
st.dataframe(
    top_cp.style.format({"total_notional": "${:,.0f}", "estimated_cost": "${:,.0f}"}),
    use_container_width=True,
)

# --- Resolution stats ---------------------------------------------------
st.subheader("Resolution Stats")
resolved = view_fails[view_fails["fail_status"] == "Resolved"]
open_fails = view_fails[view_fails["fail_status"] == "Open"]
s1, s2, s3 = st.columns(3)
s1.metric("Mean Days to Resolve", f"{resolved['days_to_resolve'].mean():.1f}" if len(resolved) else "—")
s2.metric("Median Days to Resolve", f"{resolved['days_to_resolve'].median():.1f}" if len(resolved) else "—")
s3.metric(
    "Still Open (as of report date)",
    f"{len(open_fails) / len(view_fails):.1%}" if len(view_fails) else "—",
)

# --- Raw data ---------------------------------------------------------
with st.expander("View underlying trade data"):
    st.dataframe(view, use_container_width=True)
