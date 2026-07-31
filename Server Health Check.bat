@echo off
title Server — Health Check
echo.
echo   Running health check...
echo.
ssh homeserver "health-check"
echo.
pause
