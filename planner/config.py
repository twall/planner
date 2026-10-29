import os
from pathlib import Path

PLANNER_ROOT = Path(os.environ.get("PLANNER_INSTALL_DIR", Path.home() / "planner"))
DB_PATH = PLANNER_ROOT / "data" / "tasks.db"
TASKS_CONFIG_PATH = PLANNER_ROOT / "sessions.json"
SETTINGS_PATH = PLANNER_ROOT / "settings.json"

def _tty_slug() -> str:
    try:
        return os.ttyname(0).replace("/", "_")
    except OSError:
        return "default"


STATE_PATH = Path.home() / ".planner" / f"state{_tty_slug()}.json"
IGNORED_SESSIONS_PATH = Path.home() / ".planner" / "ignored_sessions.json"
HOOK_STATE_DIR = Path.home() / ".planner" / "hook_states"
MESSAGE_QUEUE_PATH = Path.home() / ".planner" / "message_queue.json"
LOG_PATH = Path.home() / ".planner" / "planner.log"

SCREEN_POLL_INTERVAL = 5
SCREEN_IDLE_THRESHOLD = 30
SESSION_BACKEND = os.environ.get("PLANNER_SESSION_BACKEND", "screen")
JIRA_SYNC_INTERVAL = 1800
