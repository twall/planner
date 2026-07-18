import re
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from planner.config import SCREEN_POLL_INTERVAL, SCREEN_IDLE_THRESHOLD


PROMPT_PATTERNS = [
    re.compile(r'\[Y/n\]', re.IGNORECASE),
    re.compile(r'\[y/N\]', re.IGNORECASE),
    re.compile(r'\(y/n\)', re.IGNORECASE),
    re.compile(r'\(Yes/No\)', re.IGNORECASE),
    # Claude interactive selection menu (footer always has both nav and Esc to cancel)
    re.compile(r'Enter to select\s*[·•].*Esc to cancel', re.IGNORECASE),
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
    # PERMISSION_PATTERNS scan full buffer (permission dialogs may span more lines)
    for pattern in PERMISSION_PATTERNS:
        if pattern.search(text):
            return "NEEDS PERMISSION"
    # PROMPT_PATTERNS scan only recent lines — avoids false matches from scrollback history
    recent = "\n".join(lines[-20:])
    for pattern in PROMPT_PATTERNS:
        if pattern.search(recent):
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


IDLE_SKIP_CYCLES = 5  # skip this many poll cycles after N consecutive idle polls


class ScreenMonitor:
    def __init__(self, poll_interval: int = SCREEN_POLL_INTERVAL,
                 idle_threshold: int = SCREEN_IDLE_THRESHOLD):
        self._poll_interval = poll_interval
        self._idle_threshold = idle_threshold
        self._sessions: list[SessionState] = []
        self._lock = threading.Lock()
        self._snapshots: dict[str, tuple[list[str], float]] = {}
        self._skip_until: dict[str, float] = {}  # full_name -> monotonic time to resume capturing
        self._active_until: dict[str, float] = {}  # full_name -> monotonic time to force ACTIVE after detach
        self._idle_count: dict[str, int] = {}  # full_name -> consecutive IDLE poll count
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
        prev_map = {s.full_name: s for s in self._sessions}
        prev_attached = {s.full_name: s.attached for s in self._sessions}

        # Skip capturing sessions that have been confirmed idle for a long time.
        # Attached sessions always get captured (state may change on detach).
        # Also capture sessions that just detached — content may reflect new activity.
        # Never skip sessions waiting for input/permission — they must be re-captured each
        # cycle so we detect when the prompt is answered and the state changes.
        needs_response = {"NEEDS PERMISSION", "NEEDS INPUT"}
        just_detached = {s.full_name for s in raw
                         if not s.attached and prev_attached.get(s.full_name, False)}
        to_capture = [s for s in raw
                      if s.attached or s.full_name in just_detached
                      or prev_states.get(s.full_name, "") in needs_response
                      or now >= self._skip_until.get(s.full_name, 0)]

        # Capture eligible sessions in parallel — sequential screen hardcopy is ~400ms each
        captures: dict[str, list[str]] = {}
        if to_capture:
            workers = min(len(to_capture), 10)
            with ThreadPoolExecutor(max_workers=workers) as pool:
                futures = {pool.submit(self._backend.capture, s.full_name): s for s in to_capture}
                for fut in as_completed(futures):
                    s = futures[fut]
                    try:
                        captures[s.full_name] = fut.result()
                    except Exception:
                        captures[s.full_name] = []

        updated = []
        for s in raw:
            if s.full_name in captures:
                lines = captures[s.full_name]
                prev_lines, prev_time = self._snapshots.get(s.full_name, (None, None))
                if prev_lines is None:
                    backdated = now - self._idle_threshold
                    self._snapshots[s.full_name] = (lines, backdated)
                    idle_secs = float(self._idle_threshold)
                elif s.full_name in just_detached:
                    # Grace window: force ACTIVE for idle_threshold seconds after detach.
                    # Work done while attached doesn't change the captured buffer, so
                    # content equality isn't a reliable idle signal immediately post-detach.
                    idle_secs = 0.0
                    self._snapshots[s.full_name] = (lines, now)
                    self._skip_until.pop(s.full_name, None)
                    self._active_until[s.full_name] = now + self._idle_threshold
                elif lines == prev_lines:
                    idle_secs = now - prev_time
                    # Clamp to 0 while inside the post-detach grace window
                    if now < self._active_until.get(s.full_name, 0):
                        idle_secs = 0.0
                else:
                    idle_secs = 0.0
                    self._snapshots[s.full_name] = (lines, now)
                    # New content — clear any skip so we capture next poll too
                    self._skip_until.pop(s.full_name, None)
                    self._active_until.pop(s.full_name, None)
            else:
                # Skipped — reuse previous state
                prev = prev_map.get(s.full_name)
                lines = prev.last_lines if prev else []
                _, prev_time = self._snapshots.get(s.full_name, (None, now))
                idle_secs = now - (prev_time or now)

            prev_state = prev_states.get(s.full_name, "")
            state = detect_state(lines, idle_secs, s.attached, self._idle_threshold, prev_state)

            # Only skip capturing after IDLE_SKIP_CYCLES consecutive idle polls.
            # This prevents missing a permission prompt that arrives shortly after
            # a session goes idle — a single idle poll is not enough to skip.
            if state == "IDLE" and not s.attached:
                count = self._idle_count.get(s.full_name, 0) + 1
                self._idle_count[s.full_name] = count
                if count >= IDLE_SKIP_CYCLES:
                    skip_duration = self._poll_interval * IDLE_SKIP_CYCLES
                    self._skip_until[s.full_name] = now + skip_duration
                self._active_until.pop(s.full_name, None)
            else:
                self._idle_count.pop(s.full_name, None)
                if s.full_name in self._skip_until:
                    del self._skip_until[s.full_name]

            # Use name as pid for tmux (no pid prefix); screen keeps real pid
            updated.append(SessionState(
                pid=s.name, name=s.name, full_name=s.full_name,
                attached=s.attached, state=state,
                idle_seconds=idle_secs, last_lines=lines
            ))

        with self._lock:
            self._sessions = updated
