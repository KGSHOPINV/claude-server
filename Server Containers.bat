@echo off
title Server — Containers
echo.
echo   RUNNING CONTAINERS
echo   =============================================
echo.
ssh homeserver "docker ps --format 'table {{.Names}}\t{{.Status}}\t{{.Ports}}'"
echo.
pause
