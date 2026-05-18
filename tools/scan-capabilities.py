#!/usr/bin/env python3.11
"""
scan-capabilities.py — Snapshot of installed skills + connectors.

Walks three skill source trees:
  1. ~/.claude/skills/                                   — user-installed
  2. <Cowork session>/rpm/plugin_*/skills/               — Cowork plugins
  3. ~/T/claude-hostloop-plugins/.../skills/             — anthropic core

And aggregates MCP connectors from every plugin's .mcp.json.

Groups everything into 7 tiles (engineering, design, data, product,
productivity, anthropic, connectors) so the Hub's CapabilitiesCard on
/today can render a 7-tile grid that mirrors the Limitless Stack card.

POSTs ONE snapshot row to /api/agent-activity:
  source     = "inventory"
  event_type = "capability_snapshot"
  payload    = { skills_by_group, connectors, totals, scan_at, paths_scanned }

Best-effort: a failed POST never affects the snapshot — the script still
prints its summary to stdout. Same Keychain auth pattern as the other
producers (lsh-agent-activity-token → lsh-stack-health-token fallback).

Run manually:
    python3.11 tools/scan-capabilities.py
Or wire into a launchd job for daily refresh.
"""

import glob
import json
import os
import re
import subprocess
import sys
import time
from pathlib import Path

HOME = Path.home()

# ── Source trees ────────────────────────────────────────────────────────────
USER_SKILLS_DIR    = HOME / ".claude" / "skills"
COWORK_SESSIONS_GLOB = HOME / "Library" / "Application Support" / "Claude" / "local-agent-mode-sessions"
HOSTLOOP_GLOB      = Path("/var/folders").glob("*/*/T/claude-hostloop-plugins/*/skills")

# ── 7-tile bucketing ────────────────────────────────────────────────────────
# Maps plugin name → tile. Plugins not in this map get folded into "anthropic"
# (the catch-all for core / user / unbucketed). 7 tiles total to mirror the
# 7-tool Limitless Stack card on /today.
TILE_OF_PLUGIN = {
    "engineering":              "engineering",
    "design":                   "design",
    "data":                     "data",
    "product-management":       "product",
    "productivity":             "productivity",
    "pdf-viewer":               "productivity",
    "cowork-plugin-management": "productivity",
}

# Tile metadata — order + display label + hue (matches STACK_LAYOUT styling).
TILES = [
    {"id": "engineering",  "label": "Engineering",  "hue": 200},
    {"id": "design",       "label": "Design",       "hue": 280},
    {"id": "data",         "label": "Data",         "hue": 160},
    {"id": "product",      "label": "Product",      "hue": 330},
    {"id": "productivity", "label": "Productivity", "hue": 35},
    {"id": "anthropic",    "label": "Anthropic",    "hue": 50},
    {"id": "connectors",   "label": "Connectors",   "hue": 235},
]


# ── SKILL.md frontmatter parser ─────────────────────────────────────────────
# Minimal YAML-frontmatter parser. SKILL.md frontmatter is bounded by `---`
# lines and contains simple `key: value` (single line) or `key: >`/`key: |`
# (folded block). Good enough for our 60+ skills; a real YAML parser would
# pull in a dependency we don't need.
def parse_frontmatter(path: Path) -> dict:
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except Exception:
        return {}
    if not text.startswith("---"):
        return {}
    # Find the second --- delimiter
    parts = text.split("---", 2)
    if len(parts) < 3:
        return {}
    fm_text = parts[1]
    out = {}
    current_key = None
    current_block = []
    for line in fm_text.splitlines():
        if not line.strip():
            continue
        m = re.match(r"^([a-zA-Z_-]+):\s*(.*)$", line)
        if m and not line.startswith(" "):
            if current_key:
                out[current_key] = " ".join(current_block).strip()
            current_key = m.group(1)
            val = m.group(2).strip()
            if val in (">", "|"):
                current_block = []
            elif val.startswith('"') and val.endswith('"'):
                out[current_key] = val[1:-1]
                current_key = None
                current_block = []
            else:
                out[current_key] = val
                current_key = None
                current_block = []
        elif current_key:
            current_block.append(line.strip())
    if current_key and current_block:
        out[current_key] = " ".join(current_block).strip()
    return out


# ── Skill discovery ─────────────────────────────────────────────────────────
def find_session_root() -> Path | None:
    """Find the most recently modified Cowork session dir."""
    if not COWORK_SESSIONS_GLOB.exists():
        return None
    sessions = sorted(
        (p for p in COWORK_SESSIONS_GLOB.iterdir() if p.is_dir()),
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )
    if not sessions:
        return None
    # Find a session with an rpm/ dir (the active one with plugins installed).
    for s in sessions:
        for child in s.iterdir():
            rpm = child / "rpm"
            if rpm.is_dir() and (rpm / "manifest.json").exists():
                return rpm
    return None


def scan_plugin_skills(rpm_root: Path) -> tuple[list[dict], list[dict]]:
    """Return (skills, connectors) from the Cowork plugin tree."""
    skills: list[dict] = []
    connectors: list[dict] = []
    if not rpm_root or not rpm_root.exists():
        return skills, connectors

    manifest_path = rpm_root / "manifest.json"
    try:
        manifest = json.loads(manifest_path.read_text())
    except Exception:
        manifest = {"plugins": []}

    for plugin in manifest.get("plugins", []):
        pid = plugin.get("id")
        pname = plugin.get("name", pid)
        plugin_dir = rpm_root / pid
        if not plugin_dir.is_dir():
            continue
        # Skills
        skills_dir = plugin_dir / "skills"
        if skills_dir.is_dir():
            for skill_dir in skills_dir.iterdir():
                skill_md = skill_dir / "SKILL.md"
                if not skill_md.is_file():
                    continue
                fm = parse_frontmatter(skill_md)
                skills.append({
                    "name": fm.get("name") or skill_dir.name,
                    "description": fm.get("description", ""),
                    "source": "plugin",
                    "plugin": pname,
                    "tile": TILE_OF_PLUGIN.get(pname, "anthropic"),
                })
        # Connectors
        mcp_path = plugin_dir / ".mcp.json"
        if mcp_path.is_file():
            try:
                mcp = json.loads(mcp_path.read_text())
            except Exception:
                mcp = {}
            for server_name, server_def in (mcp.get("mcpServers") or {}).items():
                connectors.append({
                    "name": server_name,
                    "type": server_def.get("type", "unknown"),
                    "url": server_def.get("url", ""),
                    "plugin": pname,
                    "has_oauth": "oauth" in server_def,
                })
    return skills, connectors


def scan_user_skills() -> list[dict]:
    out: list[dict] = []
    if not USER_SKILLS_DIR.is_dir():
        return out
    for d in USER_SKILLS_DIR.iterdir():
        skill_md = d / "SKILL.md"
        if not skill_md.is_file():
            continue
        fm = parse_frontmatter(skill_md)
        out.append({
            "name": fm.get("name") or d.name,
            "description": fm.get("description", ""),
            "source": "user",
            "plugin": None,
            "tile": "anthropic",  # standalone user skills go in the catch-all tile
        })
    return out


def scan_hostloop_skills() -> list[dict]:
    out: list[dict] = []
    for skills_dir in HOSTLOOP_GLOB:
        if not skills_dir.is_dir():
            continue
        for d in skills_dir.iterdir():
            skill_md = d / "SKILL.md"
            if not skill_md.is_file():
                continue
            fm = parse_frontmatter(skill_md)
            out.append({
                "name": fm.get("name") or d.name,
                "description": fm.get("description", ""),
                "source": "anthropic-core",
                "plugin": None,
                "tile": "anthropic",
            })
    return out


# ── Identity helpers ────────────────────────────────────────────────────────
def detect_github_user() -> str:
    """Return the running user's GitHub login (e.g. 'mlav1114', 'draaen-osl').
    Prefers `gh api user --jq .login` so Matt and Dale each get tagged with
    their actual GitHub identity. Falls back to $LSH_USER env var, then
    macOS whoami, then 'unknown'. Used to tag inventory rows so the Hub's
    /api/workspace/.../capabilities endpoint can return each user's own
    snapshot instead of whichever Mac scanned last. """
    try:
        r = subprocess.run(["gh", "api", "user", "--jq", ".login"],
                           capture_output=True, text=True, timeout=5)
        login = r.stdout.strip()
        if login and r.returncode == 0:
            return login
    except Exception:
        pass
    env = os.environ.get("LSH_USER")
    if env:
        return env
    return os.environ.get("USER", "unknown")


# ── Activity reporter ───────────────────────────────────────────────────────
def report(payload: dict, title: str, gh_user: str) -> None:
    """Best-effort POST via tools/report-activity.sh. Actor encodes the
    scanner identity + the GitHub user, so the endpoint can filter to
    per-user snapshots."""
    helper = Path(__file__).resolve().parent / "report-activity.sh"
    if not helper.exists():
        return
    try:
        subprocess.run(
            [str(helper),
             "--source",     "inventory",
             "--event-type", "capability_snapshot",
             "--actor",      f"scan-capabilities/{gh_user}",
             "--repo",       "openscaffold-wiki",
             "--title",      title,
             "--payload",    json.dumps(payload)],
            check=False, timeout=10,
        )
    except Exception:
        pass


# ── Main ────────────────────────────────────────────────────────────────────
def main():
    rpm_root = find_session_root()
    plugin_skills, connectors = scan_plugin_skills(rpm_root) if rpm_root else ([], [])
    user_skills = scan_user_skills()
    hostloop_skills = scan_hostloop_skills()

    # Dedupe by skill name with explicit precedence:
    #   user_skills > plugin_skills > hostloop_skills
    # The hostloop temp folder is a CACHE that mirrors every plugin's installed
    # files, so it sees almost everything the plugin scan sees — letting it
    # override would clobber the correct plugin-tile attribution. Order is
    # important: hostloop first (lowest priority), then plugin (correct tile),
    # then user (custom override wins).
    by_name: dict[str, dict] = {}
    for s in hostloop_skills:
        by_name[s["name"]] = s
    for s in plugin_skills:
        by_name[s["name"]] = s
    for s in user_skills:
        by_name[s["name"]] = s
    all_skills = list(by_name.values())

    # Bucket into tiles
    skills_by_tile: dict[str, list[dict]] = {t["id"]: [] for t in TILES}
    for s in all_skills:
        tile = s["tile"] if s["tile"] in skills_by_tile else "anthropic"
        skills_by_tile[tile].append({"name": s["name"], "description": s["description"][:240], "source": s["source"], "plugin": s["plugin"]})

    # Connectors: dedup by name (engineering and product-management both ship
    # "slack", "notion", etc. — show one tile but record both plugin sources).
    conn_by_name: dict[str, dict] = {}
    for c in connectors:
        existing = conn_by_name.get(c["name"])
        if existing:
            existing["plugins"].append(c["plugin"])
        else:
            conn_by_name[c["name"]] = {
                "name":      c["name"],
                "type":      c["type"],
                "url":       c["url"],
                "plugins":   [c["plugin"]],
                "has_oauth": c["has_oauth"],
            }
    connectors_dedup = sorted(conn_by_name.values(), key=lambda c: c["name"])

    # Identify the scanner so the Hub can serve per-user snapshots.
    gh_user = detect_github_user()
    try:
        import socket
        host = socket.gethostname()
    except Exception:
        host = "unknown"

    payload = {
        "scan_at":       time.time(),
        "scanned_by":    gh_user,
        "host":          host,
        "skills_by_tile": skills_by_tile,
        "tile_meta":     TILES,
        "tile_counts":   {t["id"]: len(skills_by_tile[t["id"]]) for t in TILES if t["id"] != "connectors"},
        "connectors":    connectors_dedup,
        "totals": {
            "skills":     len(all_skills),
            "connectors": len(connectors_dedup),
            "tiles":      len(TILES),
        },
        "paths_scanned": [
            str(USER_SKILLS_DIR),
            str(rpm_root) if rpm_root else None,
            "hostloop-plugins",
        ],
    }
    payload["tile_counts"]["connectors"] = len(connectors_dedup)

    # Stdout summary
    print(f"=== capability snapshot @ {time.strftime('%Y-%m-%d %H:%M:%S')} (scanned_by={gh_user}, host={host}) ===")
    for tile in TILES:
        if tile["id"] == "connectors":
            count = len(connectors_dedup)
        else:
            count = len(skills_by_tile[tile["id"]])
        print(f"  {tile['label']:14s} {count:3d}")
    print(f"  TOTAL skills: {len(all_skills)}  ·  TOTAL connectors: {len(connectors_dedup)}")

    title = (f"capabilities — {len(all_skills)} skills · "
             f"{len(connectors_dedup)} connectors across {len(TILES)-1} groups")
    report(payload, title, gh_user)


if __name__ == "__main__":
    main()
