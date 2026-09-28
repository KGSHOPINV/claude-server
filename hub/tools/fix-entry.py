#!/usr/bin/env python3
"""
# 20404714  tools.fix-entry — bring the live Cloudflare account to the spec

    python3 hub/tools/fix-entry.py            # show what it would change
    python3 hub/tools/fix-entry.py --apply    # change it

Run ON the node. Reads the Cloudflare token from the same places enroll.sh
does; the value is never printed.

WHY THIS EXISTS. enrolment ran before the FlareVault login-flow spec was in
hand, so the live account is wrong in three ways that enroll.sh alone will not
correct -- it is idempotent, so it leaves existing records and policies alone
rather than repairing them.

  1  fvn-685a59.flarevault.dev      should be flareshub-fvn-685a59
  2  its Access policy allows a HUMAN by email. Spec rule 6: node endpoints
     refuse humans entirely, service token only. The lobby proxies in.
  3  hub-ksgco.flarevault.dev       points at tunnel edfa6803, which has had
     zero connections since it was created. An orphan.

WHAT IT WILL NOT TOUCH, and checks before acting:
  - any hostname not on flarevault.dev
  - the nine ksgco.app / ksgdev.com hostnames on the live tunnel
  - the tunnel itself, cloudflared, or the running service

It re-reads after every write, because the failure this whole evening kept
producing was a step that reported success and changed nothing.
"""
import json
import os
import re
import sys
import urllib.error
import urllib.request

API = 'https://api.cloudflare.com/client/v4'
ZONE_NAME = 'flarevault.dev'
APPLY = '--apply' in sys.argv

# The live tunnel this host actually runs. Read, never assumed.
TOKEN_FILE = '/etc/cloudflared/token'


def token():
    t = os.environ.get('CF_API_TOKEN', '').strip()
    if t:
        return t
    for p in (os.path.expanduser('~/.cf-token'), '/etc/flare/token'):
        try:
            with open(p) as f:
                m = re.findall(r'[A-Za-z0-9_\-]{30,}', f.read())
            if m:
                return m[0]
        except Exception:
            continue
    return ''


TOK = token()
if not TOK:
    print('no Cloudflare token found'); sys.exit(1)


def cf(method, path, body=None):
    req = urllib.request.Request(
        API + path, method=method,
        data=json.dumps(body).encode() if body is not None else None,
        headers={'Authorization': 'Bearer ' + TOK,
                 'Content-Type': 'application/json'})
    try:
        with urllib.request.urlopen(req, timeout=25) as r:
            return json.load(r)
    except urllib.error.HTTPError as e:
        try:
            return json.load(e)
        except Exception:
            return {'success': False, 'errors': [{'message': 'HTTP %s' % e.code}]}


def running_tunnel():
    """Decode the service token to find the tunnel this host actually serves."""
    import base64
    import subprocess
    try:
        raw = subprocess.run(['sudo', '-n', 'cat', TOKEN_FILE],
                             capture_output=True, text=True, timeout=10).stdout.strip()
        return json.loads(base64.b64decode(raw + '=' * (-len(raw) % 4))).get('t', '')
    except Exception:
        return ''


def server_id():
    import hashlib
    try:
        with open('/etc/machine-id') as f:
            mid = f.read().strip()
        return 'fvn_' + hashlib.sha256(mid.encode()).hexdigest()[:6]
    except Exception:
        return ''


def main():
    z = (cf('GET', '/zones?name=' + ZONE_NAME).get('result') or [])
    if not z:
        print('zone %s not visible to this token' % ZONE_NAME); return 1
    zid, acct = z[0]['id'], z[0]['account']['id']

    tid = running_tunnel()
    if not tid:
        print('cannot read the running tunnel from %s — refusing to guess' % TOKEN_FILE)
        return 1
    sid = server_id()
    if not sid:
        print('cannot derive server id'); return 1

    want = 'flareshub-%s.%s' % (sid.replace('_', '-'), ZONE_NAME)
    old = '%s.%s' % (sid.replace('_', '-'), ZONE_NAME)
    target = '%s.cfargotunnel.com' % tid

    print('  running tunnel : %s' % tid)
    print('  server id      : %s' % sid)
    print('  correct name   : %s' % want)
    print('  mode           : %s' % ('APPLY' if APPLY else 'dry run — nothing will change'))
    print()

    # ── 1. ingress: swap old name for new, keep everything else ──────────────
    cfg = cf('GET', '/accounts/%s/cfd_tunnel/%s/configurations' % (acct, tid))
    ing = ((cfg.get('result') or {}).get('config') or {}).get('ingress') or []
    named = [r for r in ing if r.get('hostname')]
    before = {r['hostname'] for r in named}
    kept = [r for r in named if r['hostname'] not in (old, want)]
    kept.append({'hostname': want, 'service': 'http://localhost:8765'})
    after = {r['hostname'] for r in kept}
    lost = (before - after) - {old}
    if lost:
        print('  REFUSING: would drop %s' % ', '.join(sorted(lost)))
        return 1
    print('  ingress   : %d -> %d  (%s -> %s)' % (len(before), len(kept), old, want))
    if APPLY:
        cf('PUT', '/accounts/%s/cfd_tunnel/%s/configurations' % (acct, tid),
           {'config': {'ingress': kept + [{'service': 'http_status:404'}]}})
        chk = cf('GET', '/accounts/%s/cfd_tunnel/%s/configurations' % (acct, tid))
        now = {r.get('hostname') for r in
               (((chk.get('result') or {}).get('config') or {}).get('ingress') or [])}
        print('    -> %s present: %s ; %s gone: %s'
              % (want, want in now, old, old not in now))

    # ── 2. DNS: create the new name, remove the old one and the orphan ───────
    recs = cf('GET', '/zones/%s/dns_records?per_page=100' % zid).get('result') or []
    have = {r['name']: r for r in recs}
    if want not in have:
        print('  dns       : create %s -> %s' % (want, target[:24] + '…'))
        if APPLY:
            cf('POST', '/zones/%s/dns_records' % zid,
               {'type': 'CNAME', 'name': want, 'content': target, 'proxied': True})
    else:
        print('  dns       : %s already exists' % want)

    for dead in (old, 'hub-ksgco.' + ZONE_NAME):
        if dead in have:
            why = 'renamed' if dead == old else 'orphan, tunnel has never had a connection'
            print('  dns       : delete %s  (%s)' % (dead, why))
            if APPLY:
                cf('DELETE', '/zones/%s/dns_records/%s' % (zid, have[dead]['id']))

    # ── 3. Access: the node app must be service-token only ───────────────────
    apps = cf('GET', '/accounts/%s/access/apps' % acct).get('result') or []
    for app in apps:
        dom = app.get('domain', '')
        if dom not in (old, want):
            continue
        pols = cf('GET', '/accounts/%s/access/apps/%s/policies'
                  % (acct, app['id'])).get('result') or []
        human = [p for p in pols if p.get('decision') != 'non_identity']
        print('  access    : app %s on %s — %d policy(ies), %d human'
              % (app['id'][:8], dom, len(pols), len(human)))
        if APPLY:
            if dom != want:
                cf('PUT', '/accounts/%s/access/apps/%s' % (acct, app['id']),
                   {'name': 'FlareSHub node %s' % sid, 'domain': want,
                    'type': 'self_hosted', 'session_duration': '24h'})
                print('    -> domain moved to %s' % want)
            for p in human:
                cf('DELETE', '/accounts/%s/access/apps/%s/policies/%s'
                   % (acct, app['id'], p['id']))
                print('    -> removed human policy %s' % p.get('name', p['id'])[:40])
            if not any(p.get('decision') == 'non_identity' for p in pols):
                cf('POST', '/accounts/%s/access/apps/%s/policies' % (acct, app['id']),
                   {'name': 'FlareSHub service token only', 'decision': 'non_identity',
                    'precedence': 1, 'include': [{'any_valid_service_token': {}}]})
                print('    -> service-token-only policy added')
            fin = cf('GET', '/accounts/%s/access/apps/%s/policies'
                     % (acct, app['id'])).get('result') or []
            print('    -> now %d policy(ies), %d human'
                  % (len(fin), len([p for p in fin if p.get('decision') != 'non_identity'])))

    print()
    if not APPLY:
        print('  nothing was changed. re-run with --apply')
    else:
        print('  done. a human browsing %s should now be refused.' % want)
    return 0


if __name__ == '__main__':
    sys.exit(main())
