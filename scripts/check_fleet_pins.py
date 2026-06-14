"""Fleet pin survey — reports each worker's current clonway-cockpit pin vs the supported tag.

Usage (no args needed):
    python3 scripts/check_fleet_pins.py

Reads the supported tag from docs/pin-sync.md (first "Supported:" line) and queries each
worker repo's default-branch pyproject.toml via the GitHub API. Prints a status table and
exits non-zero if any worker is not on the supported tag.

Requires: `gh` CLI authenticated as a hearth-care org member.
"""

from __future__ import annotations

import json
import re
import subprocess
import sys
from base64 import b64decode
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
WORKER_REPOS = [
    "auto-orchestrator",
    "auto-admissions",
    "auto-bookkeeper",
    "auto-hr",
    "auto-inspector",
    "auto-marketer",
    "auto-secretary",
    "Auto-Procurer",
]
GH_ORG = "hearth-care"


def _supported_tag() -> str:
    pin_sync = REPO_ROOT / "docs" / "pin-sync.md"
    for line in pin_sync.read_text().splitlines():
        if line.startswith("Supported:"):
            tag = line.split(":", 1)[1].strip()
            if tag:
                return tag
    raise SystemExit("Could not parse supported tag from docs/pin-sync.md")


def _gh(*args: str) -> dict:
    result = subprocess.run(
        ["gh", "api", *args],
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        raise SystemExit(f"gh api failed: {result.stderr.strip()}")
    return json.loads(result.stdout)


def _resolve_tag_sha(tag: str) -> str:
    data = _gh(f"repos/{GH_ORG}/clonway-cockpit/git/refs/tags/{tag}")
    obj = data.get("object", {})
    sha = obj.get("sha", "")
    # Lightweight tag → SHA is the commit; annotated tag → need to dereference
    if obj.get("type") == "tag":
        tag_data = _gh(f"repos/{GH_ORG}/clonway-cockpit/git/tags/{sha}")
        sha = tag_data.get("object", {}).get("sha", sha)
    return sha


def _worker_pin(repo: str) -> str:
    data = _gh(f"repos/{GH_ORG}/{repo}/contents/pyproject.toml")
    content = b64decode(data["content"]).decode()
    # Find clonway-cockpit rev line
    m = re.search(r'clonway-cockpit\s*=\s*\{[^}]*rev\s*=\s*"([^"]+)"', content, re.DOTALL)
    if not m:
        return "NOT_FOUND"
    return m.group(1).strip()


def _commits_behind(base: str, head: str) -> int:
    """How many commits between base and head in the cockpit repo (base..head = ahead)."""
    result = subprocess.run(
        ["git", "-C", str(REPO_ROOT), "rev-list", "--count", f"{base}..{head}"],
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        return -1
    return int(result.stdout.strip())


def main() -> None:
    tag = _supported_tag()
    print(f"Supported tag: {tag}")

    tag_sha = _resolve_tag_sha(tag)
    print(f"Tag SHA: {tag_sha[:12]}\n")

    col_w = max(len(r) for r in WORKER_REPOS) + 2
    header = f"{'Worker':<{col_w}} {'Pin':<44} {'Status'}"
    print(header)
    print("-" * len(header))

    all_ok = True
    for repo in WORKER_REPOS:
        pin = _worker_pin(repo)
        if pin == "NOT_FOUND":
            note = "ERROR: no cockpit pin found"
            all_ok = False
        elif pin in (tag, tag_sha):
            note = f"OK (on {tag})"
        else:
            # Check if pin is a raw SHA or a different tag
            behind = _commits_behind(pin, tag_sha) if len(pin) >= 7 else -1
            if behind > 0:
                note = f"BEHIND {behind} commits (needs pin bump)"
            elif behind == 0:
                note = f"AHEAD of {tag} (raw SHA, should pin to tag)"
            else:
                note = f"UNKNOWN relative to {tag}"
            all_ok = False

        pin_display = pin[:40] if len(pin) > 12 else pin
        print(f"{repo:<{col_w}} {pin_display:<44} {note}")

    print()
    if all_ok:
        print(f"All workers on {tag}.")
        sys.exit(0)
    else:
        print(f"Action needed: bump workers not on {tag}. See docs/pin-sync.md.")
        sys.exit(1)


if __name__ == "__main__":
    main()
