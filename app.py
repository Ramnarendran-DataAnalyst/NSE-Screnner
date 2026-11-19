from __future__ import annotations
import io
import os
import tempfile
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace

import pandas as pd
import streamlit as st

from nse_2touch_scanner import (backtest_symbol, download_history, evaluate_recent_breakout,
    get_nifty200_symbols, read_symbol_list, read_uploaded_history, save_excel, summarize_backtest)

st.set_page_config(page_title="NSE 2-Touch Trendline Scanner", page_icon="📈", layout="wide")
st.title("📈 Nifty 200 2-Touch Descending Trendline Breakout Scanner")
st.caption("Nifty 200 constituents only · Completed daily candles · Recent close-confirmed breakouts · Exactly two qualifying swing-high touches")

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
    reward_risk = st.number_input("Target risk/reward", min_value=0.5, max_value=5.0, value=2.0, step=0.5)
    max_holding_bars = st.number_input("Backtest max holding sessions", min_value=1, max_value=120, value=20, step=1)
    run_backtest = st.checkbox("Backtest earlier signals in supplied history", value=True)
    recent_window = st.number_input("Include breakouts up to N completed sessions old", min_value=0, max_value=5, value=2, step=1)
    min_price = st.number_input("Minimum stock price (₹)", min_value=0.0, value=20.0, step=5.0)
    symbols_text = st.text_area("Optional symbols (comma-separated; leave blank for all EQ stocks)", placeholder="RELIANCE, TCS, INFY")
    data_source = st.radio("Market data", ["Upload NSE bhavcopy files", "Download from NSE"], index=0)
    uploaded_files = st.file_uploader(
        "Upload daily bhavcopy files or one ZIP containing many dates",
        type=["csv", "zip", "xlsx"], accept_multiple_files=True,
        help="A ZIP may contain many daily CSVs or daily bhavcopy ZIP files. You can also select files for multiple dates.",
    ) if data_source == "Upload NSE bhavcopy files" else []
    constituents_file = st.file_uploader(
        "Nifty 200 constituents CSV (only needed if NSE list download fails)",
        type=["csv"], accept_multiple_files=False,
        help="Download the official Nifty 200 stock list from NSE's index page.",
    )
    run_scan = st.button("🚀 Run NSE Scan", type="primary", use_container_width=True)

st.info("The scanner defines a touch as a confirmed swing high within the selected ATR tolerance of the line. 'Exactly two' means exactly two qualifying confirmed swing highs on that candidate line. This is a reproducible algorithmic definition, not a guarantee that every charting method draws the same line.")

@st.cache_data(show_spinner=False, ttl=6 * 60 * 60)
def load_nse_data(month_count: int):
    # Streamlit Cloud has ephemeral local storage; this cache avoids repeat downloads during its TTL.
    return download_history(month_count, pause=0.25)

@st.cache_data(show_spinner=False, ttl=6 * 60 * 60)
def load_nifty200():
    return get_nifty200_symbols()

if run_scan:
    args = SimpleNamespace(
        lookback=int(lookback), left=int(left), right=int(right), min_gap=int(min_gap),
        max_gap=int(max_gap), tolerance_atr=float(tolerance), require_volume=bool(require_volume),
        reward_risk=float(reward_risk),
    )
    if max_gap <= min_gap:
        st.error("Maximum gap must be greater than minimum gap.")
        st.stop()
    try:
        try:
            nifty200_symbols = read_symbol_list(constituents_file.getvalue()) if constituents_file else load_nifty200()
        except Exception as exc:
            st.error(f"Could not load the official Nifty 200 list: {exc}")
            st.info("Download **List of Nifty 200 Stocks (.csv)** from the official NSE Nifty 200 page and upload it in the sidebar.")
            st.stop()
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
        before_filter = data["SYMBOL"].nunique()
        data = data[data["SYMBOL"].isin(nifty200_symbols)].copy()
        if data.empty:
            st.error("None of the uploaded/downloaded symbols matched the current Nifty 200 list. Check that you uploaded NSE CM EQ-series bhavcopies and the official constituent CSV.")
            st.stop()
        st.caption(f"Universe filter: Nifty 200 only · {data['SYMBOL'].nunique()} constituents found in the supplied history (of {len(nifty200_symbols)} current constituents).")
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
                result = evaluate_recent_breakout(group, args, int(recent_window))
                if result and result["Close"] >= float(min_price):
                    matches.append(result)
            except Exception:
                pass
            if idx % 10 == 0 or idx == len(groups):
                progress.progress(idx / max(len(groups), 1), text=f"Scanned {idx:,} / {len(groups):,} symbols")
        backtest_trades = pd.DataFrame()
        backtest_summary = pd.DataFrame()
        if run_backtest:
            bt_progress = st.progress(0, text="Backtesting earlier signals…")
            all_trades = []
            for idx, (symbol, group) in enumerate(groups, start=1):
                try:
                    all_trades.extend(backtest_symbol(group, args, float(reward_risk), int(max_holding_bars), float(min_price)))
                except Exception as exc:
                    st.warning(f"Backtest skipped {symbol}: {exc}")
                if idx % 10 == 0 or idx == len(groups):
                    bt_progress.progress(idx / max(len(groups), 1), text=f"Backtested {idx:,} / {len(groups):,} symbols")
            backtest_trades = pd.DataFrame(all_trades)
            backtest_summary = summarize_backtest(backtest_trades, float(reward_risk), int(max_holding_bars))
        results = pd.DataFrame(matches)
        if not results.empty:
            results = results.sort_values(["Breakout %", "Volume Confirmed"], ascending=[False, False]).reset_index(drop=True)
        st.session_state["scan_results"] = results
        st.session_state["scan_data_date"] = pd.to_datetime(data["DATE"]).max().date()
        st.session_state["scan_count"] = data["SYMBOL"].nunique()
        st.session_state["scan_rows"] = len(data)
        st.session_state["scan_args"] = args
        st.session_state["backtest_trades"] = backtest_trades
        st.session_state["backtest_summary"] = backtest_summary
    except Exception as exc:
        st.error(f"Scan failed: {exc}")
        st.caption("Try uploading NSE daily bhavcopy files to bypass automated archive downloads.")

if "scan_results" in st.session_state:
    results = st.session_state["scan_results"]
    c1, c2, c3 = st.columns(3)
    c1.metric("Stocks scanned", f"{st.session_state['scan_count']:,}")
    c2.metric("Fresh breakout matches", f"{len(results):,}")
    c3.metric("Latest data date", str(st.session_state["scan_data_date"]))
    if (pd.Timestamp.now(tz="Asia/Kolkata").date() - st.session_state["scan_data_date"]).days > 4:
        st.warning(f"The supplied data is stale: latest session is {st.session_state['scan_data_date']}. Upload a newer bhavcopy history for current signals.")
    if results.empty:
        st.success("No stocks met all selected conditions for the latest available completed session. Filters were not relaxed automatically.")
    else:
        st.subheader("Fresh breakout candidates")
        st.dataframe(results.drop(columns=[c for c in results.columns if c.endswith("Index")], errors="ignore"), use_container_width=True, hide_index=True)
        csv = results.to_csv(index=False).encode("utf-8-sig")
        st.download_button("⬇️ Download CSV", csv, file_name="NSE_2Touch_Breakouts.csv", mime="text/csv")
        st.caption("Signal is confirmed at the daily close. Stop Loss uses the lower of the signal-day low and projected trendline minus ATR(14); target defaults to 2R. These are research levels, not order instructions.")

if "backtest_summary" in st.session_state and not st.session_state["backtest_summary"].empty:
    st.subheader("Historical backtest")
    st.caption("Signal at daily close; entry at the next session open. Target defaults to 2R; stop is the structural signal-day stop; trades exit at stop, target, or after the holding limit. If one daily candle touches both target and stop, the backtest assumes the stop came first. Signals without a complete holding window in the supplied history are excluded.")
    st.dataframe(st.session_state["backtest_summary"], use_container_width=True, hide_index=True)
    historical_trades = st.session_state["backtest_trades"]
    if not historical_trades.empty:
        st.dataframe(historical_trades, use_container_width=True, hide_index=True)
        st.download_button("⬇️ Download backtest trades CSV", historical_trades.to_csv(index=False).encode("utf-8-sig"), file_name="NSE_2Touch_Backtest_Trades.csv", mime="text/csv")

if "scan_results" in st.session_state:
    xlsx_buffer = io.BytesIO()
    with tempfile.NamedTemporaryFile(suffix=".xlsx", delete=False) as tmp:
        temp_path = tmp.name
    try:
        summary = st.session_state.get("backtest_summary", pd.DataFrame())
        trades = st.session_state.get("backtest_trades", pd.DataFrame())
        save_excel(st.session_state["scan_results"], pd.DataFrame(), Path(temp_path),
                   trades, summary if not summary.empty else None)
        with open(temp_path, "rb") as report:
            xlsx_buffer.write(report.read())
        st.download_button("⬇️ Download Excel report (signals + backtest)", xlsx_buffer.getvalue(),
            file_name="NSE_2Touch_Screener_Report.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
    finally:
        if os.path.exists(temp_path):
            os.remove(temp_path)

with st.expander("How the scanner works / limitations"):
    st.markdown("""
    1. Reads NSE CM UDiFF daily final bhavcopy files and keeps EQ-series cash stocks.
    2. Detects confirmed swing highs using the selected left/right pivot window.
    3. Tests descending lines joining pairs of swing highs.
    4. Counts qualifying swing highs within the ATR-based touch tolerance; requires exactly two, including both anchors.
    5. Requires the previous completed close to be at/below the projected line and the signal-session close to be above it. By default, signals up to 2 completed sessions old remain visible.
    6. Optionally requires latest volume above its 20-session average.
    7. This is not a real-time or intraday scanner. Uploaded data only covers its included dates; the automatic source downloads completed daily files. The latest data date is shown, and stale data triggers a warning.
    8. Confirms swing highs only after the configured right-side bars close (default 3). This and the daily-close/volume rules can delay a signal relative to an intraday trendline crossing. The candidate table shows bars since Touch 2.
    9. Historical test: next-session open entry, structural stop, default 2R target, and time exit after the chosen maximum holding sessions.

    **Important:** NSE bhavcopy history is not adjusted for every corporate action. Delisted/newly listed stocks and temporary NSE download restrictions can affect coverage. This is a technical screening tool, not investment advice. Always inspect each chart and manage risk independently.
    """)

st.markdown("**Download data:** [NSE All Reports](https://www.nseindia.com/all-reports) → search for **CM-UDiFF Common Bhavcopy Final (zip)**. Download daily files for the dates you need, then upload several dates above. NSE's [Historical Reports](https://www.nseindia.com/static/resources/historical-reports-capital-market-daily-monthly-archives) page also links to daily and monthly archives. The scanner needs a history of daily OHLCV rows; one day's file cannot establish two touches.")

st.divider()
st.caption("Data source: NSE official CM daily bhavcopy archive. The app scans the latest available completed session; it does not predict future breakouts.")
