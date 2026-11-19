# NSE 2-Touch Trendline Breakout Scanner (Streamlit)

A Streamlit app that scans NSE cash-market EQ stocks for **fresh daily bullish breakouts above a descending trendline formed by exactly two qualifying confirmed swing-high touches**.

## Deploy free on Streamlit Community Cloud

1. Create a **private or public GitHub repository** (Streamlit Community Cloud access to private repositories depends on your GitHub authorization/settings).
2. Upload these files to the repository root:
   - `app.py`
   - `nse_2touch_scanner.py`
   - `requirements.txt`
3. Push/commit the files to GitHub.
4. Sign in at https://share.streamlit.io/ using GitHub.
5. Choose **Create app**, select your repository and branch, and set the main file path to `app.py`.
6. Deploy. Streamlit installs packages from `requirements.txt` automatically.

## Run locally

```bash
python -m venv .venv
# Windows: .venv\\Scripts\\activate
# macOS/Linux: source .venv/bin/activate
pip install -r requirements.txt
streamlit run app.py
```

## Scanner rules

- Universe: NSE cash-market EQ series (SME/non-EQ series excluded).
- Timeframe: daily; latest available completed session only.
- Swing high: unique local maximum over `left + right + 1` bars; right bars are required for confirmation.
- Trendline: straight line joining two confirmed swing highs, with second high below first.
- Touch: another confirmed swing high lies within `tolerance × ATR(14)` of the projected line.
- Exactly two qualifying touches are required, including both anchor highs.
- Fresh breakout: previous close at/below the previous day's projected line and latest close above today's projected line.
- Optional volume filter: latest volume above its 20-session average.

## Notes and limitations

- The first full-universe run may take several minutes because the app downloads historical daily NSE bhavcopy archives.
- NSE may rate-limit or block automated requests temporarily. A failed download is not evidence that there are no signals.
- Streamlit Cloud has ephemeral local storage. The app caches data in memory for six hours, but cache can be cleared on restart/redeploy.
- NSE bhavcopy prices are not fully adjusted for every corporate action. Review charts manually, especially around splits, bonuses and other corporate actions.
- "Exactly two touches" is explicitly defined by pivot and ATR tolerance settings; it is not a universal visual definition of a trendline.
- The stop-loss reference in the output is informational, not a trading instruction.

## Files

- `app.py` — Streamlit user interface
- `nse_2touch_scanner.py` — NSE downloader and scanning logic
- `requirements.txt` — Python dependencies
