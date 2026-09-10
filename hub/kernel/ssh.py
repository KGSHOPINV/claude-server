#!/usr/bin/env python3
"""
# 20200003  kernel.ssh — SSH bridge and server info
Hub kernel: server command execution layer.
"""
import os
import subprocess
import threading

LOCAL_MODE = os.environ.get('HUB_LOCAL', '0') == '1'
SSH_HOST   = os.environ.get('HUB_SSH_HOST', 'localhost')
SSH_USER   = os.environ.get('HUB_SSH_USER', '')
SERVER_IP  = os.environ.get('HUB_SERVER_IP', '')

_cache = {'status': None, 'ts': 0, 'containers': None, 'containers_ts': 0}
_lock = threading.Lock()
_server_info_cache = None   # cached once per process restart

# 20200303  ssh_run — run shell cmd via SSH or bash -c in LOCAL_MODE
def ssh_run(cmd, timeout=15):
    try:
        args = ['bash', '-c', cmd] if LOCAL_MODE else ['ssh', SSH_HOST, cmd]
        r = subprocess.run(
            args,
            capture_output=True, text=True, timeout=timeout
        )
        return {
            'output': r.stdout.strip(),
            'error': r.stderr.strip(),
            'exitcode': r.returncode,
            'online': r.returncode == 0 or r.stdout.strip() != ''
        }
    except subprocess.TimeoutExpired:
        return {'output': '', 'error': 'Connection timed out', 'exitcode': -1, 'online': False}
    except FileNotFoundError:
        return {'output': '', 'error': 'ssh not found in PATH', 'exitcode': -1, 'online': False}
    except Exception as e:
        return {'output': '', 'error': str(e), 'exitcode': -1, 'online': False}
