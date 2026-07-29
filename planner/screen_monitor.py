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

# Claude Code footer: present in all Claude sessions (idle, active, diff review, etc.)
# Matches both "? for shortcuts" (idle at prompt, including while typing) and "for agents"
_CLAUDE_FOOTER_RE = re.compile(r'for shortcuts|for agents|manual mode|accept edits', re.IGNORECASE)
# Active turn only — absent when idle, in diff review, or any non-processing state
_ACTIVE_FOOTER_RE = re.compile(r'esc to interrupt', re.IGNORECASE)

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
    # If previously waiting for user action, stay sticky until Claude footer confirms idle/active.
    # Avoids NEEDS PERMISSION → ACTIVE oscillation when capture races with mid-render content.
    if prev_state in ("NEEDS PERMISSION", "NEEDS INPUT"):
        non_blank = [l for l in lines if l.strip()]
        footer = non_blank[-1] if non_blank else ""
        if not _CLAUDE_FOOTER_RE.search(footer):
            return prev_state
    if idle_seconds >= idle_threshold:
        return "IDLE"
    # Content recently changed (idle_seconds < threshold), but check whether Claude is
    # actually processing. Screen hardcopy pads to full terminal height with blank lines,
    # so inspect non-blank lines only. The footer line distinguishes idle ("? for shortcuts")
    # from active ("esc to interrupt"). If the footer is idle and no active-turn indicator
    # is present, return IDLE — avoids the ~30s false-ACTIVE window that occurs when a
    # just-finished turn or fresh ScreenMonitor start produces a one-time content diff.
    non_blank = [l for l in lines if l.strip()]
    if non_blank:
        footer = non_blank[-1]
        # Claude Code footer is present — use it to distinguish idle vs active.
        # "esc to interrupt" appears only during an active turn; "? for shortcuts"
        # appears when Claude is idle at the prompt. Without this check, a single
        # content diff (e.g. from fresh _snapshots on planner restart) would keep
        # ALL sessions ACTIVE for up to idle_threshold seconds.
        if _CLAUDE_FOOTER_RE.search(footer):
            if not _ACTIVE_FOOTER_RE.search(footer):
                return "IDLE"
    return "ACTIVE"


# Kept for backward compatibility (used in session_manager.py legacy path)
def parse_screen_ls(output: str) -> list[dict]:
    import re
    sessions = []
    for line in output.splitlines():
        m = re.match(r'\s+(\d+)\.(\S+)\s+\((Attached|Detached)\)', line)
        if m:
            pid, name, status = m.group(1), m.group(2), m.group(3)
            sessions.append({"pid": pid, "name": name,
                             "full_name": f"{pid}.{name}",
                             "attached": status == "Attached"})
    return sessions




class ScreenMonitor:
    def __init__(self, poll_interval: int = SCREEN_POLL_INTERVAL,
                 idle_threshold: int = SCREEN_IDLE_THRESHOLD):
        self._poll_interval = poll_interval
        self._idle_threshold = idle_threshold
        self._lock = threading.Lock()
        self._snapshots: dict[str, tuple[list[str], float]] = {}
        self._skip_until: dict[str, float] = {}
        self._thread: threading.Thread | None = None
        self._running = False
        from planner.backends import get_backend
        self._backend = get_backend()
        # Seed display with cached states from previous run; first poll overwrites.
        from planner.state import load_session_states
        cached = load_session_states()
        self._sessions: list[SessionState] = [
            SessionState(pid=fn, name=fn.split(".", 1)[1] if "." in fn else fn,
                         full_name=fn, attached=False,
                         state=entry["state"], last_lines=entry["lines"])
            for fn, entry in cached.items()
        ]
        # Restore idle-skip with a short delay rather than infinite — ensures sessions
        # that were idle at shutdown still get re-checked within 120s of restart.
        for fn, entry in cached.items():
            if entry["state"] == "IDLE":
                self._skip_until[fn] = time.monotonic() + 120

    def start(self) -> None:
        self._running = True
        self._thread = threading.Thread(target=self._poll_loop, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._running = False

    def get_sessions(self) -> list[SessionState]:
        with self._lock:
            return list(self._sessions)

    def wake(self, full_name: str) -> None:
        """Force the next poll to re-capture this session (clears idle skip)."""
        self._skip_until.pop(full_name, None)

    def capture_now(self, full_name: str) -> None:
        """Immediately capture one session and update _sessions — used on detach return."""
        import time as _time
        now = _time.monotonic()
        try:
            lines = self._backend.capture(full_name)
        except Exception:
            return
        # Always clear skip so the next poll can retry, even on empty capture.
        self._skip_until.pop(full_name, None)
        if not any(l.strip() for l in lines):
            return
        self._snapshots[full_name] = (lines, now)
        with self._lock:
            updated = []
            found = False
            for s in self._sessions:
                if s.full_name == full_name:
                    prev_state = s.state
                    state = detect_state(lines, 0, False, self._idle_threshold, prev_state)
                    updated.append(SessionState(
                        pid=s.pid, name=s.name, full_name=s.full_name,
                        attached=False, state=state, idle_seconds=0, last_lines=lines
                    ))
                    found = True
                else:
                    updated.append(s)
            if not found:
                name = full_name.split(".", 1)[1] if "." in full_name else full_name
                state = detect_state(lines, 0, False, self._idle_threshold, "")
                updated.append(SessionState(
                    pid=name, name=name, full_name=full_name,
                    attached=False, state=state, idle_seconds=0, last_lines=lines
                ))
            self._sessions = updated

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

        # Skip capturing sessions confirmed idle for a long time.
        # Always capture: attached, just-detached, awaiting input/permission.
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
                prev_lines, prev_time = self._snapshots.get(s.full_name, (None, now))
                # Ignore empty captures — hardcopy can return nothing during rapid state
                # transitions; treat as no change rather than blanking the display.
                if not any(l.strip() for l in lines):
                    lines = prev_lines or []
                elif lines != prev_lines:
                    self._snapshots[s.full_name] = (lines, now)
                    self._skip_until.pop(s.full_name, None)
                idle_secs = now - self._snapshots.get(s.full_name, (None, now))[1]
            else:
                # Skipped — reuse previous state
                prev = prev_map.get(s.full_name)
                lines = prev.last_lines if prev else []
                _, prev_time = self._snapshots.get(s.full_name, (None, now))
                idle_secs = now - (prev_time or now)

            prev_state = prev_states.get(s.full_name, "")
            state = detect_state(lines, idle_secs, s.attached, self._idle_threshold, prev_state)

            # Reduce polling frequency for idle sessions — re-check every 120s rather
            # than every poll interval. Never skip permanently: Claude can start a new
            # turn (→ ACTIVE → NEEDS PERMISSION) on any session at any time.
            if state == "IDLE" and not s.attached:
                self._skip_until[s.full_name] = now + 120
            elif s.full_name in self._skip_until:
                del self._skip_until[s.full_name]

            # Use name as pid for tmux (no pid prefix); screen keeps real pid
            updated.append(SessionState(
                pid=s.name, name=s.name, full_name=s.full_name,
                attached=s.attached, state=state,
                idle_seconds=idle_secs, last_lines=lines
            ))

        with self._lock:
            self._sessions = updated
