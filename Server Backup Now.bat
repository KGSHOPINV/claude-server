@echo off
title Server — Backup
echo.
echo   Running backup now...
echo.
ssh homeserver "sudo server-backup"
echo.
pause
