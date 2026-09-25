#!/usr/bin/env python3
"""
# 20404705  tools.check-views — the registry and the renderer must agree

The failure this exists to prevent: a view renders but has no registry entry,
so the app can display it and the nav cannot offer it. Nine views were in that
state before 2026-09-22 -- a third of the app reachable only by already knowing
the view key. The reverse rots too: an entry whose renderer was deleted puts a
dead item in the nav.

Neither drift is visible by reading either file alone, which is exactly why it
went unnoticed. Run from hub/:

    python3 tools/check-views.py

Exit 0 clean, 1 on drift. Cheap enough to run before every commit.
"""
import io
import os
import re
import sys

HUB = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def main():
    app = io.open(os.path.join(HUB, 'app.html'), encoding='utf-8').read()
    reg = io.open(os.path.join(HUB, 'ui', 'registry.js'), encoding='utf-8').read()

    i = app.find('function mountPaneContent')
    if i < 0:
        print('FAIL: mountPaneContent not found in app.html')
        return 1
    cases = set(re.findall(r"\n\s*case '([a-z_]+)':", app[i:i + 40000]))
    entries = set(re.findall(r"\n  ([a-z]+):\s*\{", reg))

    # `blank` is the fallback VIEW_DEFS.blank, never a case. Everything else
    # must exist on both sides.
    unregistered = sorted(cases - entries)
    unrenderable = sorted(entries - cases - {'blank'})

    for k in unregistered:
        print(f"DRIFT: case '{k}' renders but has no entry in ui/registry.js")
    for k in unrenderable:
        print(f"DRIFT: registry entry '{k}' has no renderer in app.html")

    if unregistered or unrenderable:
        return 1
    hidden = len(re.findall(r'hidden:true', reg))
    print(f'ok: {len(cases)} views, {len(entries)} registered, '
          f'{len(entries) - hidden} offered in nav')
    return 0


if __name__ == '__main__':
    sys.exit(main())
