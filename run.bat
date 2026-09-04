@echo off
cd /d "%~dp0"
where py >nul 2>nul
if %errorlevel%==0 (
  py -3 launcher.py
) else (
  python launcher.py
)
if errorlevel 1 (
  echo.
  echo Could not start the app. Install Python 3 from https://www.python.org/downloads/
  pause
)
