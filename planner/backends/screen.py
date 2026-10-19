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
               cols: int = 220, rows: int = 50) -> bool:
        # Trap ERR so the screen session stays open on failure instead of silently dying.
        # EXIT is intentionally excluded — normal exit (after claude exits) should close cleanly.
        wrapped = (
            f"stty cols {cols} rows {rows}; "
            f"trap 'echo \"[planner] session failed (exit $?) — press Enter to close\"; read' ERR; "
            f"{shell_cmd}"
        )
        try:
            result = subprocess.run(
                ["screen", "-S", name, "-dm", "bash", "-c", wrapped],
                timeout=10, cwd=cwd, capture_output=True, text=True,
            )
        except subprocess.TimeoutExpired:
            _log.warning("launch timeout starting screen session %s", name)
            return False
        except OSError as e:
            # fork() itself can fail under resource pressure (EAGAIN/ENOMEM)
            # before screen even runs — subprocess.run raises OSError here
            # rather than returning a non-zero exit code. Must not propagate:
            # callers (resume_sessions' thread pool) would otherwise crash
            # the whole startup pass on one transient fork failure.
            _log.warning("launch raised OSError for screen session %s: %s", name, e)
            return False
        if result.returncode != 0:
            # e.g. "Cannot allocate memory" / "Resource unavailable" under fork/pty
            # pressure — this is the multiplexer itself failing, not the launched
            # command exiting. Callers must not mistake this for a dead session id.
            _log.warning(
                "launch failed starting screen session %s (exit %d): %s",
                name, result.returncode, result.stderr.strip()
            )
            return False
        return True

    def get_leaf_pid(self, full_name: str) -> str | None:
        """Resolve the PID of the command running inside the screen session.

        screen launches `bash -c "...; exec claude ..."` — the `exec` replaces
        bash's image in place, so the leaf command keeps the *child* PID of
        the screen daemon (full_name's own PID is the daemon, a separate
        process). Found via pgrep -P on the daemon's pid.
        """
        pid_str = full_name.split(".", 1)[0]
        if not pid_str.isdigit():
            return None
        try:
            result = subprocess.run(
                ["pgrep", "-P", pid_str], capture_output=True, timeout=5, text=True,
            )
        except (subprocess.TimeoutExpired, OSError):
            return None
        pids = result.stdout.split()
        return pids[0] if pids else None

    def kill(self, full_name: str, leaf_pid: str | None = None) -> None:
        try:
            result = subprocess.run(
                ["screen", "-S", full_name, "-X", "quit"],
                capture_output=True, timeout=5, text=True,
            )
            ok = result.returncode == 0
        except (subprocess.TimeoutExpired, OSError):
            ok = False
        # `-X quit` reports success even when it only tore down a stale
        # socket entry, or when the leaf command (e.g. claude) ignores the
        # SIGHUP it gets on pty teardown and survives as an orphan — so its
        # exit code alone can't be trusted to mean "nothing is running
        # anymore." Always also signal the daemon pid and the leaf pid
        # directly; each is a no-op if already dead.
        pid_str = full_name.split(".", 1)[0]
        if pid_str.isdigit():
            self._terminate_pid(int(pid_str))
        if leaf_pid and leaf_pid.isdigit():
            self._terminate_pid(int(leaf_pid))
        if not ok:
            _log.warning("kill: screen -X quit failed for %s; used SIGTERM/SIGKILL fallback", full_name)

    @staticmethod
    def _terminate_pid(pid: int) -> None:
        import os
        import signal
        try:
            os.kill(pid, signal.SIGTERM)
        except ProcessLookupError:
            return  # already dead; nothing to clean up
        except Exception:
            _log.warning("kill: SIGTERM failed for pid %d", pid)
            return
        for _ in range(10):
            time.sleep(0.2)
            try:
                os.kill(pid, 0)
            except ProcessLookupError:
                return
        try:
            os.kill(pid, signal.SIGKILL)
        except ProcessLookupError:
            pass

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
