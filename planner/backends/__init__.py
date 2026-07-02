from planner.backends.base import SessionBackend
from planner.backends.screen import ScreenBackend
from planner.backends.tmux import TmuxBackend


def get_backend(name: str | None = None) -> SessionBackend:
    import os
    backend = name or os.environ.get("PLANNER_SESSION_BACKEND", "screen")
    if backend == "tmux":
        return TmuxBackend()
    return ScreenBackend()
