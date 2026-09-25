#!/usr/bin/env python3
"""
# 20404713  tools.step — where the build actually is. Not where anyone says.

    python3 hub/tools/step.py

THE PROBLEM THIS EXISTS FOR. The build order was written down and then ignored,
including by the one who wrote it. Steps got claimed as done, skipped, and
reinvented, and work landed that nobody asked for -- because "what step are we
on" was answered from memory instead of from the machine.

A document cannot fix that. A document is what failed. This CHECKS.

Every step below asks the running system a question with a yes or no answer.
Nothing here is a promise, an intention, or a description. If a check says NOT
DONE, that step is not done, whatever anyone remembers.

RULES IT ENFORCES
  - The current step is the FIRST one that fails. Not the one that feels next.
  - A later step passing does not skip an earlier one that fails. Out-of-order
    work is reported as OUT OF ORDER, because it is how the port band shipped
    before any project had been told.
  - It reports and never repairs. Same rule as everything else here.

SOURCE OF THE ORDER: hub/plan/BUILT-VS-ASKED.md, the five numbered items. If
that file and this disagree, this one is checkable and that one is prose, so
fix the prose.
"""
import json
import os
import re
import subprocess
import sys
import urllib.error
import urllib.request

HUB = os.environ.get('HUB_URL', 'http://127.0.0.1:8765')
ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def api(path):
    try:
        with urllib.request.urlopen(HUB + path, timeout=10) as r:
            return r.status, json.load(r)
    except urllib.error.HTTPError as e:
        return e.code, {}
    except Exception:
        return 0, {}


def read(rel):
    try:
        with open(os.path.join(ROOT, rel), encoding='utf-8', errors='ignore') as f:
            return f.read()
    except Exception:
        return ''


# ── The five steps, each with a question the machine can answer ──────────────

def step1():
    """Outbound through the server.

    The intake message has to LEAVE the machine because someone pressed
    something, not because a human pasted it into a session. Until this exists,
    the operator is still the transport and every later step is theatre.
    """
    src = read('hub/kernel/router.py')
    routed = '/api/outbox' in src
    worker = 'outbox' in read('hub/kernel/log.py').lower() or os.path.exists(
        os.path.join(ROOT, 'hub/kernel/outbox.py'))
    if routed and worker:
        return True, 'outbox route + delivery worker present'
    if routed:
        return False, 'route exists, no worker — nothing actually delivers'
    return False, 'no /api/outbox route; the operator is still the transport'


def step2():
    """_pending() reads the releases table, not a hardcoded dict.

    A PENDING block frozen in source reports last Tuesday's change forever. A
    project acting on it is acting on a fossil.
    """
    src = read('hub/handlers/registry.py')
    m = re.search(r'def _pending\(\)(.{0,1200})', src, re.S)
    if not m:
        return False, '_pending() not found'
    body = m.group(1)
    if 'control' in body or 'releases' in body or 'SELECT' in body:
        return True, '_pending() reads from the release record'
    return False, '_pending() is a hardcoded dict — reports a fossil'


def step3():
    """Push on change.

    When the master moves or a band shifts, every admitted project on that
    server gets told. Without it the registry records who arrived and never
    tells them anything again.
    """
    src = read('hub/kernel/control.py') + read('hub/handlers/exchange.py')
    has_publish = 'def publish(' in src
    routed = '/api/bulletins' in read('hub/kernel/router.py')
    auto = 'publish(' in read('hub/kernel/collect.py')
    if has_publish and routed and auto:
        return True, 'bulletins publish automatically on change'
    if has_publish and routed:
        return False, 'bulletins exist and are reachable, but nothing fires them on a change'
    if has_publish:
        return False, 'publish() exists with no URL — unreachable'
    return False, 'no publish mechanism'


def step4():
    """bootstrap calls enroll and exits printing a LIVE hostname.

    install -> hostname -> reachable, as one flow. This is the premise. The
    check is deliberately harsh: a hostname that does not answer is not a
    hostname, so this asks the internet, not the config.
    """
    boot = read('bootstrap.sh')
    calls = 'enroll.sh' in boot
    node = os.path.expanduser('~/.flare/node.json')
    host = ''
    try:
        with open(node) as f:
            host = (json.load(f) or {}).get('hostname', '')
    except Exception:
        pass
    live = False
    if host:
        try:
            code = subprocess.run(
                ['curl', '-s', '-o', '/dev/null', '-w', '%{http_code}', '-m', '12',
                 'https://' + host], capture_output=True, text=True, timeout=20).stdout.strip()
            live = code in ('200', '302')   # 302 = Access login, which is correct
        except Exception:
            live = False
    if calls and live:
        return True, 'bootstrap enrols and %s answers' % host
    if live:
        return False, '%s is live, but bootstrap does not call enroll.sh — not one flow' % host
    if calls:
        return False, 'bootstrap calls enroll.sh, but no live hostname on this node'
    return False, 'no enrolment from bootstrap and no live hostname'


def step5():
    """ONE intake end to end before a second is started.

    Four half-done intakes tell you less than one finished one. Done means: in
    the registry, and it has acknowledged what it was sent.
    """
    s, reg = api('/api/registry')
    projects = (reg or {}).get('projects') or []
    if not projects:
        return False, 'registry is empty — no intake has started'
    done = []
    for p in projects:
        name = p.get('name')
        s2, b = api('/api/bulletins/%s?all=1' % name)
        items = (b or {}).get('bulletins') or []
        if items and all(i.get('read') for i in items):
            done.append(name)
    if len(done) >= 1:
        return True, 'complete: %s' % ', '.join(done)
    return False, '%d registered, none has acknowledged anything' % len(projects)


STEPS = [
    ('1', 'Outbound through the server', step1),
    ('2', '_pending() from the record, not a dict', step2),
    ('3', 'Push on change', step3),
    ('4', 'bootstrap -> enroll -> live hostname', step4),
    ('5', 'One intake end to end', step5),
]


def main():
    print()
    print('  BUILD ORDER — checked against the machine, not remembered')
    print('  hub: %s' % HUB)
    print()
    results = []
    for num, title, fn in STEPS:
        try:
            ok, why = fn()
        except Exception as e:
            ok, why = False, 'check itself failed: %s' % str(e)[:60]
        results.append((num, title, ok, why))

    current = next((r for r in results if not r[2]), None)

    for num, title, ok, why in results:
        mark = 'done' if ok else ('HERE' if current and num == current[0] else '----')
        print('  [%s] %s. %s' % (mark, num, title))
        print('         %s' % why)

    print()
    if current is None:
        print('  All five pass. The order is complete.')
        return 0

    # Out-of-order work is the failure mode this tool exists to catch.
    ahead = [n for n, t, ok, w in results if ok and n > current[0]]
    print('  YOU ARE ON STEP %s.  %s' % (current[0], current[1]))
    print('  %s' % current[3])
    if ahead:
        print()
        print('  OUT OF ORDER: step(s) %s are done while %s is not.' % (', '.join(ahead), current[0]))
        print('  That is how the port band shipped before any project had been told.')
    print()
    print('  Anything that is not step %s is not the work.' % current[0])
    return 1


if __name__ == '__main__':
    sys.exit(main())
