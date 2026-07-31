@echo off
title Server — AI (WARNING: CPU Heavy)
echo.
echo   WARNING: AI stack is CPU-only. No GPU installed.
echo   Server will run hot and slow while models are loaded.
echo.
echo   Starting AI stack...
ssh homeserver "cd /srv/docker/ai && docker compose up -d"
echo.
echo   Opening Open WebUI in browser...
timeout /t 5 /nobreak > nul
start http://192.168.1.229:3004
echo.
pause
