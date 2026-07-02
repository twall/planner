import re
import threading
import time
from dataclasses import dataclass, field
from planner.config import SCREEN_POLL_INTERVAL, SCREEN_IDLE_THRESHOLD


PROMPT_PATTERNS = [
    re.compile(r'\[Y/n\]', re.IGNORECASE),
    re.compile(r'\[y/N\]', re.IGNORECASE),
    re.compile(r'\(y/n\)', re.IGNORECASE),
    re.compile(r'\(Yes/No\)', re.IGNORECASE),
]

PERMISSION_PATTERNS = [
    # Claude Code permission UI — require the trailing ? to avoid matching content diffs/configs
    re.compile(r'Allow this action\?'),
    re.compile(r'Do you want to (allow|proceed)', re.IGNORECASE),
    re.compile(r'needs your permission', re.IGNORECASE),
    # Claude Code permission footer (may have extra options after "Tab to amend")
    re.compile(r'Esc to cancel\s*[·•]\s*Tab to amend', re.IGNORECASE),
    # Bash/tool approval prompt
    re.compile(r'This command requires approval', re.IGNORECASE),
]


@dataclass
class SessionState:
    pid: str
    name: str
    full_name: str
    attached: bool
    state: str = "IDLE"
    idle_seconds: float = 0.0
    last_lines: list[str] = field(default_factory=list)


def detect_state(lines: list[str], idle_seconds: float, attached: bool = False,
                 idle_threshold: int = SCREEN_IDLE_THRESHOLD, prev_state: str = "") -> str:
    if attached:
        return "ATTACHED"
    text = "\n".join(lines)
    for pattern in PERMISSION_PATTERNS:
        if pattern.search(text):
            return "NEEDS PERMISSION"
    for pattern in PROMPT_PATTERNS:
        if pattern.search(text):
            return "NEEDS INPUT"
    if idle_seconds >= idle_threshold:
        return "IDLE"
    return "ACTIVE"


# Kept for backward compatibility (used in session_manager.py legacy path)
def parse_screen_ls(output: str) -> list[dict]:
    from planner.backends.screen import ScreenBackend
    sessions = ScreenBackend().list_sessions()
    return [{"pid": s.name, "name": s.name, "full_name": s.full_name,
             "attached": s.attached} for s in sessions]


class ScreenMonitor:
    def __init__(self, poll_interval: int = SCREEN_POLL_INTERVAL,
                 idle_threshold: int = SCREEN_IDLE_THRESHOLD):
        self._poll_interval = poll_interval
        self._idle_threshold = idle_threshold
        self._sessions: list[SessionState] = []
        self._lock = threading.Lock()
        self._snapshots: dict[str, tuple[list[str], float]] = {}
        self._thread: threading.Thread | None = None
        self._running = False
        # Backend resolved once; respects PLANNER_SESSION_BACKEND env var
        from planner.backends import get_backend
        self._backend = get_backend()

    def start(self) -> None:
        self._running = True
        self._thread = threading.Thread(target=self._poll_loop, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._running = False

    def get_sessions(self) -> list[SessionState]:
        with self._lock:
            return list(self._sessions)

    def _poll_loop(self) -> None:
        while self._running:
            self._poll()
            time.sleep(self._poll_interval)

    def _poll(self) -> None:
        try:
            raw = self._backend.list_sessions()
        except Exception:
            return

        now = time.monotonic()
        prev_states = {s.full_name: s.state for s in self._sessions}
        updated = []
        for s in raw:
            lines = self._backend.capture(s.full_name)
            prev_lines, prev_time = self._snapshots.get(s.full_name, (None, None))
            if prev_lines is None:
                backdated = now - self._idle_threshold
                self._snapshots[s.full_name] = (lines, backdated)
                idle_secs = float(self._idle_threshold)
            elif lines == prev_lines:
                idle_secs = now - prev_time
            else:
                idle_secs = 0.0
                self._snapshots[s.full_name] = (lines, now)
            prev_state = prev_states.get(s.full_name, "")
            state = detect_state(lines, idle_secs, s.attached, self._idle_threshold, prev_state)
            # Use name as pid for tmux (no pid prefix); screen keeps real pid
            updated.append(SessionState(
                pid=s.name, name=s.name, full_name=s.full_name,
                attached=s.attached, state=state,
                idle_seconds=idle_secs, last_lines=lines
            ))

        with self._lock:
            self._sessions = updated
