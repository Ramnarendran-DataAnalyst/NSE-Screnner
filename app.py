from __future__ import annotations
import io
from datetime import datetime
from types import SimpleNamespace

import pandas as pd
import streamlit as st

from nse_2touch_scanner import download_history, evaluate_symbol, read_uploaded_history, save_excel

st.set_page_config(page_title="NSE 2-Touch Trendline Scanner", page_icon="📈", layout="wide")
st.title("📈 NSE 2-Touch Descending Trendline Breakout Scanner")
st.caption("Daily NSE cash-market scanner · Completed candles only · Exactly two qualifying swing-high touches")

with st.sidebar:
    st.header("Scan settings")
    months = st.slider("History to download (months)", 3, 12, 6)
    lookback = st.slider("Pattern lookback (trading bars)", 40, 180, 100, 5)
    left = st.number_input("Swing-high bars to left", 1, 8, 3)
    right = st.number_input("Swing-high confirmation bars to right", 1, 8, 3)
    min_gap = st.number_input("Minimum bars between touches", 3, 30, 5)
    max_gap = st.number_input("Maximum bars between touches", 10, 100, 60)
    tolerance = st.slider("Touch tolerance (ATR multiple)", 0.05, 0.50, 0.15, 0.01)
    require_volume = st.checkbox("Require breakout volume above 20-day average", value=True)
    min_price = st.number_input("Minimum stock price (₹)", min_value=0.0, value=20.0, step=5.0)
    symbols_text = st.text_area("Optional symbols (comma-separated; leave blank for all EQ stocks)", placeholder="RELIANCE, TCS, INFY")
    data_source = st.radio("Market data", ["Upload NSE bhavcopy files", "Download from NSE"], index=0)
    uploaded_files = st.file_uploader(
        "Upload daily bhavcopy files or one ZIP containing many dates",
        type=["csv", "zip", "xlsx"], accept_multiple_files=True,
        help="A ZIP may contain many daily CSVs or daily bhavcopy ZIP files. You can also select files for multiple dates.",
    ) if data_source == "Upload NSE bhavcopy files" else []
    run_scan = st.button("🚀 Run NSE Scan", type="primary", use_container_width=True)

st.info("The scanner defines a touch as a confirmed swing high within the selected ATR tolerance of the line. 'Exactly two' means exactly two qualifying confirmed swing highs on that candidate line. This is a reproducible algorithmic definition, not a guarantee that every charting method draws the same line.")

@st.cache_data(show_spinner=False, ttl=6 * 60 * 60)
def load_nse_data(month_count: int):
    # Streamlit Cloud has ephemeral local storage; this cache avoids repeat downloads during its TTL.
    return download_history(month_count, pause=0.25)

if run_scan:
    args = SimpleNamespace(
        lookback=int(lookback), left=int(left), right=int(right), min_gap=int(min_gap),
        max_gap=int(max_gap), tolerance_atr=float(tolerance), require_volume=bool(require_volume)
    )
    if max_gap <= min_gap:
        st.error("Maximum gap must be greater than minimum gap.")
        st.stop()
    try:
        if data_source == "Upload NSE bhavcopy files":
            if not uploaded_files:
                st.error("Upload several daily bhavcopy files first. Use the NSE All Reports page linked below.")
                st.stop()
            with st.spinner(f"Reading {len(uploaded_files)} uploaded file(s) and combining their dates…"):
                frames = [read_uploaded_history(f.getvalue(), f.name) for f in uploaded_files]
                data = pd.concat(frames, ignore_index=True).drop_duplicates(["DATE", "SYMBOL"], keep="last")
                data = data.sort_values(["SYMBOL", "DATE"])
            if data.empty:
                st.error("The uploaded files contain no usable EQ-series rows. Check the columns and date range.")
                st.stop()
        else:
            with st.spinner("Downloading official NSE daily bhavcopy history. First run may take several minutes…"):
                data = load_nse_data(int(months))
        if data.empty:
            st.warning("No NSE data was returned. Try again later or upload/check the data source.")
            st.stop()
        requested = [x.strip().upper() for x in symbols_text.split(",") if x.strip()]
        if requested:
            missing = sorted(set(requested) - set(data["SYMBOL"].unique()))
            data = data[data["SYMBOL"].isin(requested)]
            if missing:
                st.warning("Not found in downloaded EQ-series data: " + ", ".join(missing))
        progress = st.progress(0, text="Scanning symbols…")
        matches = []
        groups = list(data.groupby("SYMBOL", sort=False))
        for idx, (symbol, group) in enumerate(groups, start=1):
            try:
                result = evaluate_symbol(group, args)
                if result and result["Close"] >= float(min_price):
                    matches.append(result)
            except Exception:
                pass
            if idx % 10 == 0 or idx == len(groups):
                progress.progress(idx / max(len(groups), 1), text=f"Scanned {idx:,} / {len(groups):,} symbols")
        results = pd.DataFrame(matches)
        if not results.empty:
            results = results.sort_values(["Breakout %", "Volume Confirmed"], ascending=[False, False]).reset_index(drop=True)
        st.session_state["scan_results"] = results
        st.session_state["scan_data_date"] = pd.to_datetime(data["DATE"]).max().date()
        st.session_state["scan_count"] = data["SYMBOL"].nunique()
        st.session_state["scan_rows"] = len(data)
        st.session_state["scan_args"] = args
    except Exception as exc:
        st.error(f"Scan failed: {exc}")
        st.caption("Try uploading NSE daily bhavcopy files to bypass automated archive downloads.")

if "scan_results" in st.session_state:
    results = st.session_state["scan_results"]
    c1, c2, c3 = st.columns(3)
    c1.metric("Stocks scanned", f"{st.session_state['scan_count']:,}")
    c2.metric("Fresh breakout matches", f"{len(results):,}")
    c3.metric("Latest data date", str(st.session_state["scan_data_date"]))
    if results.empty:
        st.success("No stocks met all selected conditions for the latest available completed session. Filters were not relaxed automatically.")
    else:
        st.subheader("Fresh breakout candidates")
        st.dataframe(results.drop(columns=[c for c in results.columns if c.endswith("Index")], errors="ignore"), use_container_width=True, hide_index=True)
        csv = results.to_csv(index=False).encode("utf-8-sig")
        st.download_button("⬇️ Download CSV", csv, file_name="NSE_2Touch_Breakouts.csv", mime="text/csv")
        xlsx_buffer = io.BytesIO()
        temp_path = None
        import tempfile, os
        with tempfile.NamedTemporaryFile(suffix=".xlsx", delete=False) as tmp:
            temp_path = tmp.name
        try:
            save_excel(results, pd.DataFrame(), __import__('pathlib').Path(temp_path))
            with open(temp_path, "rb") as f:
                xlsx_buffer.write(f.read())
            st.download_button("⬇️ Download Excel report", xlsx_buffer.getvalue(), file_name="NSE_2Touch_Breakouts.xlsx", mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
        finally:
            if temp_path and os.path.exists(temp_path):
                os.remove(temp_path)
        st.caption("Breakout % is the closing price's distance above the projected trendline. Technical SL Reference is a reference for further chart review, not an order instruction.")

with st.expander("How the scanner works / limitations"):
    st.markdown("""
    1. Reads NSE CM UDiFF daily final bhavcopy files and keeps EQ-series cash stocks.
    2. Detects confirmed swing highs using the selected left/right pivot window.
    3. Tests descending lines joining pairs of swing highs.
    4. Counts qualifying swing highs within the ATR-based touch tolerance; requires exactly two, including both anchors.
    5. Requires the previous completed close to be at/below the projected line and the latest completed close to be above it.
    6. Optionally requires latest volume above its 20-session average.

    **Important:** NSE bhavcopy history is not adjusted for every corporate action. Delisted/newly listed stocks and temporary NSE download restrictions can affect coverage. This is a technical screening tool, not investment advice. Always inspect each chart and manage risk independently.
    """)

st.markdown("**Download data:** [NSE All Reports](https://www.nseindia.com/all-reports) → search for **CM-UDiFF Common Bhavcopy Final (zip)**. Download daily files for the dates you need, then upload several dates above. NSE's [Historical Reports](https://www.nseindia.com/static/resources/historical-reports-capital-market-daily-monthly-archives) page also links to daily and monthly archives. The scanner needs a history of daily OHLCV rows; one day's file cannot establish two touches.")

st.divider()
st.caption("Data source: NSE official CM daily bhavcopy archive. The app scans the latest available completed session; it does not predict future breakouts.")
