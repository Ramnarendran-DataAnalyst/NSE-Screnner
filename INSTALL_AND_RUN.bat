@echo off
cd /d "%~dp0"
echo Installing required Python packages...
py -m pip install -r requirements.txt
if errorlevel 1 goto error
echo.
echo Starting NSE 2-Touch Trendline Breakout Scanner...
py nse_2touch_scanner.py --require-volume
if errorlevel 1 goto error
echo.
echo Done. Check the output folder for your Excel report.
pause
exit /b 0
:error
echo.
echo Something went wrong. Confirm Python 3.10+ is installed and internet access is available.
pause
exit /b 1
