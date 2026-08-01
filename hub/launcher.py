"""
Hub Launcher — Windows system tray app.
Starts the hub server in the background and opens the browser.

Build to EXE:
  pip install pyinstaller pystray pillow
  pyinstaller --onefile --noconsole --name HubServer launcher.py
"""

import os
import sys
import subprocess
import threading
import webbrowser
import time

PORT = 8765
HUB_URL = f'http://localhost:{PORT}'

# ── Find server.py ────────────────────────────────────────────────────────────
BASE = os.path.dirname(os.path.abspath(sys.argv[0]))
SERVER_PY = os.path.join(BASE, 'server.py')
if not os.path.exists(SERVER_PY):
    # Running from dist/ — look one level up
    SERVER_PY = os.path.join(BASE, '..', 'hub', 'server.py')
SERVER_PY = os.path.normpath(SERVER_PY)

_proc = None
_running = False


def start_server():
    global _proc, _running
    python = sys.executable
    _proc = subprocess.Popen(
        [python, SERVER_PY],
        creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0),
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    _running = True


def stop_server():
    global _proc, _running
    if _proc:
        _proc.terminate()
        try:
            _proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            _proc.kill()
    _running = False


def open_browser():
    time.sleep(1.2)  # give server a moment
    webbrowser.open(HUB_URL)


def restart_server(icon, item):
    stop_server()
    time.sleep(0.5)
    start_server()
    icon.notify('Hub server restarted', 'Server Hub')


def open_hub(icon, item):
    webbrowser.open(HUB_URL)


def open_mobile(icon, item):
    webbrowser.open(f'{HUB_URL}/mobile')


def quit_app(icon, item):
    stop_server()
    icon.stop()


# ── Try to import pystray ─────────────────────────────────────────────────────
try:
    import pystray
    from PIL import Image, ImageDraw

    def make_icon():
        img = Image.new('RGBA', (64, 64), (0, 0, 0, 0))
        d = ImageDraw.Draw(img)
        d.ellipse([4, 4, 60, 60], fill='#39d0c4')
        d.text((22, 20), '⊞', fill='#0d1117')
        return img

    def run_tray():
        icon = pystray.Icon(
            'HubServer',
            make_icon(),
            'Server Hub',
            menu=pystray.Menu(
                pystray.MenuItem('Open Hub',    open_hub,    default=True),
                pystray.MenuItem('Open Mobile', open_mobile),
                pystray.Menu.SEPARATOR,
                pystray.MenuItem('Restart Server', restart_server),
                pystray.Menu.SEPARATOR,
                pystray.MenuItem('Quit', quit_app),
            )
        )
        icon.run()

    HAS_TRAY = True

except ImportError:
    HAS_TRAY = False


# ── Main ──────────────────────────────────────────────────────────────────────
if __name__ == '__main__':
    start_server()
    threading.Thread(target=open_browser, daemon=True).start()

    if HAS_TRAY:
        run_tray()
    else:
        # Fallback — no tray, just keep alive
        print(f'Hub running at {HUB_URL}')
        print('Close this window to stop.')
        try:
            while True:
                time.sleep(1)
        except KeyboardInterrupt:
            stop_server()
