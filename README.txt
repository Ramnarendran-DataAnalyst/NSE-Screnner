NSE DAILY 2-TOUCH DESCENDING TRENDLINE BREAKOUT SCANNER
=======================================================

WHAT IT DOES
- Downloads daily NSE CM UDiFF Common Bhavcopy Final ZIP files from NSE archives.
- Builds up to 6 months of daily OHLCV history and caches each ZIP in data/bhavcopy.
- Scans NSE cash-market EQ series (non-EQ and SME series are excluded).
- Finds confirmed swing highs and tests descending lines connecting pairs of highs.
- Requires exactly two qualifying swing-high touches within 0.15 x ATR(14) of the line.
- Signals only when the previous completed daily close was at/below the line and the latest completed daily close is above it.
- Requires latest volume above 20-day average when run with --require-volume.
- Exports an Excel report to output/.

INSTALL
1. Install Python 3.10 or newer from https://www.python.org/downloads/ .
2. During installation, enable “Add Python to PATH” if offered.
3. Extract this folder to a normal location such as Desktop.
4. Double-click INSTALL_AND_RUN.bat.

RUN AGAIN LATER
Double-click INSTALL_AND_RUN.bat again. Previously downloaded bhavcopy ZIPs are cached, so only new missing dates need downloading.

DEFAULT RULES
- History: 6 calendar months downloaded; last 100 trading bars considered.
- Swing high: highest high in a 3-bars-left / 3-bars-right window, unique maximum.
- Two anchor swing highs: at least 5 and at most 60 trading bars apart; second high lower than first.
- Exactly two confirmed swing highs may lie within 0.15 x ATR(14) of the projected line, including both anchor highs.
- Fresh breakout: prior day's close <= prior projected line AND latest completed day's close > latest projected line.
- Volume: latest volume > 20-day average volume (enabled by the .bat file).

IMPORTANT LIMITATIONS
- The scan is end-of-day, not intraday. Run after NSE's final bhavcopy is published.
- NSE may rate-limit or temporarily block automated downloads. If so, try later. The script does not silently substitute third-party prices.
- NSE bhavcopy prices are not adjusted for every historical corporate action. Splits/bonuses can distort older trendlines. Review chart context before trading.
- “Exactly two touches” is operationally defined as exactly two confirmed swing highs within the ATR tolerance. No automated definition can guarantee every trader's visual interpretation.
- The output's stop-loss reference is a technical reference only, not a personalized recommendation. Check liquidity, gap risk, and risk per trade.
- No trading performance or profitability is guaranteed.

TUNING
To run without the volume filter:
  py nse_2touch_scanner.py

To use tighter touch tolerance:
  py nse_2touch_scanner.py --require-volume --tolerance-atr 0.10

To use a wider swing confirmation:
  py nse_2touch_scanner.py --require-volume --left 4 --right 4

OFFICIAL SOURCE
https://www.nseindia.com/all-reports
Look for “CM-UDiFF Common Bhavcopy Final (zip)”.
