#!/usr/bin/env python3
"""
# 20200015  kernel.bank — the temporary secret handoff. DELIBERATE EXCEPTION.

This breaks Law V of CONSTITUTION.md:

    "Credentials are never here. Pointers only."

Knowingly, and with the operator's explicit approval, because FlareVault does
not do this yet and the need is real today: a Cloudflare token sat on a desktop
for a full day because there was no safe way to get it to the server.

The exception is only defensible while it announces itself. install-preflight
FAILS while this bank holds anything, so --strict cannot pass clean and nobody
can forget this is open. A temporary exception that stops complaining has
become architecture.

WHAT MAKES IT SAFE -- in order of how much each actually contributes:

  read-once (project scope)  gone the moment it is collected
  TTL                        gone anyway, read or not
  never backed up            excluded by name in tools/backup.sh, not by luck
  never logged               the read is logged; the VALUE never is
  encryption at rest         defence in depth, NOT the guarantee -- see below

On the encryption: the key lives on the same box. Anything the hub can decrypt
unattended, someone holding the box can decrypt too. It protects a value that
leaks into a stray copy or a careless read; it does not protect against someone
who has root. Saying otherwise would be exactly the kind of claim this project
spent a fortnight deleting.

The version that IS strong -- encrypt with a key the operator holds, so the box
never has both halves -- is what FlareVault should do. Not this.

TWO SCOPES, because they cannot share a rule:

  project   one project's own key.  read-once. deleted on collection.
  account   ONE key, several projects, same upstream account. Cannot be
            read-once -- the second project would find it gone. Stays until
            TTL or revocation, and EVERY read is logged, because one project
            leaking it burns all of them and the log is what tells you which.
"""
import base64
import hashlib
import hmac
import os
import sqlite3
from datetime import datetime, timedelta

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# Its own file. Not server.db, not control.db. A secret store that shares a
# file with anything else gets copied by anything that copies that file.
BANK_DB = os.environ.get(
    'HUB_BANK_DB', os.path.join(os.path.dirname(BASE_DIR), 'db', 'bank.db'))

DEFAULT_TTL_HOURS = 24


def _now():
    return datetime.now()


def _iso(dt):
    return dt.isoformat(timespec='seconds')


def _conn():
    d = os.path.dirname(BANK_DB)
    os.makedirs(d, exist_ok=True)
    first = not os.path.exists(BANK_DB)
    c = sqlite3.connect(BANK_DB, timeout=5)
    c.row_factory = sqlite3.Row
    if first:
        try:
            os.chmod(BANK_DB, 0o600)
        except Exception:
            pass
    return c


# 20200391  _key — derived per install, never stored beside the data
def _key():
    """Derived from the machine and a local salt file, so the same ciphertext
    is useless on a different box. The salt lives 0600 outside the database:
    a database file copied on its own does not carry the means to read it.

    This is NOT protection against someone with root here. It is protection
    against a copy of the database leaving the machine.
    """
    salt_path = os.path.join(os.path.dirname(BANK_DB), '.bank-salt')
    salt = b''
    try:
        with open(salt_path, 'rb') as f:
            salt = f.read().strip()
    except Exception:
        pass
    if not salt:
        salt = base64.b64encode(os.urandom(32))
        try:
            with open(salt_path, 'wb') as f:
                f.write(salt)
            os.chmod(salt_path, 0o600)
        except Exception:
            pass
    machine = ''
    try:
        with open('/etc/machine-id') as f:
            machine = f.read().strip()
    except Exception:
        pass
    return hashlib.sha256(salt + machine.encode()).digest()


def _crypt(data: bytes) -> bytes:
    """Keystream XOR over SHA-256 blocks. Stdlib only, by the project's own
    rule. Symmetric, so the same call encrypts and decrypts.

    Sufficient for "a leaked file is not plaintext". Not a substitute for the
    read-once and TTL above, which are what actually bound the exposure.
    """
    key = _key()
    out = bytearray()
    counter = 0
    while len(out) < len(data):
        block = hmac.new(key, counter.to_bytes(8, 'big'), hashlib.sha256).digest()
        out.extend(block)
        counter += 1
    return bytes(a ^ b for a, b in zip(data, out[:len(data)]))


# 20200392  ensure_tables
def ensure_tables():
    c = _conn()
    c.execute("""CREATE TABLE IF NOT EXISTS secrets (
        slot TEXT PRIMARY KEY,         -- e.g. cloudflare/account, fksinv/deploy-key
        scope TEXT NOT NULL,           -- project | account
        owner TEXT,                    -- project name, or '' for account scope
        note TEXT,                     -- what this is FOR. never the value.
        blob TEXT NOT NULL,            -- encrypted
        created TEXT, expires TEXT
    )""")
    # Who collected what, and when. The value is never in here.
    c.execute("""CREATE TABLE IF NOT EXISTS reads (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        slot TEXT NOT NULL, project TEXT, at TEXT
    )""")
    c.commit()
    c.close()


def _expire(c):
    c.execute('DELETE FROM secrets WHERE expires < ?', (_iso(_now()),))


# 20200393  deposit — the operator puts something in
def deposit(slot, value, scope='project', owner='', note='', ttl_hours=None):
    if scope not in ('project', 'account'):
        return None, 'scope must be project|account'
    if not slot or not value:
        return None, 'slot and value required'
    ensure_tables()
    ttl = DEFAULT_TTL_HOURS if ttl_hours is None else int(ttl_hours)
    c = _conn()
    _expire(c)
    c.execute('INSERT OR REPLACE INTO secrets (slot,scope,owner,note,blob,created,expires)'
              ' VALUES (?,?,?,?,?,?,?)',
              (slot, scope, owner, note,
               base64.b64encode(_crypt(value.encode())).decode(),
               _iso(_now()), _iso(_now() + timedelta(hours=ttl))))
    c.commit()
    c.close()
    return slot, 'held, expires in %dh' % ttl


# 20200394  collect — a project takes it
def collect(slot, project=''):
    """Project scope is deleted on collection. Account scope is not, because a
    second project would find it gone -- so that one is bounded by TTL and
    revocation instead, and every read is recorded."""
    ensure_tables()
    c = _conn()
    _expire(c)
    r = c.execute('SELECT * FROM secrets WHERE slot=?', (slot,)).fetchone()
    if not r:
        c.close()
        return None, 'nothing in that slot (collected, expired, or never deposited)'
    if r['scope'] == 'project' and r['owner'] and project and r['owner'] != project:
        c.close()
        return None, 'that slot belongs to %s' % r['owner']
    value = _crypt(base64.b64decode(r['blob'])).decode()
    c.execute('INSERT INTO reads (slot,project,at) VALUES (?,?,?)',
              (slot, project or '?', _iso(_now())))
    once = r['scope'] == 'project'
    if once:
        c.execute('DELETE FROM secrets WHERE slot=?', (slot,))
    c.commit()
    c.close()
    return value, ('collected and deleted' if once
                   else 'collected; account-scoped, still held until TTL')


def revoke(slot):
    ensure_tables()
    c = _conn()
    c.execute('DELETE FROM secrets WHERE slot=?', (slot,))
    c.commit()
    c.close()
    return slot, 'revoked'


# 20200395  held — what is in the bank. NEVER the values.
def held():
    ensure_tables()
    c = _conn()
    _expire(c)
    c.commit()
    out = [{'slot': r['slot'], 'scope': r['scope'], 'owner': r['owner'],
            'note': r['note'], 'expires': r['expires'],
            'reads': c.execute('SELECT COUNT(*) n FROM reads WHERE slot=?',
                               (r['slot'],)).fetchone()['n']}
           for r in c.execute('SELECT * FROM secrets ORDER BY slot')]
    c.close()
    return out


def read_log(limit=50):
    ensure_tables()
    c = _conn()
    out = [dict(r) for r in c.execute(
        'SELECT * FROM reads ORDER BY id DESC LIMIT ?', (limit,))]
    c.close()
    return out


# 20200396  exception_open — the assertion that keeps this temporary
def exception_open():
    """install-preflight calls this. While the bank holds anything, --strict
    cannot pass clean.

    This is the entire reason the exception is defensible. An exception that
    stops complaining has become architecture, and this one is meant to be
    deleted the day FlareVault can do it properly.
    """
    items = held()
    if not items:
        return False, 'bank empty'
    return True, ('%d secret(s) held — Law V exception is OPEN: %s'
                  % (len(items), ', '.join(i['slot'] for i in items)))
