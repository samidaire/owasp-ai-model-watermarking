@echo off
rem UI development without the ML stack: every "Run" replays a recorded log; nothing executes and
rem demo\results is never modified. The page reports mode "simulate". See UI_INTEGRATION.md.
call "%~dp0Start-Demo-UI.cmd" --simulate %*
