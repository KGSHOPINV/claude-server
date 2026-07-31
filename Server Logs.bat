@echo off
title Server — Container Logs
echo.
echo   Which container logs do you want to tail?
echo.
set /p CONTAINER=  Container name:
echo.
echo   Tailing logs for: %CONTAINER%
echo   (Press Ctrl+C to stop)
echo.
ssh homeserver "docker logs -f --tail 50 %CONTAINER%"
echo.
pause
