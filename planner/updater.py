import subprocess
import urllib.request
import urllib.error
import json
from pathlib import Path

GITHUB_API = "https://api.github.com/repos/twall/planner/commits/master"
_INSTALL_ROOT = Path(__file__).parent.parent


def _local_sha() -> str | None:
    try:
        result = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            capture_output=True, text=True, timeout=5, cwd=_INSTALL_ROOT
        )
        return result.stdout.strip() if result.returncode == 0 else None
    except Exception:
        return None


def _remote_sha() -> str | None:
    try:
        req = urllib.request.Request(
            GITHUB_API,
            headers={"Accept": "application/vnd.github.sha",
                     "User-Agent": "planner-updater/1.0"}
        )
        with urllib.request.urlopen(req, timeout=8) as resp:
            return resp.read().decode().strip()
    except Exception:
        return None


def check_for_update() -> str | None:
    """Return a message string if an update is available, else None."""
    local = _local_sha()
    remote = _remote_sha()
    if not local or not remote:
        return None
    if local != remote:
        short = remote[:7]
        return f"Update available ({short}). Run: cd ~/planner && git pull"
    return None
