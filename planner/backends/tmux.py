import subprocess

from planner.backends.base import RawSession, SessionBackend


class TmuxBackend(SessionBackend):
    def list_sessions(self) -> list[RawSession]:
        try:
            result = subprocess.run(
                ["tmux", "list-sessions", "-F", "#{session_name}:#{session_attached}"],
                capture_output=True, text=True, timeout=5
            )
        except Exception:
            return []
        if result.returncode != 0:
            return []
        sessions = []
        for line in result.stdout.splitlines():
            if ":" not in line:
                continue
            name, attached_flag = line.rsplit(":", 1)
            sessions.append(RawSession(name=name, full_name=name,
                                       attached=(attached_flag == "1")))
        return sessions

    def launch(self, name: str, shell_cmd: str, cwd: str | None = None,
               cols: int = 220, rows: int = 50) -> None:
        cmd = ["tmux", "new-session", "-d", "-s", name,
               "-x", str(cols), "-y", str(rows)]
        if cwd:
            cmd += ["-c", cwd]
        cmd += [shell_cmd]
        subprocess.run(cmd, timeout=10)

    def kill(self, full_name: str) -> None:
        subprocess.run(["tmux", "kill-session", "-t", full_name],
                       capture_output=True, timeout=5)

    def send_input(self, full_name: str, text: str) -> None:
        subprocess.run(
            ["tmux", "send-keys", "-t", full_name, text, "Enter"],
            capture_output=True, timeout=5
        )

    def attach_cmd(self, full_name: str) -> str:
        return f"tmux attach -t {full_name}"

    def capture(self, full_name: str) -> list[str]:
        try:
            result = subprocess.run(
                ["tmux", "capture-pane", "-p", "-t", full_name],
                capture_output=True, text=True, timeout=3
            )
            return result.stdout.splitlines()
        except Exception:
            return []
