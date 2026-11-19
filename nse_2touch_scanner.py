#!/usr/bin/env python3
"""NSE Daily 2-Touch Descending Trendline Breakout Scanner.

Downloads NSE CM UDiFF daily final bhavcopies, caches them locally, builds OHLCV
history, and scans EQ-series cash stocks. Signals use completed daily candles only.
"""
from __future__ import annotations
import argparse, io, logging, time, zipfile
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Optional

import pandas as pd
import requests
from openpyxl.styles import Font, PatternFill, Alignment
from openpyxl.utils import get_column_letter

BASE = Path(__file__).resolve().parent
CACHE = BASE / "data" / "bhavcopy"
OUT = BASE / "output"
URL = "https://nsearchives.nseindia.com/content/cm/BhavCopy_NSE_CM_0_0_0_{ymd}_F_0000.csv.zip"
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/120 Safari/537.36",
    "Accept": "*/*", "Accept-Language": "en-US,en;q=0.9", "Referer": "https://www.nseindia.com/"
}
logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)s | %(message)s", datefmt="%H:%M:%S")


def get_session():
    s = requests.Session(); s.headers.update(HEADERS)
    try: s.get("https://www.nseindia.com", timeout=15)
    except requests.RequestException: pass
    return s


def read_bhavcopy(content: bytes) -> pd.DataFrame:
    with zipfile.ZipFile(io.BytesIO(content)) as z:
        names = [n for n in z.namelist() if n.lower().endswith('.csv')]
        if not names: raise ValueError("No CSV found inside bhavcopy ZIP")
        df = pd.read_csv(z.open(names[0]))
    df.columns = [str(c).strip().upper() for c in df.columns]
    # Current UDiFF CM common bhavcopy field names.
    aliases = {
        "TRADE_DATE": "TRADE_DATE", "TRADDT": "TRADE_DATE", "TRAD_DT": "TRADE_DATE", "BIZDT": "TRADE_DATE",
        "TCKRSYMB": "SYMBOL", "TCKR_SYMB": "SYMBOL", "SYMBOL": "SYMBOL",
        "SCTYSRS": "SERIES", "SCTY_SRS": "SERIES", "SERIES": "SERIES",
        "OPNPRIC": "OPEN", "OPN_PRIC": "OPEN", "OPEN": "OPEN",
        "HGHPRIC": "HIGH", "HGH_PRIC": "HIGH", "HIGH": "HIGH",
        "LWPRIC": "LOW", "LW_PRIC": "LOW", "LOW": "LOW",
        "CLSPRIC": "CLOSE", "CLS_PRIC": "CLOSE", "CLOSE": "CLOSE",
        "TTLTRDQTY": "VOLUME", "TTL_TRD_QNTY": "VOLUME", "TOTTRDQTY": "VOLUME",
        # Current NSE UDiFF CM files use TtlTradgVol (not TtlTrdQty).
        "TTLTRADGVOL": "VOLUME", "TTL_TRADG_VOL": "VOLUME", "VOLUME": "VOLUME"
    }
    df = df.rename(columns={c: aliases[c] for c in df.columns if c in aliases})
    required = ["SYMBOL", "SERIES", "OPEN", "HIGH", "LOW", "CLOSE", "VOLUME"]
    missing = [c for c in required if c not in df.columns]
    if missing: raise ValueError(f"Bhavcopy schema changed; missing {missing}. Found: {list(df.columns)}")
    if "TRADE_DATE" in df.columns:
        df["DATE"] = pd.to_datetime(df["TRADE_DATE"], errors="coerce", dayfirst=True)
    else:
        # Date is encoded in the official filename, added by downloader.
        df["DATE"] = pd.NaT
    for c in ["OPEN", "HIGH", "LOW", "CLOSE", "VOLUME"]:
        df[c] = pd.to_numeric(df[c], errors="coerce")
    df["SYMBOL"] = df["SYMBOL"].astype(str).str.strip()
    df["SERIES"] = df["SERIES"].astype(str).str.strip().str.upper()
    df = df[(df["SERIES"] == "EQ") & df["SYMBOL"].ne("")]
    return df[["DATE", "SYMBOL", "OPEN", "HIGH", "LOW", "CLOSE", "VOLUME"]].dropna(subset=["OPEN", "HIGH", "LOW", "CLOSE"])


def download_history(months: int, pause: float = 0.25) -> pd.DataFrame:
    CACHE.mkdir(parents=True, exist_ok=True)
    session = get_session()
    start = date.today() - timedelta(days=int(months * 31 + 15))
    end = date.today() - timedelta(days=1)  # never scan an unfinished current session
    frames = []
    day = start
    tried = 0; downloaded = 0
    status_counts = {}
    parse_errors = []
    while day <= end:
        if day.weekday() < 5:
            ymd = day.strftime("%Y%m%d")
            path = CACHE / f"{ymd}.zip"
            content = None
            if path.exists():
                content = path.read_bytes()
            else:
                url = URL.format(ymd=ymd)
                try:
                    r = session.get(url, timeout=25); tried += 1
                    status_counts[r.status_code] = status_counts.get(r.status_code, 0) + 1
                    if r.status_code == 200 and r.content[:2] == b"PK":
                        path.write_bytes(r.content); content = r.content; downloaded += 1
                    elif r.status_code not in (404, 403):
                        logging.warning("NSE returned HTTP %s for %s", r.status_code, ymd)
                except requests.RequestException as e:
                    logging.warning("Download failed for %s: %s", ymd, e)
                time.sleep(pause)
            if content:
                try:
                    d = read_bhavcopy(content)
                    if d["DATE"].isna().all(): d["DATE"] = pd.Timestamp(day)
                    else: d["DATE"] = d["DATE"].fillna(pd.Timestamp(day))
                    frames.append(d)
                except Exception as e:
                    parse_errors.append(f"{ymd}: {e}")
                    logging.warning("Could not parse %s: %s", ymd, e)
        day += timedelta(days=1)
    if not frames:
        details = f"Tried {tried} archive requests; HTTP statuses: {status_counts or 'none (network/cache issue)'}; ZIPs downloaded: {downloaded}."
        if parse_errors:
            details += " First parser errors: " + " | ".join(parse_errors[:3])
        raise RuntimeError("No usable NSE bhavcopy files were loaded. " + details + " Check Streamlit logs. NSE's current UDiFF volume field is TtlTradgVol; this version supports it. If all requests are 403/429, NSE is blocking the cloud server IP.")
    data = pd.concat(frames, ignore_index=True).drop_duplicates(["DATE", "SYMBOL"], keep="last")
    data = data.sort_values(["SYMBOL", "DATE"])
    logging.info("Loaded %s rows across %s sessions (%s newly downloaded)", len(data), data.DATE.nunique(), downloaded)
    return data


def atr14(df: pd.DataFrame) -> pd.Series:
    prev = df["CLOSE"].shift(1)
    tr = pd.concat([df["HIGH"]-df["LOW"], (df["HIGH"]-prev).abs(), (df["LOW"]-prev).abs()], axis=1).max(axis=1)
    return tr.rolling(14, min_periods=14).mean()


def swing_highs(high: pd.Series, left: int, right: int):
    vals = high.to_numpy(); pivots = []
    for i in range(left, len(vals)-right):
        window = vals[i-left:i+right+1]
        # Unique local maximum: avoids ambiguous equal-high clusters.
        if vals[i] == max(window) and (window == vals[i]).sum() == 1:
            pivots.append(i)
    return pivots


def evaluate_symbol(g: pd.DataFrame, args) -> Optional[dict]:
    g = g.sort_values("DATE").reset_index(drop=True)
    if len(g) < max(45, args.left + args.right + 20): return None
    # Use only most recent lookback bars; pivot confirmation requires right bars.
    g = g.tail(args.lookback).reset_index(drop=True)
    g["ATR14"] = atr14(g)
    g["VOL20"] = g["VOLUME"].rolling(20).mean()
    pivots = swing_highs(g["HIGH"], args.left, args.right)
    last = len(g)-1
    if last < args.right + 1 or pd.isna(g.loc[last, "ATR14"]): return None
    # Latest completed candle must cross from at/below the line to above it.
    candidates = []
    # Find pairs among confirmed pivots, with the second touch not too old.
    for a_idx in range(len(pivots)):
        i = pivots[a_idx]
        for j in pivots[a_idx+1:]:
            if j-i < args.min_gap or j-i > args.max_gap: continue
            if j > last-args.right: continue
            h1, h2 = float(g.loc[i,"HIGH"]), float(g.loc[j,"HIGH"])
            if h2 >= h1: continue
            slope = (h2-h1)/(j-i)
            # Count qualifying confirmed swing highs on or near the line, including anchors.
            touches = []
            for k in pivots:
                if k < i or k > last-args.right: continue
                line_k = h1 + slope*(k-i)
                tol = args.tolerance_atr * float(g.loc[k,"ATR14"] if pd.notna(g.loc[k,"ATR14"]) else g.loc[j,"ATR14"])
                if abs(float(g.loc[k,"HIGH"])-line_k) <= tol:
                    touches.append(k)
            if len(touches) != 2 or i not in touches or j not in touches: continue
            line_prev = h1 + slope*((last-1)-i)
            line_now = h1 + slope*(last-i)
            prev_close = float(g.loc[last-1,"CLOSE"]); close = float(g.loc[last,"CLOSE"])
            if not (prev_close <= line_prev and close > line_now): continue
            vol_avg = g.loc[last,"VOL20"]
            vol_ok = pd.notna(vol_avg) and float(g.loc[last,"VOLUME"]) > float(vol_avg)
            if args.require_volume and not vol_ok: continue
            breakout_pct = (close/line_now-1)*100 if line_now else 0
            candidates.append({
                "Symbol": g.loc[last,"SYMBOL"], "Breakout Date": g.loc[last,"DATE"].date(),
                "Close": round(close,2), "Trendline at Close": round(line_now,2),
                "Breakout %": round(breakout_pct,2), "Touch 1 Date": g.loc[i,"DATE"].date(),
                "Touch 1 High": round(h1,2), "Touch 2 Date": g.loc[j,"DATE"].date(),
                "Touch 2 High": round(h2,2), "Touch Count": len(touches),
                "Volume": int(g.loc[last,"VOLUME"]), "20D Avg Volume": int(vol_avg) if pd.notna(vol_avg) else None,
                "Volume Confirmed": "YES" if vol_ok else "NO",
                "ATR14": round(float(g.loc[last,"ATR14"]),2),
                "Technical SL Reference": round(min(float(g.loc[last,"LOW"]), line_now-float(g.loc[last,"ATR14"])),2),
                "Pivot High 1 Index": i, "Pivot High 2 Index": j
            })
    if not candidates: return None
    # Prefer the most recent second touch; if tied, prefer the tightest two-point line fit.
    return sorted(candidates, key=lambda x: (x["Touch 2 Date"], x["Breakout %"]), reverse=True)[0]


def save_excel(results: pd.DataFrame, data: pd.DataFrame, filename: Path):
    filename.parent.mkdir(parents=True, exist_ok=True)
    with pd.ExcelWriter(filename, engine="openpyxl") as writer:
        results.to_excel(writer, sheet_name="Fresh Breakouts", index=False)
        meta = pd.DataFrame({"Item": ["Data source", "Universe", "Signal definition", "Touch definition", "Breakout definition", "Important limitation"],
            "Value": ["NSE CM UDiFF Common Bhavcopy Final (official daily files)", "NSE cash EQ series; SME/non-EQ series excluded",
            "Latest completed daily candle only", "Exactly two confirmed swing highs within configured ATR tolerance, including the two anchor highs",
            "Previous close at/below projected line and latest close above projected line",
            "Geometric rule is explicit but remains a technical pattern definition, not a guarantee; corporate-action gaps can affect unadjusted bhavcopy history."]})
        meta.to_excel(writer, sheet_name="Methodology", index=False)
        for ws in writer.book.worksheets:
            ws.freeze_panes = "A2"; ws.auto_filter.ref = ws.dimensions
            for cell in ws[1]:
                cell.font = Font(bold=True, color="FFFFFF")
                cell.fill = PatternFill("solid", fgColor="17365D")
                cell.alignment = Alignment(wrap_text=True)
            for col in ws.columns:
                letter = get_column_letter(col[0].column)
                max_len = min(42, max(12, max((len(str(c.value)) if c.value is not None else 0) for c in col)+2))
                ws.column_dimensions[letter].width = max_len


def main():
    p = argparse.ArgumentParser(description="Scan NSE stocks for fresh 2-touch descending trendline breakouts")
    p.add_argument("--months", type=int, default=6, help="Historical calendar months to download (default 6)")
    p.add_argument("--lookback", type=int, default=100, help="Bars used for pattern detection (default 100)")
    p.add_argument("--left", type=int, default=3, help="Swing-high bars to the left (default 3)")
    p.add_argument("--right", type=int, default=3, help="Swing-high confirmation bars to the right (default 3)")
    p.add_argument("--min-gap", type=int, default=5, help="Minimum trading bars between trendline touches")
    p.add_argument("--max-gap", type=int, default=60, help="Maximum trading bars between trendline touches")
    p.add_argument("--tolerance-atr", type=float, default=0.15, help="Touch tolerance as ATR multiple (default 0.15)")
    p.add_argument("--require-volume", action="store_true", help="Require latest volume above 20-day average")
    p.add_argument("--pause", type=float, default=0.25, help="Seconds between NSE archive requests")
    args = p.parse_args()
    if args.months < 3 or args.lookback < 30 or args.left < 1 or args.right < 1:
        p.error("Use months >=3, lookback >=30, and left/right >=1")
    print("\nNSE 2-Touch Descending Trendline Breakout Scanner")
    print("Downloading official NSE daily bhavcopy files. First run may take several minutes.\n")
    data = download_history(args.months, args.pause)
    found = []
    for symbol, group in data.groupby("SYMBOL", sort=False):
        try:
            result = evaluate_symbol(group, args)
            if result: found.append(result)
        except Exception as e:
            logging.debug("Skipped %s: %s", symbol, e)
    results = pd.DataFrame(found)
    if not results.empty:
        results = results.sort_values(["Breakout %", "Volume Confirmed"], ascending=[False, False])
    stamp = datetime.now().strftime("%Y%m%d_%H%M")
    path = OUT / f"NSE_2Touch_Breakouts_{stamp}.xlsx"
    save_excel(results, data, path)
    print(f"\nCompleted. Stocks scanned: {data['SYMBOL'].nunique()}")
    print(f"Fresh breakout matches: {len(results)}")
    print(f"Excel report: {path}")
    if results.empty: print("No stocks met every rule today. This is a valid result; filters were not relaxed automatically.")
    else: print(results[["Symbol","Close","Trendline at Close","Breakout %","Touch 1 Date","Touch 2 Date","Volume Confirmed"]].to_string(index=False))

if __name__ == "__main__": main()
