@echo off
title Crochet Studio
cd /d "%~dp0"

if not exist ".venv\Scripts\python.exe" (
    echo First time setup - this takes a minute or two...
    python -m venv .venv || goto :nopython
    ".venv\Scripts\python.exe" -m pip install --disable-pip-version-check -q -r requirements.txt || goto :failed
)

rem Open the browser a few seconds after the server starts.
start "" /b cmd /c "timeout /t 3 /nobreak >nul & start http://localhost:8000"

echo.
echo  Crochet Studio is running at http://localhost:8000
echo  Keep this window open while you use it. Close it to stop.
echo.
".venv\Scripts\python.exe" run.py
pause
exit /b 0

:nopython
echo.
echo Python isn't installed. Get it from https://www.python.org/downloads/
echo (tick "Add python.exe to PATH" during install), then double-click this file again.
pause
exit /b 1

:failed
echo.
echo Setup failed. Delete the .venv folder and try again, or ask Claude for help.
pause
exit /b 1
