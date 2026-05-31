import streamlit as st
import requests
import time
from datetime import datetime

# ─── Config ───────────────────────────────────────────────────
API_URL = "http://localhost:8000"
DEFAULT_STORE = "STORE_BLR_002"
REFRESH_INTERVAL = 5  # seconds

st.set_page_config(
    page_title="Apex Store Intelligence",
    page_icon="🏪",
    layout="wide",
)

# ─── Header ───────────────────────────────────────────────────
st.title("🏪 Apex Store Intelligence Dashboard")
st.caption(f"Live analytics • Auto-refresh every {REFRESH_INTERVAL}s")

# ─── Sidebar ──────────────────────────────────────────────────
st.sidebar.header("Settings")
store_id = st.sidebar.text_input("Store ID", value=DEFAULT_STORE)
auto_refresh = st.sidebar.checkbox("Auto Refresh", value=True)

# ─── Fetch Data ───────────────────────────────────────────────
def fetch(endpoint: str) -> dict | None:
    try:
        resp = requests.get(f"{API_URL}{endpoint}", timeout=5)
        if resp.status_code == 200:
            return resp.json()
    except Exception as e:
        st.error(f"API Error: {e}")
    return None


# ─── Main Dashboard ───────────────────────────────────────────
placeholder = st.empty()

while True:
    with placeholder.container():

        # ── Metrics ───────────────────────────────────────────
        metrics = fetch(f"/stores/{store_id}/metrics")
        funnel  = fetch(f"/stores/{store_id}/funnel")
        anomalies = fetch(f"/stores/{store_id}/anomalies")
        health  = fetch("/health")

        st.subheader("📊 Live Metrics")
        if metrics:
            col1, col2, col3, col4 = st.columns(4)
            col1.metric("👥 Unique Visitors",  metrics["unique_visitors"])
            col2.metric("💰 Conversion Rate",  f"{round(metrics['conversion_rate'] * 100, 1)}%")
            col3.metric("🛒 Queue Depth",      metrics["queue_depth"])
            col4.metric("🚪 Abandonment Rate", f"{round(metrics['abandonment_rate'] * 100, 1)}%")
        else:
            st.warning("No metrics data available")

        st.divider()

        # ── Funnel ────────────────────────────────────────────
        st.subheader("🔻 Conversion Funnel")
        if funnel and funnel.get("stages"):
            cols = st.columns(len(funnel["stages"]))
            for i, stage in enumerate(funnel["stages"]):
                with cols[i]:
                    st.metric(
                        label=stage["stage"],
                        value=stage["count"],
                        delta=f"-{stage['dropoff_pct']}%" if stage["dropoff_pct"] > 0 else None,
                        delta_color="inverse",
                    )
        else:
            st.warning("No funnel data available")

        st.divider()

        # ── Zone Dwell ────────────────────────────────────────
        st.subheader("🗺️ Zone Dwell Times")
        if metrics and metrics.get("avg_dwell_per_zone"):
            zones = metrics["avg_dwell_per_zone"]
            zone_names  = [z["zone_id"] for z in zones]
            zone_dwells = [round(z["avg_dwell_ms"] / 1000, 1) for z in zones]

            st.bar_chart(
                data=dict(zip(zone_names, zone_dwells)),
                use_container_width=True,
            )
        else:
            st.warning("No zone data available")

        st.divider()

        # ── Anomalies ─────────────────────────────────────────
        st.subheader("⚠️ Active Anomalies")
        if anomalies and anomalies.get("anomalies"):
            for a in anomalies["anomalies"]:
                if a["severity"] == "CRITICAL":
                    st.error(f"🔴 **{a['anomaly_type']}** — {a['description']}\n\n💡 {a['suggested_action']}")
                elif a["severity"] == "WARN":
                    st.warning(f"🟡 **{a['anomaly_type']}** — {a['description']}\n\n💡 {a['suggested_action']}")
                else:
                    st.info(f"🔵 **{a['anomaly_type']}** — {a['description']}\n\n💡 {a['suggested_action']}")
        else:
            st.success("✅ No active anomalies")

        st.divider()

        # ── Health ────────────────────────────────────────────
        st.subheader("💓 System Health")
        if health:
            status_color = "🟢" if health["status"] == "OK" else "🔴"
            st.write(f"{status_color} Overall: **{health['status']}**")
            for s in health.get("stores", []):
                icon = "🟢" if s["status"] == "OK" else "🔴"
                st.write(f"{icon} {s['store_id']} — {s['status']}")
        else:
            st.error("API unavailable")

        # ── Last Updated ──────────────────────────────────────
        st.caption(f"Last updated: {datetime.now().strftime('%H:%M:%S')}")

    if not auto_refresh:
        break

    time.sleep(REFRESH_INTERVAL)
    placeholder.empty()