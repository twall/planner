import logging
import re
import subprocess
import time
from pathlib import Path

from planner.backends.base import RawSession, SessionBackend

_log = logging.getLogger(__name__)


class ScreenBackend(SessionBackend):
    def list_sessions(self) -> list[RawSession]:
        try:
            result = subprocess.run(["screen", "-ls"], capture_output=True, text=True, timeout=5)
        except Exception:
            return []
        sessions = []
        for line in result.stdout.splitlines():
            m = re.match(r'\s+(\d+)\.(\S+)\s+\((Attached|Detached)\)', line)
            if m:
                pid, name, status = m.group(1), m.group(2), m.group(3)
                full_name = f"{pid}.{name}"
                sessions.append(RawSession(name=name, full_name=full_name,
                                           attached=(status == "Attached")))
        return sessions

    def launch(self, name: str, shell_cmd: str, cwd: str | None = None,
               cols: int = 220, rows: int = 50) -> None:
        # Trap ERR so the screen session stays open on failure instead of silently dying.
        # EXIT is intentionally excluded — normal exit (after claude exits) should close cleanly.
        wrapped = (
            f"stty cols {cols} rows {rows}; "
            f"trap 'echo \"[planner] session failed (exit $?) — press Enter to close\"; read' ERR; "
            f"{shell_cmd}"
        )
        subprocess.run(
            ["screen", "-S", name, "-dm", "bash", "-c", wrapped],
            timeout=10, cwd=cwd
        )

    def kill(self, full_name: str) -> None:
        subprocess.run(["screen", "-S", full_name, "-X", "quit"],
                       capture_output=True, timeout=5)

    def send_input(self, full_name: str, text: str) -> None:
        try:
            subprocess.run(
                ["screen", "-S", full_name, "-p", "0", "-X", "stuff", text + "\r"],
                capture_output=True, timeout=5
            )
        except subprocess.TimeoutExpired:
            _log.warning("send_input timeout on session %s — session may be unresponsive", full_name)

    def send_raw(self, full_name: str, text: str) -> None:
        # screen 'stuff' truncates at ~200 chars; chunk to avoid silent truncation
        chunk_size = 150
        for i in range(0, len(text), chunk_size):
            try:
                subprocess.run(
                    ["screen", "-S", full_name, "-p", "0", "-X", "stuff", text[i:i + chunk_size]],
                    capture_output=True, timeout=5
                )
            except subprocess.TimeoutExpired:
                _log.warning("send_raw timeout on session %s at offset %d — aborting", full_name, i)
                break
            if i + chunk_size < len(text):
                time.sleep(0.05)

    def attach_cmd(self, full_name: str) -> str:
        return f"screen -d -r {full_name}"

    def capture(self, full_name: str) -> list[str]:
        tmp = f"/tmp/planner-screen-{full_name}.txt"
        try:
            subprocess.run(
                ["screen", "-S", full_name, "-p", "0", "-X", "hardcopy", tmp],
                timeout=3, capture_output=True
            )
            return Path(tmp).read_text(errors="replace").splitlines()
        except Exception:
            return []
