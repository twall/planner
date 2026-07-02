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


def check_for_update() -> tuple[bool, str, str] | tuple[bool, None, None]:
    """Return (is_outdated, local_sha, remote_sha). Returns (False, None, None) on error."""
    local = _local_sha()
    remote = _remote_sha()
    if not local or not remote:
        return False, None, None
    return local != remote, local, remote


def do_upgrade() -> tuple[bool, str]:
    """Run git pull and reinstall. Returns (success, output)."""
    try:
        pull = subprocess.run(
            ["git", "pull", "--ff-only"],
            capture_output=True, text=True, timeout=30, cwd=_INSTALL_ROOT
        )
        if pull.returncode != 0:
            return False, pull.stderr.strip() or pull.stdout.strip()
        pip = subprocess.run(
            [str(_INSTALL_ROOT / ".venv" / "bin" / "pip"), "install", "-q", "-e", str(_INSTALL_ROOT)],
            capture_output=True, text=True, timeout=60, cwd=_INSTALL_ROOT
        )
        out = pull.stdout.strip()
        if pip.returncode != 0:
            return False, f"{out}\npip install failed: {pip.stderr.strip()}"
        return True, out
    except Exception as e:
        return False, str(e)
