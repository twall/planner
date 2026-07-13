import re
import subprocess
from pathlib import Path

from planner.backends.base import RawSession, SessionBackend


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
        # Wrap in bash to set terminal size before exec'ing the target command
        wrapped = f"stty cols {cols} rows {rows}; {shell_cmd}"
        subprocess.run(
            ["screen", "-S", name, "-dm", "bash", "-c", wrapped],
            timeout=10, cwd=cwd
        )

    def kill(self, full_name: str) -> None:
        subprocess.run(["screen", "-S", full_name, "-X", "quit"],
                       capture_output=True, timeout=5)

    def send_input(self, full_name: str, text: str) -> None:
        subprocess.run(
            ["screen", "-S", full_name, "-X", "stuff", text + "\r"],
            capture_output=True, timeout=5
        )

    def send_raw(self, full_name: str, text: str) -> None:
        subprocess.run(
            ["screen", "-S", full_name, "-X", "stuff", text],
            capture_output=True, timeout=5
        )

    def attach_cmd(self, full_name: str) -> str:
        return f"screen -d -r {full_name}"

    def capture(self, full_name: str) -> list[str]:
        tmp = f"/tmp/planner-screen-{full_name}.txt"
        try:
            subprocess.run(
                ["screen", "-S", full_name, "-X", "hardcopy", tmp],
                timeout=3, capture_output=True
            )
            return Path(tmp).read_text(errors="replace").splitlines()
        except Exception:
            return []
