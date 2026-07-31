@echo off
title Server Hub
echo.
echo   Server Hub
echo   ══════════════════════════════════════
echo   Starting local API server...
echo   Opens at: http://localhost:8765
echo.
echo   Close this window to stop the hub.
echo.
start "" "http://localhost:8765"
python "%~dp0hub\server.py"
pause
