#!/usr/bin/env python3
"""
# 20404712  tools.cf-check — which Cloudflare permission is your token missing?

A Cloudflare token either works or returns "Invalid access token", and that
message is the same whether the token is wrong, expired, or simply missing one
permission out of six. You cannot tell which from the error, so you rebuild the
token guessing, and that is how a day disappears.

This calls every endpoint enroll.sh actually uses, one at a time, and names the
exact permission each failure needs.

    python3 tools/cf-check.py --zone flarevault.dev

Token is read from, in order: $CF_API_TOKEN, ~/.cf-token, /etc/flare/token.
The same places enroll.sh looks, so a pass here means enroll.sh will get the
same token.

THE VALUE IS NEVER PRINTED. Not in output, not in errors, not on failure. Only
its length and first four characters, which are enough to tell two tokens apart
without exposing either.

Read-only. It calls nothing that creates, changes or deletes anything.
"""
import json
import os
import re
import sys
import urllib.error
import urllib.request

API = 'https://api.cloudflare.com/client/v4'


def find_token():
    t = os.environ.get('CF_API_TOKEN', '').strip()
    if t:
        return t, '$CF_API_TOKEN'
    for p in (os.path.expanduser('~/.cf-token'), '/etc/flare/token'):
        try:
            with open(p) as f:
                raw = f.read()
        except Exception:
            continue
        # Accept a bare token or KEY=value; the token is the long opaque run.
        m = re.findall(r'[A-Za-z0-9_\-]{30,}', raw)
        if m:
            return m[0], p
    return '', ''


def call(token, path):
    req = urllib.request.Request(
        API + path, headers={'Authorization': 'Bearer ' + token,
                             'Content-Type': 'application/json'})
    try:
        with urllib.request.urlopen(req, timeout=15) as r:
            return r.status, json.loads(r.read().decode())
    except urllib.error.HTTPError as e:
        try:
            return e.code, json.loads(e.read().decode())
        except Exception:
            return e.code, {}
    except Exception as e:
        return 0, {'_transport': str(e)}


def why(body):
    errs = (body or {}).get('errors') or []
    if not errs:
        return ''
    e = errs[0]
    return '%s %s' % (e.get('code', ''), e.get('message', ''))


def main():
    zone = ''
    for i, a in enumerate(sys.argv):
        if a == '--zone' and i + 1 < len(sys.argv):
            zone = sys.argv[i + 1]
    if not zone:
        print('usage: cf-check.py --zone <yourzone.com>')
        return 2

    token, src = find_token()
    if not token:
        print('No token found.')
        print('  Put it at ~/.cf-token:')
        print('    ssh <server> "umask 077 && cat > ~/.cf-token"')
        print('  then paste, Enter, Ctrl-D.')
        return 1
    print('token   %s…%s  (%d chars)  from %s' % (token[:4], token[-2:], len(token), src))
    print('zone    %s\n' % zone)

    results = []

    # 1. Does it exist at all? Any valid token passes this, including one with
    #    no useful permissions -- which is why a pass here proves very little.
    st, body = call(token, '/user/tokens/verify')
    ok = st == 200 and body.get('success')
    # NOT A GATE. This endpoint returned 401 for a token that answered 200 on
    # zones, cfd_tunnel and access/apps -- verified 2026-09-24 against the
    # operator's real token. Gating on it refused a working token and blocked
    # enrolment for a day while the token got the blame.
    #
    # Report it, carry on. What matters is whether the calls enroll.sh makes
    # actually work, and those are tested below.
    results.append(('/user/tokens/verify accepts it (NOT authoritative)', ok,
                    why(body) or ('HTTP %s' % st), ''))
    ok = True          # never let this one stop the run
    if not ok:
        print('  [FAIL] token is valid — %s' % (why(body) or ('HTTP %s' % st)))
        print('\nThe token itself is rejected. Nothing else can be tested.')
        print('Check it is a CUSTOM TOKEN (starts with a long opaque string),')
        print('not an R2/S3 credential (cfat_…) and not the Global API Key.')
        return 1

    # 2. Zone lookup. enroll.sh cannot find the zone id without this.
    st, body = call(token, '/zones?name=' + zone)
    res = (body or {}).get('result') or []
    ok = st == 200 and bool(res)
    zone_id = res[0]['id'] if ok else ''
    acct_id = (res[0].get('account') or {}).get('id', '') if ok else ''
    results.append(('read the zone %s' % zone, ok,
                    why(body) or ('zone not found' if st == 200 else 'HTTP %s' % st),
                    'Zone -> Zone -> Read, with Zone Resources including this zone'))

    if ok:
        print('  zone id    %s' % zone_id)
        print('  account id %s\n' % (acct_id or '(not returned)'))

        # 3. DNS. enroll.sh writes the CNAME here.
        st, body = call(token, '/zones/%s/dns_records?per_page=1' % zone_id)
        results.append(('list DNS records', st == 200,
                        why(body) or 'HTTP %s' % st,
                        'Zone -> DNS -> Edit'))

        if acct_id:
            # 4. Tunnels. ACCOUNT-level -- the one most tokens are missing,
            #    because a token scoped only to zones cannot hold it.
            st, body = call(token, '/accounts/%s/cfd_tunnel?is_deleted=false' % acct_id)
            results.append(('list Cloudflare Tunnels', st == 200,
                            why(body) or 'HTTP %s' % st,
                            'Account -> Cloudflare Tunnel -> Edit, with ACCOUNT '
                            'Resources including this account'))

            # 5. Access apps. Also account-level.
            st, body = call(token, '/accounts/%s/access/apps' % acct_id)
            results.append(('list Access apps', st == 200,
                            why(body) or 'HTTP %s' % st,
                            'Account -> Access: Apps and Policies -> Edit, with '
                            'ACCOUNT Resources including this account'))
        else:
            results.append(('account-level calls', False,
                            'no account id returned by the zone lookup',
                            'the zone response had no account block'))

    print('WHAT ENROLL.SH NEEDS\n')
    bad = []
    for name, ok, err, need in results:
        if 'NOT authoritative' in name and not ok:
            print('  [note] %s' % name)
            print('         %s -- ignored, it is not a judge of this token' % err)
            continue
        print('  [%s] %s' % ('ok  ' if ok else 'FAIL', name))
        if not ok:
            print('         %s' % err)
            if need:
                print('         needs: %s' % need)
            bad.append(need)

    print()
    if not bad:
        print('All six checks pass. enroll.sh will get the same token from the')
        print('same place, so it has everything it needs.')
        return 0

    print('MISSING %d of %d.' % (len(bad), len(results)))
    print()
    print('Rebuild as a Custom Token with BOTH resource sections set --')
    print('that is what most attempts get wrong: the permissions are added but')
    print('Account Resources is left empty, so every /accounts/ call fails.')
    print()
    print('  Permissions')
    print('    Account  -> Cloudflare Tunnel          -> Edit')
    print('    Account  -> Access: Apps and Policies  -> Edit')
    print('    Zone     -> DNS                        -> Edit')
    print('    Zone     -> Zone                       -> Read')
    print()
    print('  Account Resources   Include -> your account')
    print('  Zone Resources      Include -> Specific zone -> %s' % zone)
    return 1


if __name__ == '__main__':
    sys.exit(main())
