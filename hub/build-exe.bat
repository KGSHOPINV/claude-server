@echo off
echo.
echo  Building HubServer.exe...
echo.

pip install pyinstaller pystray pillow --quiet

pyinstaller --onefile --noconsole --name HubServer --icon=NONE launcher.py

echo.
if exist dist\HubServer.exe (
  echo  Done! dist\HubServer.exe is ready.
  echo  Copy it next to server.py and double-click to launch.
) else (
  echo  Build failed. Check output above.
)
echo.
pause
