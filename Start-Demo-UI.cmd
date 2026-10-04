@echo off
rem Double-click to start the demo UI; it opens in your browser. Close this window to stop it.
rem Uses demo\.venv when present (full ML stack: live runs). Otherwise any Python 3 serves the
rem saved results; live runs then need the venv, so use Start-Demo-UI-Simulate.cmd for UI work.
rem Extra arguments pass through, e.g.  Start-Demo-UI.cmd --simulate --ui path\to\build
cd /d "%~dp0demo"
rem Pick ONE interpreter, then run the server once (never fall through to a second server).
set "PY="
if exist ".venv\Scripts\python.exe" set "PY=.venv\Scripts\python.exe"
if not defined PY (where py >nul 2>nul && set "PY=py -3")
if not defined PY set "PY=python"
echo Starting demo UI with: %PY%
%PY% server.py --open %*
pause
