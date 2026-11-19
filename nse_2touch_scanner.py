#!/usr/bin/env python3
"""NSE Daily 2-Touch Descending Trendline Breakout Scanner.

Downloads NSE CM UDiFF daily final bhavcopies, caches them locally, builds OHLCV
history, and scans EQ-series cash stocks. Signals use completed daily candles only.
"""
from __future__ import annotations
import argparse, io, logging, re, time, zipfile
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
NIFTY200_URL = "https://nsearchives.nseindia.com/content/indices/ind_nifty200list.csv"
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/120 Safari/537.36",
    "Accept": "*/*", "Accept-Language": "en-US,en;q=0.9", "Referer": "https://www.nseindia.com/"
}
logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)s | %(message)s", datefmt="%H:%M:%S")

BHAVCOPY_ALIASES = {
    "DATE": ("TRADEDATE", "TRADDT", "BIZDT", "TIMESTAMP", "DATE"),
    "SYMBOL": ("TCKRSYMB", "SYMBOL"),
    "SERIES": ("SCTYSRS", "SERIES"),
    "OPEN": ("OPNPRIC", "OPNPRICE", "OPENPRICE", "OPENINGPRICE", "OPEN"),
    "HIGH": ("HGHPRIC", "HIGHPRICE", "HIGHESTPRICE", "HIGH"),
    "LOW": ("LWPRIC", "LOWPRICE", "LOWESTPRICE", "LOW"),
    "CLOSE": ("CLSPRIC", "CLSPRICE", "CLOSEPRICE", "CLOSINGPRICE", "CLOSE"),
    "VOLUME": ("TTLTRADGVOL", "TTLTRDQTY", "TOTTRDQTY", "TOTALTRADEDQTY", "TOTALTRADEDQUANTITY", "TOTALTRADEDVOLUME", "TRADEDVOLUME", "VOLUME"),
}


def get_session():
    s = requests.Session(); s.headers.update(HEADERS)
    try: s.get("https://www.nseindia.com", timeout=15)
    except requests.RequestException: pass
    return s


def get_nifty200_symbols() -> set[str]:
    """Fetch the current Nifty 200 constituent symbols from NSE's official CSV."""
    response = requests.get(NIFTY200_URL, headers=HEADERS, timeout=25)
    response.raise_for_status()
    constituents = pd.read_csv(io.BytesIO(response.content))
    symbol_col = next((c for c in constituents.columns if re.sub(r"[^A-Z0-9]", "", str(c).upper()) in {"SYMBOL", "TCKRSYMB"}), None)
    if symbol_col is None:
        raise ValueError(f"NSE constituent file has no Symbol column. Headers found: {list(constituents.columns)}")
    symbols = set(constituents[symbol_col].astype(str).str.strip().str.upper()) - {"", "NAN"}
    if not 180 <= len(symbols) <= 220:
        raise ValueError(f"Expected about 200 Nifty 200 constituents, found {len(symbols)}")
    return symbols


def read_symbol_list(content: bytes) -> set[str]:
    """Read an NSE index constituent CSV supplied by the user."""
    table = pd.read_csv(io.BytesIO(content))
    symbol_col = next((c for c in table.columns if re.sub(r"[^A-Z0-9]", "", str(c).upper()) in {"SYMBOL", "TCKRSYMB"}), None)
    if symbol_col is None:
        raise ValueError(f"Constituent CSV needs a Symbol column. Headers found: {list(table.columns)}")
    symbols = set(table[symbol_col].astype(str).str.strip().str.upper()) - {"", "NAN"}
    if not 180 <= len(symbols) <= 220:
        raise ValueError(f"This list contains {len(symbols)} symbols; expected the official Nifty 200 list (about 200)")
    return symbols


def read_bhavcopy(content: bytes, filename: str = "upload.csv") -> pd.DataFrame:
    """Read one NSE bhavcopy CSV/ZIP or an Excel file into unique canonical columns."""
    stream = io.BytesIO(content)
    if filename.lower().endswith((".xlsx", ".xls")):
        df = pd.read_excel(stream)
    elif zipfile.is_zipfile(stream):
        stream.seek(0)
        with zipfile.ZipFile(stream) as archive:
            names = [n for n in archive.namelist() if n.lower().endswith(".csv")]
            if not names:
                raise ValueError("ZIP contains no CSV file")
            candidates = []
            known = {alias for choices in BHAVCOPY_ALIASES.values() for alias in choices}
            for name in names:
                table = pd.read_csv(io.BytesIO(archive.read(name)))
                normalized = {re.sub(r"[^A-Z0-9]", "", str(c).strip().upper()) for c in table.columns}
                candidates.append((len(normalized & known), table))
            df = max(candidates, key=lambda item: item[0])[1]
    else:
        df = pd.read_csv(stream)

    # Normalize labels first, then pick one source column per output field. This
    # avoids duplicate-key errors when a file contains multiple date aliases.
    columns = [(str(c), re.sub(r"[^A-Z0-9]", "", str(c).strip().upper())) for c in df.columns]
    selected = {}
    for target, choices in BHAVCOPY_ALIASES.items():
        source = next((original for choice in choices for original, normalized in columns if normalized == choice), None)
        if source is not None:
            selected[target] = df[source].reset_index(drop=True)
    missing = [c for c in ("SYMBOL", "SERIES", "OPEN", "HIGH", "LOW", "CLOSE", "VOLUME") if c not in selected]
    if missing:
        found = [str(c) for c in df.columns]
        raise ValueError(f"Missing columns {missing}. Headers found: {found}. Upload NSE CM-UDiFF Common Bhavcopy Final, or a file with symbol, series, date, open, high, low, close and volume columns.")

    if "DATE" in selected:
        dates = pd.to_datetime(selected["DATE"], errors="coerce", dayfirst=True)
    else:
        dates = pd.Series(pd.NaT, index=range(len(df)))
    match = re.search(r"(20\d{6})", filename)
    if match:
        dates = dates.fillna(pd.to_datetime(match.group(1), format="%Y%m%d"))
    out = pd.DataFrame({"DATE": dates, **{key: selected[key] for key in ("SYMBOL", "SERIES", "OPEN", "HIGH", "LOW", "CLOSE", "VOLUME")}})
    for c in ("OPEN", "HIGH", "LOW", "CLOSE", "VOLUME"):
        out[c] = pd.to_numeric(out[c], errors="coerce")
    out["SYMBOL"] = out["SYMBOL"].astype(str).str.strip().str.upper()
    out["SERIES"] = out["SERIES"].astype(str).str.strip().str.upper()
    out = out[(out["SERIES"] == "EQ") & out["SYMBOL"].ne("")]
    return out[["DATE", "SYMBOL", "OPEN", "HIGH", "LOW", "CLOSE", "VOLUME"]].dropna(subset=["DATE", "OPEN", "HIGH", "LOW", "CLOSE"])


def read_uploaded_history(content: bytes, filename: str) -> pd.DataFrame:
    """Read a bhavcopy or an archive containing many daily CSV/ZIP files."""
    if not filename.lower().endswith(".zip"):
        return read_bhavcopy(content, filename)

    def unpack(payload: bytes, member_name: str, depth: int = 0) -> list[pd.DataFrame]:
        if depth > 4:
            raise ValueError("ZIP nesting is deeper than supported (maximum 4 levels)")
        with zipfile.ZipFile(io.BytesIO(payload)) as archive:
            frames = []
            for info in archive.infolist():
                if info.is_dir():
                    continue
                name = info.filename
                lower = name.lower()
                if lower.endswith(".csv"):
                    frames.append(read_bhavcopy(archive.read(info), name))
                elif lower.endswith(".zip"):
                    frames.extend(unpack(archive.read(info), name, depth + 1))
            return frames

    frames = unpack(content, filename)
    if not frames:
        # Also accept a single NSE bhavcopy ZIP whose inner CSV has an unusual suffix.
        return read_bhavcopy(content, filename)
    return pd.concat(frames, ignore_index=True)


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
