#!/usr/bin/env python3
"""
registry_gen.py — Telescope code scanner and registry validator for the hub codebase.

Usage (from repo root):
    python hub/tools/registry_gen.py

What it does:
    1. SCAN   — walks hub/server.py, hub/kernel/*.py, hub/handlers/*.py for
                telescope-code comments in the form:  # 20XXXXXX  <name/description>
    2. VALIDATE — cross-references found codes against knowledge/telescope-codes.json
                  and reports SHADOW (found but unregistered) and DEAD (registered but
                  not found in source).
    3. GENERATE — writes knowledge/registry-live.json with timestamp, scan results,
                  and matched objects with their source file + line.

Exit codes:
    0 — clean (no shadow, no dead)
    1 — issues found (shadow or dead codes present)
"""

import glob
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

# ── Paths (relative to repo root) ────────────────────────────────────────────

REPO_ROOT = Path(__file__).resolve().parents[2]  # hub/tools/../../  == repo root

SOURCE_GLOBS = [
    "hub/server.py",
    "hub/kernel/*.py",
    "hub/handlers/*.py",
]

CODES_MAP_PATH = REPO_ROOT / "knowledge" / "telescope-codes.json"
REGISTRY_LIVE_PATH = REPO_ROOT / "knowledge" / "registry-live.json"

# ── Code pattern ─────────────────────────────────────────────────────────────
# Matches:  # 20302701  GET /api/status
#       or  # 20200301  db_conn
CODE_RE = re.compile(r"#\s*(20\d{6})\s+(.+)")

# ─────────────────────────────────────────────────────────────────────────────


def load_codes_map() -> dict:
    """Load knowledge/telescope-codes.json.

    Returns an empty dict (with a warning) if the file doesn't exist yet —
    all found codes will be reported as SHADOW.
    """
    if not CODES_MAP_PATH.exists():
        print(f"  [warn] {CODES_MAP_PATH.relative_to(REPO_ROOT)} not found — "
              "treating all source codes as SHADOW")
        return {}

    with CODES_MAP_PATH.open(encoding="utf-8") as fh:
        data = json.load(fh)

    # Support three shapes:
    #   flat:    {"20200301": "db_conn", ...}
    #   codes:   {"codes": {"20200301": "db_conn", ...}}
    #   objects: {"objects": [{"code": "20200301", "name": "db_conn", ...}, ...]}
    if isinstance(data, dict) and "codes" in data:
        return data["codes"]
    if isinstance(data, dict) and "objects" in data:
        return {obj["code"]: obj.get("description", obj.get("name", ""))
                for obj in data["objects"] if "code" in obj}
    return data


def collect_source_files() -> list[Path]:
    """Expand SOURCE_GLOBS into a sorted, deduplicated list of existing paths."""
    found: list[Path] = []
    for pattern in SOURCE_GLOBS:
        for match in glob.glob(str(REPO_ROOT / pattern)):
            p = Path(match)
            if p.is_file() and p not in found:
                found.append(p)
    return sorted(found)


def scan_file(path: Path) -> list[dict]:
    """Return all telescope-code hits in a single file.

    Each hit is:
        {
            "code":  "20302701",
            "name":  "GET /api/status",
            "file":  "hub/server.py",
            "line":  412,
            "raw":   "    elif path == '/api/status':  # 20302701  GET /api/status"
        }
    """
    hits: list[dict] = []
    rel = path.relative_to(REPO_ROOT).as_posix()

    with path.open(encoding="utf-8", errors="replace") as fh:
        for lineno, raw in enumerate(fh, start=1):
            m = CODE_RE.search(raw)
            if m:
                hits.append({
                    "code": m.group(1),
                    "name": m.group(2).strip(),
                    "file": rel,
                    "line": lineno,
                    "raw":  raw.rstrip(),
                })
    return hits


def scan_all(source_files: list[Path]) -> list[dict]:
    """Scan every source file and merge results."""
    all_hits: list[dict] = []
    for path in source_files:
        hits = scan_file(path)
        all_hits.extend(hits)
    return all_hits


def validate(hits: list[dict], codes_map: dict) -> dict:
    """Cross-reference scan hits against the authoritative codes map.

    Returns:
        {
            "matched": [...],   # in both source and map
            "shadow":  [...],   # in source but NOT in map  (bug — unregistered)
            "dead":    [...],   # in map but NOT in source  (possible dead code)
        }
    """
    found_codes: set[str] = {h["code"] for h in hits}
    map_codes:   set[str] = set(codes_map.keys())

    matched_codes = found_codes & map_codes
    shadow_codes  = found_codes - map_codes
    dead_codes    = map_codes   - found_codes

    # Build full hit objects for matched and shadow (multiple hits per code allowed)
    matched: list[dict] = []
    shadow:  list[dict] = []

    for hit in hits:
        if hit["code"] in matched_codes:
            matched.append({**hit, "map_description": codes_map[hit["code"]]})
        else:
            shadow.append(hit)

    # Dead = in map, not in source; we only have the map description
    dead: list[dict] = []
    for code in sorted(dead_codes):
        dead.append({
            "code":            code,
            "map_description": codes_map[code],
        })

    return {"matched": matched, "shadow": shadow, "dead": dead}


def print_report(results: dict, source_files: list[Path]) -> None:
    """Print the three-section console report."""
    matched = results["matched"]
    shadow  = results["shadow"]
    dead    = results["dead"]

    print()
    print("Scanned files:")
    if source_files:
        for f in source_files:
            rel = f.relative_to(REPO_ROOT).as_posix()
            hit_count = sum(1 for h in matched + shadow if h["file"] == rel)
            print(f"  {rel}  ({hit_count} codes)")
    else:
        print("  (no source files found)")

    # ── MATCHED ──────────────────────────────────────────────────────────────
    print()
    print(f"✓ MATCHED ({len(matched)} codes in both source and map)")
    if matched:
        for h in sorted(matched, key=lambda x: x["code"]):
            print(f"  {h['code']}  {h['name']}  [{h['file']}:{h['line']}]")
    else:
        print("  (none)")

    # ── SHADOW ───────────────────────────────────────────────────────────────
    print()
    print(f"⚠ SHADOW ({len(shadow)} codes in source but NOT in map — unregistered)")
    if shadow:
        for h in sorted(shadow, key=lambda x: x["code"]):
            print(f"  {h['code']}  {h['name']}  [{h['file']}:{h['line']}]")
    else:
        print("  (none)")

    # ── DEAD ─────────────────────────────────────────────────────────────────
    print()
    print(f"✗ DEAD ({len(dead)} codes registered but NOT found in source)")
    if dead:
        for d in dead:
            print(f"  {d['code']}  {d['map_description']}")
    else:
        print("  (none)")


def write_registry_live(results: dict, source_files: list[Path]) -> None:
    """Write knowledge/registry-live.json."""
    matched = results["matched"]
    shadow  = results["shadow"]
    dead    = results["dead"]

    output = {
        "_meta": {
            "generated":    datetime.now(timezone.utc).isoformat(),
            "generator":    "hub/tools/registry_gen.py",
            "codes_map":    str(CODES_MAP_PATH.relative_to(REPO_ROOT).as_posix()),
            "source_files": [f.relative_to(REPO_ROOT).as_posix() for f in source_files],
        },
        "summary": {
            "matched": len(matched),
            "shadow":  len(shadow),
            "dead":    len(dead),
            "clean":   len(shadow) == 0 and len(dead) == 0,
        },
        "matched": sorted(matched, key=lambda x: x["code"]),
        "shadow":  sorted(shadow,  key=lambda x: x["code"]),
        "dead":    sorted(dead,    key=lambda x: x["code"]),
    }

    REGISTRY_LIVE_PATH.parent.mkdir(parents=True, exist_ok=True)
    with REGISTRY_LIVE_PATH.open("w", encoding="utf-8") as fh:
        json.dump(output, fh, indent=2)
        fh.write("\n")

    print()
    print(f"Written: {REGISTRY_LIVE_PATH.relative_to(REPO_ROOT).as_posix()}")


# ── Main ─────────────────────────────────────────────────────────────────────


def main() -> int:
    print("=" * 60)
    print("  Hub Telescope Code Scanner — registry_gen.py")
    print("=" * 60)
    print(f"  Repo root: {REPO_ROOT}")
    print(f"  Codes map: {CODES_MAP_PATH.relative_to(REPO_ROOT).as_posix()}")

    codes_map    = load_codes_map()
    source_files = collect_source_files()
    hits         = scan_all(source_files)
    results      = validate(hits, codes_map)

    print_report(results, source_files)
    write_registry_live(results, source_files)

    matched = results["matched"]
    shadow  = results["shadow"]
    dead    = results["dead"]

    print()
    print("Summary:")
    print(f"  {len(matched)} matched   "
          f"{len(shadow)} shadow   "
          f"{len(dead)} dead")

    if shadow or dead:
        print()
        print("Result: ISSUES FOUND — fix shadow/dead codes before merging")
        return 1

    print()
    print("Result: CLEAN")
    return 0


if __name__ == "__main__":
    sys.exit(main())
