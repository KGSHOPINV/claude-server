"""
Pulls live state from the server via SSH and updates server.db.
Run: python scripts/update-db.py

Requires: ssh homeserver configured in ~/.ssh/config
"""
import sqlite3
import subprocess
import json
from datetime import datetime, timezone

DB_PATH = "db/server.db"
NOW = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")

def ssh(cmd):
    result = subprocess.run(
        ["ssh", "homeserver", cmd],
        capture_output=True, text=True
    )
    return result.stdout.strip()

def main():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()

    print(f"\nConnecting to server...")

    # Get container states
    raw = ssh("docker ps -a --format '{{.Names}}|{{.Status}}|{{.Ports}}'")
    containers = {}
    for line in raw.splitlines():
        parts = line.split("|")
        if len(parts) >= 2:
            name, status = parts[0], parts[1]
            ports = parts[2] if len(parts) > 2 else ""
            containers[name] = {"status": status, "ports": ports}

    # Update containers table
    c.execute("DELETE FROM containers")
    for name, info in containers.items():
        c.execute(
            "INSERT INTO containers (name, status, ports, last_seen) VALUES (?,?,?,?)",
            (name, info["status"], info["ports"], NOW)
        )

    # Update service statuses based on live container data
    for name, info in containers.items():
        status = "up" if info["status"].startswith("Up") else "down"
        c.execute(
            "UPDATE services SET status=?, last_checked=? WHERE docker_container=?",
            (status, NOW, name)
        )

    # Get system info and log to notes
    load = ssh("cut -d' ' -f1-3 /proc/loadavg")
    mem = ssh("free -h | awk '/Mem:/ {printf \"%s / %s\", $3, $2}'")
    disk = ssh("df -h / | awk 'NR==2 {printf \"%s / %s (%s)\", $3, $2, $5}'")
    uptime = ssh("uptime -p")

    for key, val in [("load_avg", load), ("memory", mem), ("disk_root", disk), ("uptime", uptime)]:
        c.execute(
            "INSERT OR REPLACE INTO notes (category, key, value, updated) VALUES ('snapshot', ?, ?, ?)",
            (key, val, NOW)
        )

    conn.commit()
    conn.close()

    print(f"  Containers updated: {len(containers)}")
    print(f"  Load: {load}  |  Memory: {mem}  |  Disk: {disk}")
    print(f"  Snapshot saved at {NOW}\n")

if __name__ == "__main__":
    main()
