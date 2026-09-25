#!/usr/bin/env python3
"""
# 20204019  handlers.door — turn a login into a role, and nothing more

    GET /api/door        who am I, and a role token for the lobby

THE GAP THIS CLOSES. Cloudflare Access verifies you with Google and cloudflared
forwards the request with your email on it. kernel/auth.check_auth already
accepts that and hands back a hub SESSION. But handlers/lobby.py does not read
sessions -- it reads a JWT carrying a ROLE claim, because the lobby's whole job
is deciding what renders for master vs operator vs client. Nothing connected
the two, so a fully authenticated operator got 401 no_token.

This is the connector, and deliberately nothing else.

FROM THE FLAREVAULT LOGIN-FLOW SPEC, what is ours:

    "Login -> your standalone auth (Layer 1 + 2)"
    "Dashboard renders based on JWT role"
    "Layer 3 + 4 gates = empty hooks for now, FlarVault fills them later"

So this endpoint covers layers 1 and 2 and REFUSES to go further. It cannot
mint a token that reaches layer 3 or 4 -- not because the caller is untrusted,
but because a step-up must be proved at the moment it is used, and FlareVault
owns that proof. A token issued here that unlocked the vault would make the
ladder decorative.

WHY IT ISSUES RATHER THAN THE LOGIN ROUTE DOING IT. /api/auth/login is the
local door and predates all of this; Access users never touch it. Putting the
minting here means BOTH doors -- Google through the tunnel, and username and
password over Tailscale -- arrive at one place that decides the role. One
decision point, not two that can drift.
"""
import os

from kernel.auth import check_auth
from kernel import identity as _id

# EVERYONE THROUGH THIS DOOR IS AN OPERATOR.
#
# Not master, not client-full, not client-viewer. Those are FlareVault's to
# assert, and it is HOLDING THAT SPACE -- its tokens will carry the role and,
# for a client, the `servers` claim saying which nodes they own.
#
# Inventing that here would mean two issuers disagreeing about who someone is,
# and the one nobody is watching wins. So this door issues the one role it can
# actually justify: you got through, so you operate this fleet.
#
# When FlareVault's login is live, this endpoint stops minting and starts
# deferring. Nothing downstream changes, because identity.issue() already
# stamps the claims FlareVault will stamp.
DOOR_ROLE = 'operator'

# The ceiling this endpoint can issue. Named rather than inlined so that the
# day someone raises it, they have to edit a line that says what it means.
DOOR_CEILING = 2


# 20319701  GET /api/door — exchange a session for a role token
def get_door(handler, path, params):
    """# 20319701  GET /api/door

    Returns the identity behind this request and a short-lived role JWT the
    lobby accepts. Gate 1: you must already be through a door -- this mints a
    role, it does not authenticate anyone.
    """
    sess = check_auth(handler)
    if not sess:
        handler.send_json({
            'ok': False, 'error': 'no_session',
            'door': 'login.flarevault.dev',
            'detail': 'Sign in at the lobby. Over Tailscale, POST '
                      '/api/auth/login with a hub username and password.',
        }, 401)
        return

    user = sess.get('user', '')
    via = sess.get('via', 'local')
    role = DOOR_ROLE

    # Short TTL on purpose. The lobby re-asks whenever it needs to, and a role
    # token that outlives the session it came from is a session that cannot be
    # ended. 30 minutes is long enough that nobody notices and short enough
    # that revoking access at Cloudflare actually takes effect.
    try:
        token = _id.issue(user or 'operator', role, ttl=1800,
                          extra={'via': via, 'ceiling': DOOR_CEILING})
    except Exception as e:
        handler.send_json({'ok': False, 'error': 'issue_failed',
                           'detail': str(e)[:120]}, 500)
        return

    handler.send_json({
        'ok': True,
        'user': user,
        'role': role,
        'via': via,                 # 'cf-access' or 'local' -- which door
        'token': token,
        'expires_in': 1800,
        'ceiling': DOOR_CEILING,
        'use': 'send as Authorization: Bearer <token> to /api/lobby',
        'beyond_the_ceiling': {
            'layer_3': 'destructive actions — PIN/TOTP step-up, FlareVault owns it',
            'layer_4': 'vault and kill switch — USB present, FlareVault owns it',
            'note': 'This door cannot issue past layer 2 by design. A step-up '
                    'must be proved when it is used, not carried in a token '
                    'minted earlier.',
        },
    })
