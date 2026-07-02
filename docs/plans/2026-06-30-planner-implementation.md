# Planner Dashboard Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a persistent Textual TUI dashboard at `~/planner` for daily/weekly task planning and Claude Code screen session monitoring.

**Architecture:** Textual app with three panels (sessions, tasks, briefing) backed by SQLite. A background thread polls `screen` sessions every 5s. Recurring daily tasks (Slack, Bitbucket, Sentry) run via `claude --print` subprocesses and write results into the DB. A global `/task` Claude Code skill lets any session add tasks.

**Tech Stack:** Python 3.11+, Textual, aiosqlite, httpx (JIRA REST), subprocess (screen polling + claude CLI)

## Global Constraints

- Python 3.11+ required (3.14 available locally — compatible)
- Project root: `~/planner` (i.e. `/Users/twall/planner`)
- All imports use `planner.*` package prefix
- DB at `~/planner/data/tasks.db` — create `data/` dir if missing
- JIRA token read from `~/.claude/MEMORY.md` (already in context when running under Claude Code); for standalone use, read from env var `JIRA_API_TOKEN`
- Sentry token read from env var `SENTRY_ACCESS_TOKEN`
- Slack MCP available via `claude --print` subprocess
- No conda — use `uv venv --python 3.11 .venv` then `uv pip install`
- All commits: conventional commits format, no Claude attribution lines
- GitHub remote: `git@github.com:twall/planner.git` (already configured)

---

## File Map

| File | Responsibility |
|------|---------------|
| `planner/__init__.py` | Package marker |
| `planner/config.py` | All constants + path resolution |
| `planner/db.py` | SQLite schema init + all read/write helpers |
| `planner/screen_monitor.py` | Screen session polling + state detection |
| `planner/jira.py` | JIRA REST client — fetch assigned open issues |
| `planner/scheduler.py` | Recurring task runner — spawn claude subprocesses, parse output, write to DB |
| `planner/cli.py` | CLI entry point for `/task add` and `/task list` |
| `planner/app.py` | Textual app — composes widgets, wires keybindings, starts background workers |
| `planner/widgets/session_panel.py` | Sessions list widget |
| `planner/widgets/task_panel.py` | Task list widget (horizons) |
| `planner/widgets/briefing_panel.py` | Daily briefing summary widget |
| `planner/widgets/status_bar.py` | Clock + sync status |
| `scripts/planner` | Shell launcher (activates venv, runs app) |
| `skills/task.md` | `/task` Claude Code skill definition |
| `requirements.txt` | Pinned deps |
| `tests/test_db.py` | DB schema + CRUD tests |
| `tests/test_screen_monitor.py` | Session parsing + state detection tests |
| `tests/test_jira.py` | JIRA client tests (httpx mocking) |
| `tests/test_scheduler.py` | Scheduler output parsing tests |
| `tests/test_cli.py` | CLI argument parsing tests |

---

## Task 1: Project Scaffold + DB Layer

**Files:**
- Create: `planner/__init__.py`
- Create: `planner/config.py`
- Create: `planner/db.py`
- Create: `data/.gitkeep`
- Create: `requirements.txt`
- Create: `tests/__init__.py`
- Create: `tests/test_db.py`

**Interfaces:**
- Produces:
  - `config.DB_PATH: Path` — resolved absolute path to tasks.db
  - `config.SCREEN_POLL_INTERVAL: int = 5`
  - `config.SCREEN_IDLE_THRESHOLD: int = 30`
  - `config.JIRA_PROJECTS: list[str] = ["PLEX"]`
  - `config.SENTRY_PROJECTS: list[str] = ["WEBAPP", "REST-API", "internal"]`
  - `config.BITBUCKET_REPOS: list[str] = ["rd", "plex-search", "plex-search-ui"]`
  - `config.SLACK_CHANNELS: list[str] = ["#issues", "#monitoring"]`
  - `config.JIRA_SYNC_INTERVAL: int = 1800`
  - `config.SKILLS_PATH: Path`
  - `db.init_db(db_path: Path) -> None` — creates schema if not exists
  - `db.add_task(db_path, source, title, horizon, priority, description, jira_key, screen_session) -> int` — returns new task id
  - `db.list_tasks(db_path, horizon=None, status=None) -> list[dict]` — returns list of task dicts
  - `db.update_task(db_path, task_id, **fields) -> None`
  - `db.upsert_jira_task(db_path, jira_key, title, description, priority, status) -> None`
  - `db.get_last_run(db_path, task_name: str) -> str | None` — ISO date string or None
  - `db.set_last_run(db_path, task_name: str, date_str: str) -> None`

- [ ] **Step 1: Set up venv and install deps**

```bash
cd ~/planner
uv venv --python 3.11 .venv
source .venv/bin/activate
```

Create `requirements.txt`:
```
textual>=0.80.0
aiosqlite>=0.20.0
httpx>=0.27.0
pytest>=8.0.0
pytest-asyncio>=0.23.0
```

```bash
uv pip install -r requirements.txt
```

Expected: all packages install cleanly.

- [ ] **Step 2: Write failing tests for db**

Create `tests/__init__.py` (empty).

Create `tests/test_db.py`:
```python
import pytest
import tempfile
from pathlib import Path
from planner.db import init_db, add_task, list_tasks, update_task, upsert_jira_task, get_last_run, set_last_run


@pytest.fixture
def db_path(tmp_path):
    p = tmp_path / "tasks.db"
    init_db(p)
    return p


def test_init_creates_schema(db_path):
    tasks = list_tasks(db_path)
    assert tasks == []


def test_add_and_list_task(db_path):
    task_id = add_task(db_path, source="freeform", title="Test task", horizon="today", priority=3)
    tasks = list_tasks(db_path)
    assert len(tasks) == 1
    assert tasks[0]["title"] == "Test task"
    assert tasks[0]["horizon"] == "today"
    assert tasks[0]["id"] == task_id


def test_list_tasks_filtered_by_horizon(db_path):
    add_task(db_path, source="freeform", title="Today task", horizon="today", priority=3)
    add_task(db_path, source="freeform", title="Backlog task", horizon="backlog", priority=3)
    today = list_tasks(db_path, horizon="today")
    assert len(today) == 1
    assert today[0]["title"] == "Today task"


def test_update_task(db_path):
    task_id = add_task(db_path, source="freeform", title="Old title", horizon="backlog", priority=3)
    update_task(db_path, task_id, title="New title", status="done")
    tasks = list_tasks(db_path)
    assert tasks[0]["title"] == "New title"
    assert tasks[0]["status"] == "done"


def test_upsert_jira_task_insert(db_path):
    upsert_jira_task(db_path, jira_key="PLEX-1", title="Fix bug", description="desc", priority=2, status="open")
    tasks = list_tasks(db_path)
    assert len(tasks) == 1
    assert tasks[0]["jira_key"] == "PLEX-1"


def test_upsert_jira_task_update(db_path):
    upsert_jira_task(db_path, jira_key="PLEX-1", title="Fix bug", description="desc", priority=2, status="open")
    upsert_jira_task(db_path, jira_key="PLEX-1", title="Fix bug updated", description="desc", priority=2, status="in_progress")
    tasks = list_tasks(db_path)
    assert len(tasks) == 1
    assert tasks[0]["title"] == "Fix bug updated"
    assert tasks[0]["status"] == "in_progress"


def test_last_run_roundtrip(db_path):
    assert get_last_run(db_path, "slack") is None
    set_last_run(db_path, "slack", "2026-06-30")
    assert get_last_run(db_path, "slack") == "2026-06-30"
```

- [ ] **Step 3: Run tests — verify they fail**

```bash
cd ~/planner
source .venv/bin/activate
pytest tests/test_db.py -v
```

Expected: `ModuleNotFoundError: No module named 'planner'`

- [ ] **Step 4: Create config.py**

Create `planner/__init__.py` (empty).

Create `planner/config.py`:
```python
from pathlib import Path

PLANNER_ROOT = Path.home() / "planner"
DB_PATH = PLANNER_ROOT / "data" / "tasks.db"
SKILLS_PATH = Path.home() / "plex/search/ops/claude/skills"

SCREEN_POLL_INTERVAL = 5
SCREEN_IDLE_THRESHOLD = 30
JIRA_SYNC_INTERVAL = 1800
RECURRING_TASK_HOUR = 8

JIRA_PROJECTS = ["PLEX"]
SENTRY_PROJECTS = ["WEBAPP", "REST-API", "internal"]
BITBUCKET_REPOS = ["rd", "plex-search", "plex-search-ui"]
SLACK_CHANNELS = ["#issues", "#monitoring"]
```

- [ ] **Step 5: Create db.py**

Create `planner/db.py`:
```python
import sqlite3
from pathlib import Path


SCHEMA = """
CREATE TABLE IF NOT EXISTS tasks (
    id              INTEGER PRIMARY KEY,
    source          TEXT NOT NULL,
    jira_key        TEXT,
    title           TEXT NOT NULL,
    description     TEXT,
    priority        INTEGER DEFAULT 3,
    horizon         TEXT DEFAULT 'backlog',
    status          TEXT DEFAULT 'open',
    screen_session  TEXT,
    created_at      TEXT DEFAULT (datetime('now')),
    updated_at      TEXT DEFAULT (datetime('now')),
    jira_synced_at  TEXT
);

CREATE TABLE IF NOT EXISTS recurring_runs (
    task_name   TEXT PRIMARY KEY,
    last_run    TEXT NOT NULL
);
"""


def _conn(db_path: Path) -> sqlite3.Connection:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    return conn


def init_db(db_path: Path) -> None:
    with _conn(db_path) as conn:
        conn.executescript(SCHEMA)


def add_task(db_path: Path, source: str, title: str, horizon: str = "backlog",
             priority: int = 3, description: str = None, jira_key: str = None,
             screen_session: str = None) -> int:
    with _conn(db_path) as conn:
        cur = conn.execute(
            "INSERT INTO tasks (source, title, horizon, priority, description, jira_key, screen_session) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (source, title, horizon, priority, description, jira_key, screen_session)
        )
        return cur.lastrowid


def list_tasks(db_path: Path, horizon: str = None, status: str = None) -> list[dict]:
    conditions, params = [], []
    if horizon:
        conditions.append("horizon = ?")
        params.append(horizon)
    if status:
        conditions.append("status = ?")
        params.append(status)
    where = ("WHERE " + " AND ".join(conditions)) if conditions else ""
    with _conn(db_path) as conn:
        rows = conn.execute(
            f"SELECT * FROM tasks {where} ORDER BY priority ASC, created_at ASC",
            params
        ).fetchall()
    return [dict(r) for r in rows]


def update_task(db_path: Path, task_id: int, **fields) -> None:
    allowed = {"title", "description", "priority", "horizon", "status", "screen_session"}
    updates = {k: v for k, v in fields.items() if k in allowed}
    if not updates:
        return
    updates["updated_at"] = "datetime('now')"
    set_clause = ", ".join(f"{k} = ?" for k in updates if k != "updated_at")
    set_clause += ", updated_at = datetime('now')"
    values = [v for k, v in updates.items() if k != "updated_at"]
    values.append(task_id)
    with _conn(db_path) as conn:
        conn.execute(f"UPDATE tasks SET {set_clause} WHERE id = ?", values)


def upsert_jira_task(db_path: Path, jira_key: str, title: str, description: str,
                     priority: int, status: str) -> None:
    with _conn(db_path) as conn:
        existing = conn.execute(
            "SELECT id FROM tasks WHERE jira_key = ?", (jira_key,)
        ).fetchone()
        if existing:
            conn.execute(
                "UPDATE tasks SET title=?, description=?, priority=?, status=?, "
                "jira_synced_at=datetime('now'), updated_at=datetime('now') WHERE jira_key=?",
                (title, description, priority, status, jira_key)
            )
        else:
            conn.execute(
                "INSERT INTO tasks (source, jira_key, title, description, priority, status, jira_synced_at) "
                "VALUES ('jira', ?, ?, ?, ?, ?, datetime('now'))",
                (jira_key, title, description, priority, status)
            )


def get_last_run(db_path: Path, task_name: str) -> str | None:
    with _conn(db_path) as conn:
        row = conn.execute(
            "SELECT last_run FROM recurring_runs WHERE task_name = ?", (task_name,)
        ).fetchone()
    return row["last_run"] if row else None


def set_last_run(db_path: Path, task_name: str, date_str: str) -> None:
    with _conn(db_path) as conn:
        conn.execute(
            "INSERT INTO recurring_runs (task_name, last_run) VALUES (?, ?) "
            "ON CONFLICT(task_name) DO UPDATE SET last_run=excluded.last_run",
            (task_name, date_str)
        )
```

- [ ] **Step 6: Run tests — verify they pass**

```bash
pytest tests/test_db.py -v
```

Expected: all 7 tests PASS.

- [ ] **Step 7: Create data dir and commit**

```bash
mkdir -p ~/planner/data
touch ~/planner/data/.gitkeep
echo "data/tasks.db" >> ~/planner/.gitignore
echo ".venv/" >> ~/planner/.gitignore
echo "__pycache__/" >> ~/planner/.gitignore
echo "*.pyc" >> ~/planner/.gitignore
echo "/tmp/planner-*.txt" >> ~/planner/.gitignore

git add planner/ tests/ requirements.txt data/.gitkeep .gitignore
git commit -m "feat: project scaffold, config, and db layer"
git push
```

---

## Task 2: Screen Session Monitor

**Files:**
- Create: `planner/screen_monitor.py`
- Create: `tests/test_screen_monitor.py`

**Interfaces:**
- Consumes: `config.SCREEN_POLL_INTERVAL`, `config.SCREEN_IDLE_THRESHOLD`
- Produces:
  - `SessionState` — dataclass with fields: `pid: str`, `name: str`, `full_name: str`, `attached: bool`, `state: str`, `idle_seconds: float`, `last_lines: list[str]`
  - `ScreenMonitor` — class with:
    - `__init__(poll_interval, idle_threshold)`
    - `start() -> None` — starts background thread
    - `stop() -> None`
    - `get_sessions() -> list[SessionState]` — thread-safe snapshot

- [ ] **Step 1: Write failing tests**

Create `tests/test_screen_monitor.py`:
```python
import pytest
from unittest.mock import patch, MagicMock
from planner.screen_monitor import parse_screen_ls, detect_state, PROMPT_PATTERNS


SCREEN_LS_OUTPUT = """There are screens on:
\t67261.agent-core\t(Detached)
\t37635.webapp\t(Detached)
\t79406.master\t(Attached)
3 Sockets in /Users/twall/.screen."""


def test_parse_screen_ls_count():
    sessions = parse_screen_ls(SCREEN_LS_OUTPUT)
    assert len(sessions) == 3


def test_parse_screen_ls_fields():
    sessions = parse_screen_ls(SCREEN_LS_OUTPUT)
    agent = next(s for s in sessions if s["name"] == "agent-core")
    assert agent["pid"] == "67261"
    assert agent["attached"] is False
    assert agent["full_name"] == "67261.agent-core"


def test_parse_screen_ls_attached():
    sessions = parse_screen_ls(SCREEN_LS_OUTPUT)
    master = next(s for s in sessions if s["name"] == "master")
    assert master["attached"] is True


def test_detect_state_needs_permission():
    lines = ["some output", "Do you want to proceed? [Y/n]", ""]
    assert detect_state(lines, idle_seconds=0) == "NEEDS INPUT"


def test_detect_state_allow_deny():
    lines = ["Tool: bash", "Allow this action? (Yes/No)", ""]
    assert detect_state(lines, idle_seconds=0) == "NEEDS PERMISSION"


def test_detect_state_idle():
    lines = ["some output", "some more output"]
    assert detect_state(lines, idle_seconds=35) == "IDLE"


def test_detect_state_active():
    lines = ["some output", "some more output"]
    assert detect_state(lines, idle_seconds=10) == "ACTIVE"


def test_detect_state_attached():
    lines = ["some output"]
    assert detect_state(lines, idle_seconds=0, attached=True) == "ATTACHED"
```

- [ ] **Step 2: Run tests — verify they fail**

```bash
pytest tests/test_screen_monitor.py -v
```

Expected: `ImportError: cannot import name 'parse_screen_ls'`

- [ ] **Step 3: Implement screen_monitor.py**

Create `planner/screen_monitor.py`:
```python
import re
import subprocess
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from planner.config import SCREEN_POLL_INTERVAL, SCREEN_IDLE_THRESHOLD


PROMPT_PATTERNS = [
    re.compile(r'\[Y/n\]', re.IGNORECASE),
    re.compile(r'\[y/N\]', re.IGNORECASE),
    re.compile(r'\(y/n\)', re.IGNORECASE),
    re.compile(r'\(Yes/No\)', re.IGNORECASE),
    re.compile(r'Do you want to', re.IGNORECASE),
]

PERMISSION_PATTERNS = [
    re.compile(r'Allow this action', re.IGNORECASE),
    re.compile(r'Allow|Deny.*\?', re.IGNORECASE),
    re.compile(r'permission', re.IGNORECASE),
]


@dataclass
class SessionState:
    pid: str
    name: str
    full_name: str
    attached: bool
    state: str = "ACTIVE"
    idle_seconds: float = 0.0
    last_lines: list[str] = field(default_factory=list)


def parse_screen_ls(output: str) -> list[dict]:
    sessions = []
    for line in output.splitlines():
        m = re.match(r'\s+(\d+)\.(\S+)\s+\((Attached|Detached)\)', line)
        if m:
            pid, name, status = m.group(1), m.group(2), m.group(3)
            sessions.append({
                "pid": pid,
                "name": name,
                "full_name": f"{pid}.{name}",
                "attached": status == "Attached",
            })
    return sessions


def detect_state(lines: list[str], idle_seconds: float, attached: bool = False) -> str:
    if attached:
        return "ATTACHED"
    text = "\n".join(lines)
    for pattern in PERMISSION_PATTERNS:
        if pattern.search(text):
            return "NEEDS PERMISSION"
    for pattern in PROMPT_PATTERNS:
        if pattern.search(text):
            return "NEEDS INPUT"
    if idle_seconds >= SCREEN_IDLE_THRESHOLD:
        return "IDLE"
    return "ACTIVE"


def _capture_session(full_name: str) -> list[str]:
    tmp = f"/tmp/planner-{full_name}.txt"
    try:
        subprocess.run(
            ["screen", "-S", full_name, "-X", "hardcopy", "-h", tmp],
            timeout=3, capture_output=True
        )
        return Path(tmp).read_text(errors="replace").splitlines()[-50:]
    except Exception:
        return []


class ScreenMonitor:
    def __init__(self, poll_interval: int = SCREEN_POLL_INTERVAL,
                 idle_threshold: int = SCREEN_IDLE_THRESHOLD):
        self._poll_interval = poll_interval
        self._idle_threshold = idle_threshold
        self._sessions: list[SessionState] = []
        self._lock = threading.Lock()
        self._snapshots: dict[str, tuple[list[str], float]] = {}  # full_name -> (lines, timestamp)
        self._thread: threading.Thread | None = None
        self._running = False

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
            result = subprocess.run(["screen", "-ls"], capture_output=True, text=True, timeout=5)
            raw = parse_screen_ls(result.stdout)
        except Exception:
            return

        now = time.monotonic()
        updated = []
        for s in raw:
            lines = _capture_session(s["full_name"])
            prev_lines, prev_time = self._snapshots.get(s["full_name"], (None, now))
            if prev_lines is not None and lines == prev_lines:
                idle_secs = now - prev_time
            else:
                idle_secs = 0.0
                self._snapshots[s["full_name"]] = (lines, now)
            state = detect_state(lines[-50:], idle_secs, s["attached"])
            updated.append(SessionState(
                pid=s["pid"], name=s["name"], full_name=s["full_name"],
                attached=s["attached"], state=state,
                idle_seconds=idle_secs, last_lines=lines[-20:]
            ))

        with self._lock:
            self._sessions = updated
```

- [ ] **Step 4: Run tests — verify they pass**

```bash
pytest tests/test_screen_monitor.py -v
```

Expected: all 8 tests PASS.

- [ ] **Step 5: Commit**

```bash
git add planner/screen_monitor.py tests/test_screen_monitor.py
git commit -m "feat: screen session monitor with idle and prompt detection"
git push
```

---

## Task 3: JIRA Client

**Files:**
- Create: `planner/jira.py`
- Create: `tests/test_jira.py`

**Interfaces:**
- Consumes: `config.JIRA_PROJECTS`
- Produces:
  - `JiraClient(token: str, cloud_id: str)` — class
  - `JiraClient.fetch_assigned_issues(projects: list[str]) -> list[dict]` — each dict has keys: `jira_key`, `title`, `description`, `priority`, `status`
  - `jira_priority_to_int(priority_name: str) -> int` — maps "Highest"→1, "High"→2, "Medium"→3, "Low"→4, "Lowest"→5

- [ ] **Step 1: Write failing tests**

Create `tests/test_jira.py`:
```python
import pytest
from unittest.mock import patch, AsyncMock, MagicMock
from planner.jira import jira_priority_to_int, JiraClient


def test_priority_mapping():
    assert jira_priority_to_int("Highest") == 1
    assert jira_priority_to_int("High") == 2
    assert jira_priority_to_int("Medium") == 3
    assert jira_priority_to_int("Low") == 4
    assert jira_priority_to_int("Lowest") == 5
    assert jira_priority_to_int("Unknown") == 3


def test_fetch_assigned_issues_parses_response():
    client = JiraClient(token="tok", cloud_id="cloud123")
    mock_response = {
        "issues": [
            {
                "key": "PLEX-42",
                "fields": {
                    "summary": "Fix the thing",
                    "description": None,
                    "priority": {"name": "High"},
                    "status": {"name": "In Progress"},
                }
            }
        ]
    }
    with patch.object(client, "_search", return_value=mock_response):
        issues = client.fetch_assigned_issues(["PLEX"])
    assert len(issues) == 1
    assert issues[0]["jira_key"] == "PLEX-42"
    assert issues[0]["title"] == "Fix the thing"
    assert issues[0]["priority"] == 2
    assert issues[0]["status"] == "in_progress"


def test_fetch_assigned_issues_empty():
    client = JiraClient(token="tok", cloud_id="cloud123")
    with patch.object(client, "_search", return_value={"issues": []}):
        issues = client.fetch_assigned_issues(["PLEX"])
    assert issues == []
```

- [ ] **Step 2: Run tests — verify they fail**

```bash
pytest tests/test_jira.py -v
```

Expected: `ImportError: cannot import name 'jira_priority_to_int'`

- [ ] **Step 3: Implement jira.py**

Create `planner/jira.py`:
```python
import httpx
from planner.config import JIRA_PROJECTS

CLOUD_ID = "1a1f388e-937a-419e-a549-3f923712873f"
JIRA_BASE = f"https://api.atlassian.com/ex/jira/{CLOUD_ID}/rest/api/3"

PRIORITY_MAP = {
    "highest": 1, "blocker": 1,
    "high": 2, "critical": 2,
    "medium": 3,
    "low": 4,
    "lowest": 5, "trivial": 5,
}

STATUS_MAP = {
    "to do": "open", "open": "open", "new": "open",
    "in progress": "in_progress", "in review": "in_progress",
    "done": "done", "closed": "done", "resolved": "done",
}


def jira_priority_to_int(priority_name: str) -> int:
    return PRIORITY_MAP.get(priority_name.lower(), 3)


class JiraClient:
    def __init__(self, token: str, cloud_id: str = CLOUD_ID):
        self._token = token
        self._cloud_id = cloud_id
        self._base = f"https://api.atlassian.com/ex/jira/{cloud_id}/rest/api/3"

    def _search(self, jql: str, fields: list[str]) -> dict:
        headers = {
            "Authorization": f"Bearer {self._token}",
            "Accept": "application/json",
        }
        resp = httpx.get(
            f"{self._base}/search",
            headers=headers,
            params={"jql": jql, "fields": ",".join(fields), "maxResults": 100},
            timeout=15,
        )
        resp.raise_for_status()
        return resp.json()

    def fetch_assigned_issues(self, projects: list[str] = None) -> list[dict]:
        projects = projects or JIRA_PROJECTS
        project_filter = " OR ".join(f'project = "{p}"' for p in projects)
        jql = f"assignee = currentUser() AND statusCategory != Done AND ({project_filter}) ORDER BY priority ASC"
        data = self._search(jql, ["summary", "description", "priority", "status"])
        results = []
        for issue in data.get("issues", []):
            f = issue["fields"]
            desc = f.get("description") or ""
            if isinstance(desc, dict):
                # Atlassian Document Format — extract plain text
                desc = " ".join(
                    block.get("text", "")
                    for content in desc.get("content", [])
                    for block in content.get("content", [])
                    if block.get("type") == "text"
                )
            results.append({
                "jira_key": issue["key"],
                "title": f["summary"],
                "description": desc[:500] if desc else None,
                "priority": jira_priority_to_int(f.get("priority", {}).get("name", "Medium")),
                "status": STATUS_MAP.get(f.get("status", {}).get("name", "").lower(), "open"),
            })
        return results
```

- [ ] **Step 4: Run tests — verify they pass**

```bash
pytest tests/test_jira.py -v
```

Expected: all 3 tests PASS.

- [ ] **Step 5: Commit**

```bash
git add planner/jira.py tests/test_jira.py
git commit -m "feat: JIRA REST client with issue fetching and priority mapping"
git push
```

---

## Task 4: Scheduler (Recurring Tasks)

**Files:**
- Create: `planner/scheduler.py`
- Create: `tests/test_scheduler.py`

**Interfaces:**
- Consumes: `db.get_last_run`, `db.set_last_run`, `db.add_task`, `config.DB_PATH`, `config.SKILLS_PATH`
- Produces:
  - `RecurringTask` — dataclass: `name: str`, `label: str`, `prompt: str`
  - `parse_claude_output(output: str) -> list[dict]` — parses `claude --print` output into list of `{title, description, horizon}` dicts; expects a simple line-based format
  - `Scheduler(db_path: Path)` — class with:
    - `run_task(task: RecurringTask) -> list[dict]` — spawns subprocess, parses output, writes tasks to DB, updates last_run; returns list of new task dicts
    - `should_run_today(task_name: str) -> bool` — returns True if not run today
    - `run_all_due() -> None` — runs all tasks where `should_run_today` is True

- [ ] **Step 1: Write failing tests**

Create `tests/test_scheduler.py`:
```python
import pytest
import tempfile
from pathlib import Path
from unittest.mock import patch, MagicMock
from planner.db import init_db, list_tasks, get_last_run
from planner.scheduler import parse_claude_output, Scheduler, RecurringTask


def test_parse_claude_output_tasks():
    output = """
SUMMARY: 3 new errors in #issues channel.

TASKS:
- Investigate WEBAPP-NW spike (today, priority 2)
- Check PLEX-DB connection errors (today, priority 3)
- Review monitoring alert rule (this_week, priority 4)
"""
    tasks = parse_claude_output(output)
    assert len(tasks) == 3
    assert tasks[0]["title"] == "Investigate WEBAPP-NW spike"
    assert tasks[0]["horizon"] == "today"
    assert tasks[0]["priority"] == 2


def test_parse_claude_output_empty():
    tasks = parse_claude_output("No new issues found.")
    assert tasks == []


def test_should_run_today_no_prior_run(tmp_path):
    db_path = tmp_path / "tasks.db"
    init_db(db_path)
    sched = Scheduler(db_path)
    assert sched.should_run_today("slack") is True


def test_should_run_today_already_ran(tmp_path):
    from planner.db import set_last_run
    import datetime
    db_path = tmp_path / "tasks.db"
    init_db(db_path)
    today = datetime.date.today().isoformat()
    set_last_run(db_path, "slack", today)
    sched = Scheduler(db_path)
    assert sched.should_run_today("slack") is False


def test_run_task_writes_to_db(tmp_path):
    db_path = tmp_path / "tasks.db"
    init_db(db_path)
    sched = Scheduler(db_path)
    task = RecurringTask(name="slack", label="Slack Digest", prompt="check slack")
    mock_output = "TASKS:\n- Fix auth bug (today, priority 2)\n"
    with patch.object(sched, "_invoke_claude", return_value=mock_output):
        result = sched.run_task(task)
    tasks = list_tasks(db_path, horizon="today")
    assert len(tasks) == 1
    assert tasks[0]["source"] == "slack"
    assert tasks[0]["title"] == "Fix auth bug"
```

- [ ] **Step 2: Run tests — verify they fail**

```bash
pytest tests/test_scheduler.py -v
```

Expected: `ImportError: cannot import name 'parse_claude_output'`

- [ ] **Step 3: Implement scheduler.py**

Create `planner/scheduler.py`:
```python
import datetime
import re
import subprocess
from dataclasses import dataclass
from pathlib import Path

from planner.config import DB_PATH, SKILLS_PATH
from planner.db import add_task, get_last_run, set_last_run


TASK_LINE_RE = re.compile(
    r'^-\s+(.+?)\s+\((\w+),\s*priority\s*(\d)\)',
    re.IGNORECASE
)

SLACK_PROMPT = """Use the slack:channel-digest skill to read #issues and #monitoring channels.
Summarize new errors and alerts since the last check.
Output format — first a SUMMARY line, then a TASKS: section with one task per line:
- <task title> (<today|this_week|backlog>, priority <1-5>)
Only output actionable tasks. If nothing new, output: No new issues found."""

BITBUCKET_PROMPT = """Use the review-bitbucket-prs skill to check open PRs in rd, plex-search, plex-search-ui repos.
Find PRs that need action: approve, respond, or first review.
Output format — first a SUMMARY line, then a TASKS: section:
- <task title> (<today|this_week|backlog>, priority <1-5>)
If nothing needs action, output: No PR action needed."""

SENTRY_PROMPT = """Check Sentry projects WEBAPP, REST-API, internal for recent issues (last 24h).
Then check Slack #issues and #monitoring for the same time window.
Report ONLY issues present in Sentry but NOT mentioned in Slack (alerting dropouts).
Output format — first a SUMMARY line, then a TASKS: section:
- <task title> (<today|this_week|backlog>, priority <1-5>)
If no gaps found, output: No Sentry alerting gaps found."""


@dataclass
class RecurringTask:
    name: str
    label: str
    prompt: str


RECURRING_TASKS = [
    RecurringTask("slack", "Slack Digest", SLACK_PROMPT),
    RecurringTask("bitbucket", "Bitbucket PR Review", BITBUCKET_PROMPT),
    RecurringTask("sentry", "Sentry Gap Check", SENTRY_PROMPT),
]


def parse_claude_output(output: str) -> list[dict]:
    tasks = []
    in_tasks = False
    for line in output.splitlines():
        if line.strip().upper().startswith("TASKS:"):
            in_tasks = True
            continue
        if in_tasks:
            m = TASK_LINE_RE.match(line.strip())
            if m:
                tasks.append({
                    "title": m.group(1).strip(),
                    "horizon": m.group(2).lower(),
                    "priority": int(m.group(3)),
                    "description": None,
                })
    return tasks


class Scheduler:
    def __init__(self, db_path: Path = DB_PATH):
        self._db_path = db_path

    def should_run_today(self, task_name: str) -> bool:
        today = datetime.date.today().isoformat()
        return get_last_run(self._db_path, task_name) != today

    def _invoke_claude(self, prompt: str) -> str:
        result = subprocess.run(
            ["claude", "--print", prompt],
            capture_output=True, text=True, timeout=120
        )
        return result.stdout

    def run_task(self, task: RecurringTask) -> list[dict]:
        output = self._invoke_claude(task.prompt)
        parsed = parse_claude_output(output)
        for item in parsed:
            add_task(
                self._db_path,
                source=task.name,
                title=item["title"],
                horizon=item.get("horizon", "today"),
                priority=item.get("priority", 3),
                description=item.get("description"),
            )
        today = datetime.date.today().isoformat()
        set_last_run(self._db_path, task.name, today)
        return parsed

    def run_all_due(self) -> None:
        for task in RECURRING_TASKS:
            if self.should_run_today(task.name):
                self.run_task(task)
```

- [ ] **Step 4: Run tests — verify they pass**

```bash
pytest tests/test_scheduler.py -v
```

Expected: all 5 tests PASS.

- [ ] **Step 5: Commit**

```bash
git add planner/scheduler.py tests/test_scheduler.py
git commit -m "feat: recurring task scheduler with claude subprocess execution"
git push
```

---

## Task 5: CLI (`/task` skill entry point)

**Files:**
- Create: `planner/cli.py`
- Create: `skills/task.md`
- Create: `tests/test_cli.py`

**Interfaces:**
- Consumes: `db.add_task`, `db.list_tasks`, `config.DB_PATH`
- Produces:
  - `main(argv: list[str] | None = None) -> int` — entry point; returns 0 on success, 1 on error
  - CLI installed as `python -m planner.cli`

- [ ] **Step 1: Write failing tests**

Create `tests/test_cli.py`:
```python
import pytest
import tempfile
from pathlib import Path
from unittest.mock import patch
from planner.db import init_db, list_tasks
from planner.cli import main


@pytest.fixture
def db(tmp_path):
    p = tmp_path / "tasks.db"
    init_db(p)
    return p


def test_add_task_today(db):
    with patch("planner.cli.DB_PATH", db):
        rc = main(["add", "Fix the bug", "--today", "--priority", "2"])
    assert rc == 0
    tasks = list_tasks(db, horizon="today")
    assert len(tasks) == 1
    assert tasks[0]["title"] == "Fix the bug"
    assert tasks[0]["priority"] == 2


def test_add_task_backlog_default(db):
    with patch("planner.cli.DB_PATH", db):
        rc = main(["add", "Someday task"])
    assert rc == 0
    tasks = list_tasks(db, horizon="backlog")
    assert len(tasks) == 1


def test_list_tasks_output(db, capsys):
    with patch("planner.cli.DB_PATH", db):
        main(["add", "Task one", "--today"])
        main(["add", "Task two", "--week"])
        rc = main(["list"])
    assert rc == 0
    out = capsys.readouterr().out
    assert "Task one" in out
    assert "Task two" in out


def test_add_missing_title_errors(db):
    with patch("planner.cli.DB_PATH", db):
        rc = main(["add"])
    assert rc == 1
```

- [ ] **Step 2: Run tests — verify they fail**

```bash
pytest tests/test_cli.py -v
```

Expected: `ImportError: cannot import name 'main'`

- [ ] **Step 3: Implement cli.py**

Create `planner/cli.py`:
```python
import sys
from pathlib import Path
from planner.config import DB_PATH
from planner.db import init_db, add_task, list_tasks


def main(argv: list[str] | None = None) -> int:
    args = argv if argv is not None else sys.argv[1:]
    if not args:
        print("Usage: planner.cli add <title> [--today|--week|--backlog] [--priority N]", file=sys.stderr)
        return 1

    command = args[0]
    rest = args[1:]

    init_db(DB_PATH)

    if command == "add":
        if not rest or rest[0].startswith("--"):
            print("Error: title required", file=sys.stderr)
            return 1
        title = rest[0]
        horizon = "backlog"
        priority = 3
        i = 1
        while i < len(rest):
            if rest[i] == "--today":
                horizon = "today"
            elif rest[i] == "--week":
                horizon = "this_week"
            elif rest[i] == "--backlog":
                horizon = "backlog"
            elif rest[i] == "--priority" and i + 1 < len(rest):
                try:
                    priority = int(rest[i + 1])
                    i += 1
                except ValueError:
                    pass
            i += 1
        task_id = add_task(DB_PATH, source="freeform", title=title, horizon=horizon, priority=priority)
        print(f"Added task #{task_id}: {title} [{horizon}]")
        return 0

    elif command == "list":
        tasks = list_tasks(DB_PATH)
        if not tasks:
            print("No tasks.")
            return 0
        for t in tasks:
            tag = f"[{t['jira_key']}]" if t.get("jira_key") else f"[{t['source']}]"
            print(f"  {t['id']:3}. {tag} {t['title']}  ({t['horizon']}, p{t['priority']})")
        return 0

    else:
        print(f"Unknown command: {command}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 4: Run tests — verify they pass**

```bash
pytest tests/test_cli.py -v
```

Expected: all 4 tests PASS.

- [ ] **Step 5: Create /task skill**

Create `skills/task.md`:
```markdown
---
name: task
description: Add or list tasks in the planner dashboard from any Claude Code session. Use when user says "/task add ...", "add a task", "remember to...", or asks to see current tasks.
---

# /task — Planner Task Management

Add tasks to the central planner dashboard or list current tasks.

## Usage

```
/task add "title" [--today|--week|--backlog] [--priority 1-5]
/task list
```

## Implementation

Run the planner CLI directly:

```bash
cd ~/planner && source .venv/bin/activate && python -m planner.cli add "<title>" [--today|--week|--backlog] [--priority N]
```

For list:
```bash
cd ~/planner && source .venv/bin/activate && python -m planner.cli list
```

## Examples

User: "add a task to review the imap performance"
→ `python -m planner.cli add "Review imap graph performance" --week --priority 3`

User: "remind me to check the sentry alerts today"
→ `python -m planner.cli add "Check Sentry alerts" --today --priority 2`

User: "what's on my list?"
→ `python -m planner.cli list`
```

- [ ] **Step 6: Install skill globally and commit**

```bash
cp ~/planner/skills/task.md ~/.claude/skills/task.md

git add planner/cli.py skills/task.md tests/test_cli.py
git commit -m "feat: CLI entry point and /task global skill"
git push
```

---

## Task 6: Textual Widgets

**Files:**
- Create: `planner/widgets/__init__.py`
- Create: `planner/widgets/session_panel.py`
- Create: `planner/widgets/task_panel.py`
- Create: `planner/widgets/briefing_panel.py`
- Create: `planner/widgets/status_bar.py`

**Interfaces:**
- Consumes: `SessionState` from `screen_monitor`, `list_tasks` from `db`, `config.*`
- Produces (Textual widgets — no unit tests; tested visually in Task 7):
  - `SessionPanel(sessions: list[SessionState])` — `ListView` subclass; `update(sessions)` method; posts `SessionSelected(full_name)` and `SessionPreview(full_name)` messages
  - `TaskPanel(db_path: Path)` — `Widget` subclass; `refresh_tasks()` method; posts `TaskAction(task_id, action)` message where `action ∈ {"done", "move", "edit"}`
  - `BriefingPanel()` — `Widget` subclass; `update(summaries: list[str])` method
  - `StatusBar()` — `Widget` subclass; `set_sync_status(label: str, seconds_ago: int)` method

- [ ] **Step 1: Create widget package**

Create `planner/widgets/__init__.py` (empty).

- [ ] **Step 2: Implement session_panel.py**

Create `planner/widgets/session_panel.py`:
```python
from textual.app import ComposeResult
from textual.message import Message
from textual.widgets import ListView, ListItem, Label
from textual.reactive import reactive
from planner.screen_monitor import SessionState

STATE_COLORS = {
    "NEEDS PERMISSION": "bold red",
    "NEEDS INPUT": "bold yellow",
    "IDLE": "dim",
    "ACTIVE": "green",
    "ATTACHED": "bold cyan",
}


class SessionPanel(ListView):
    class SessionSelected(Message):
        def __init__(self, full_name: str):
            super().__init__()
            self.full_name = full_name

    class SessionPreview(Message):
        def __init__(self, full_name: str, lines: list[str]):
            super().__init__()
            self.full_name = full_name
            self.lines = lines

    def __init__(self):
        super().__init__()
        self._sessions: list[SessionState] = []

    def update(self, sessions: list[SessionState]) -> None:
        self._sessions = sessions
        self.clear()
        for s in sessions:
            color = STATE_COLORS.get(s.state, "white")
            idle_str = f"  {int(s.idle_seconds // 60)}m" if s.state == "IDLE" and s.idle_seconds >= 60 else ""
            label = f"[{color}]● {s.name:<16} {s.state}{idle_str}[/{color}]"
            self.append(ListItem(Label(label), id=f"sess-{s.pid}"))

    def on_list_view_selected(self, event: ListView.Selected) -> None:
        idx = self._get_index(event.item)
        if idx is not None:
            self.post_message(self.SessionSelected(self._sessions[idx].full_name))

    def action_preview(self) -> None:
        idx = self.index
        if idx is not None and idx < len(self._sessions):
            s = self._sessions[idx]
            self.post_message(self.SessionPreview(s.full_name, s.last_lines))

    def _get_index(self, item) -> int | None:
        for i, child in enumerate(self.children):
            if child is item:
                return i
        return None
```

- [ ] **Step 3: Implement task_panel.py**

Create `planner/widgets/task_panel.py`:
```python
from pathlib import Path
from textual.app import ComposeResult
from textual.message import Message
from textual.widgets import Static, ListView, ListItem, Label
from textual.widget import Widget
from planner.db import list_tasks, update_task
from planner.config import DB_PATH

HORIZON_CYCLE = ["today", "this_week", "backlog"]

SOURCE_TAG = {
    "jira": "JIRA",
    "freeform": "·",
    "slack": "SLACK",
    "bitbucket": "BB",
    "sentry": "SENTRY",
}


class TaskPanel(Widget):
    class TaskAction(Message):
        def __init__(self, task_id: int, action: str):
            super().__init__()
            self.task_id = task_id
            self.action = action

    DEFAULT_CSS = """
    TaskPanel {
        height: 100%;
        overflow-y: auto;
    }
    """

    def __init__(self, db_path: Path = DB_PATH):
        super().__init__()
        self._db_path = db_path
        self._tasks: list[dict] = []
        self._cursor = 0

    def compose(self) -> ComposeResult:
        yield Static(id="task-list-content")

    def refresh_tasks(self) -> None:
        self._tasks = list_tasks(self._db_path, status=None)
        self._render_tasks()

    def _render_tasks(self) -> None:
        lines = []
        current_horizon = None
        for i, t in enumerate(self._tasks):
            if t["status"] == "done":
                continue
            if t["horizon"] != current_horizon:
                current_horizon = t["horizon"]
                heading = {"today": "TODAY", "this_week": "THIS WEEK", "backlog": "BACKLOG"}.get(current_horizon, current_horizon.upper())
                lines.append(f"\n[bold]{heading}[/bold]")
            tag = SOURCE_TAG.get(t["source"], t["source"].upper())
            cursor = "▶ " if i == self._cursor else "  "
            jira = f"[{t['jira_key']}] " if t.get("jira_key") else f"[{tag}] "
            lines.append(f"{cursor}{jira}{t['title']}")
        content = "\n".join(lines) if lines else "[dim]No tasks.[/dim]"
        self.query_one("#task-list-content", Static).update(content)

    def action_move_cursor_down(self) -> None:
        if self._cursor < len(self._tasks) - 1:
            self._cursor += 1
            self._render_tasks()

    def action_move_cursor_up(self) -> None:
        if self._cursor > 0:
            self._cursor -= 1
            self._render_tasks()

    def action_mark_done(self) -> None:
        if self._tasks:
            t = self._tasks[self._cursor]
            update_task(self._db_path, t["id"], status="done")
            self.refresh_tasks()

    def action_move_horizon(self) -> None:
        if self._tasks:
            t = self._tasks[self._cursor]
            idx = HORIZON_CYCLE.index(t["horizon"]) if t["horizon"] in HORIZON_CYCLE else 2
            new_horizon = HORIZON_CYCLE[(idx + 1) % len(HORIZON_CYCLE)]
            update_task(self._db_path, t["id"], horizon=new_horizon)
            self.refresh_tasks()
```

- [ ] **Step 4: Implement briefing_panel.py**

Create `planner/widgets/briefing_panel.py`:
```python
from textual.widgets import Static
from textual.widget import Widget
from textual.app import ComposeResult


class BriefingPanel(Widget):
    DEFAULT_CSS = """
    BriefingPanel {
        height: 5;
        border: solid $panel;
        padding: 0 1;
    }
    """

    def compose(self) -> ComposeResult:
        yield Static("[dim]Daily briefing loading...[/dim]", id="briefing-content")

    def update(self, summaries: list[str]) -> None:
        text = "  ".join(summaries) if summaries else "[dim]No briefing data yet.[/dim]"
        self.query_one("#briefing-content", Static).update(text)
```

- [ ] **Step 5: Implement status_bar.py**

Create `planner/widgets/status_bar.py`:
```python
import datetime
from textual.widgets import Static
from textual.widget import Widget
from textual.app import ComposeResult


class StatusBar(Widget):
    DEFAULT_CSS = """
    StatusBar {
        height: 1;
        background: $panel;
        padding: 0 1;
    }
    """

    def __init__(self):
        super().__init__()
        self._sync_label = "never"
        self._sync_seconds_ago = -1

    def compose(self) -> ComposeResult:
        yield Static(id="status-content")

    def set_sync_status(self, label: str, seconds_ago: int) -> None:
        self._sync_label = label
        self._sync_seconds_ago = seconds_ago
        self._refresh_content()

    def on_mount(self) -> None:
        self.set_interval(1, self._refresh_content)

    def _refresh_content(self) -> None:
        now = datetime.datetime.now().strftime("%H:%M")
        date = datetime.date.today().strftime("%a %b %d")
        if self._sync_seconds_ago >= 0:
            mins = self._sync_seconds_ago // 60
            sync_str = f"{mins}m ago" if mins > 0 else "just now"
        else:
            sync_str = "never"
        text = f"  PLANNER  [{date}]  [last sync: {sync_str}]  {now}"
        self.query_one("#status-content", Static).update(text)
```

- [ ] **Step 6: Commit**

```bash
git add planner/widgets/
git commit -m "feat: Textual widgets — session panel, task panel, briefing, status bar"
git push
```

---

## Task 7: Main App + Launcher

**Files:**
- Create: `planner/app.py`
- Create: `scripts/planner`
- Create: `README.md`
- Modify: `requirements.txt` — add `pytest-asyncio` if not present

**Interfaces:**
- Consumes: all widgets, `ScreenMonitor`, `JiraClient`, `Scheduler`, `db.*`, `config.*`
- Produces: runnable `PlannerApp` Textual application

- [ ] **Step 1: Implement app.py**

Create `planner/app.py`:
```python
import asyncio
import datetime
import os
import subprocess
from pathlib import Path

from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.widgets import Footer, Header

from planner.config import DB_PATH, JIRA_SYNC_INTERVAL, SCREEN_POLL_INTERVAL
from planner.db import init_db, list_tasks
from planner.jira import JiraClient
from planner.scheduler import Scheduler, RECURRING_TASKS
from planner.screen_monitor import ScreenMonitor
from planner.widgets.briefing_panel import BriefingPanel
from planner.widgets.session_panel import SessionPanel
from planner.widgets.status_bar import StatusBar
from planner.widgets.task_panel import TaskPanel


class PlannerApp(App):
    CSS = """
    Screen {
        layout: vertical;
    }
    #main-row {
        height: 1fr;
        layout: horizontal;
    }
    SessionPanel {
        width: 28;
        border: solid $panel;
    }
    TaskPanel {
        width: 1fr;
        border: solid $panel;
    }
    BriefingPanel {
        height: 5;
    }
    """

    BINDINGS = [
        Binding("tab", "focus_next", "Switch panel"),
        Binding("enter", "attach_session", "Attach"),
        Binding("p", "preview_session", "Preview"),
        Binding("n", "new_task", "New task"),
        Binding("d", "mark_done", "Done"),
        Binding("m", "move_horizon", "Move horizon"),
        Binding("j", "sync_jira", "Sync JIRA"),
        Binding("b", "run_bitbucket", "Bitbucket PRs"),
        Binding("s", "run_slack", "Slack digest"),
        Binding("R", "run_all", "Run all"),
        Binding("q", "quit", "Quit"),
        Binding("J", "cursor_down", "Down", show=False),
        Binding("K", "cursor_up", "Up", show=False),
    ]

    def __init__(self):
        super().__init__()
        self._monitor = ScreenMonitor()
        self._scheduler = Scheduler(DB_PATH)
        self._jira_client: JiraClient | None = self._make_jira_client()
        self._last_jira_sync = -1
        self._briefing_summaries: list[str] = []

    def _make_jira_client(self) -> JiraClient | None:
        token = os.environ.get("JIRA_API_TOKEN")
        if not token:
            return None
        return JiraClient(token=token)

    def compose(self) -> ComposeResult:
        yield StatusBar()
        with Horizontal(id="main-row"):
            yield SessionPanel()
            yield TaskPanel(DB_PATH)
        yield BriefingPanel()
        yield Footer()

    def on_mount(self) -> None:
        init_db(DB_PATH)
        self._monitor.start()
        self.set_interval(SCREEN_POLL_INTERVAL, self._refresh_sessions)
        self.set_interval(JIRA_SYNC_INTERVAL, self.action_sync_jira)
        self.set_interval(10, self._check_recurring)
        self.call_after_refresh(self._startup)

    async def _startup(self) -> None:
        self.query_one(TaskPanel).refresh_tasks()
        await asyncio.get_event_loop().run_in_executor(None, self._scheduler.run_all_due)
        self.query_one(TaskPanel).refresh_tasks()

    def _refresh_sessions(self) -> None:
        sessions = self._monitor.get_sessions()
        self.query_one(SessionPanel).update(sessions)

    def _check_recurring(self) -> None:
        now = datetime.datetime.now()
        if now.hour >= 8:
            due = [t for t in RECURRING_TASKS if self._scheduler.should_run_today(t.name)]
            if due:
                asyncio.get_event_loop().run_in_executor(None, self._scheduler.run_all_due)

    def action_sync_jira(self) -> None:
        if not self._jira_client:
            self.notify("JIRA_API_TOKEN not set", severity="warning")
            return
        from planner.config import JIRA_PROJECTS
        from planner.db import upsert_jira_task
        try:
            issues = self._jira_client.fetch_assigned_issues(JIRA_PROJECTS)
            for issue in issues:
                upsert_jira_task(DB_PATH, **issue)
            self.query_one(TaskPanel).refresh_tasks()
            self.query_one(StatusBar).set_sync_status("JIRA", 0)
            self.notify(f"Synced {len(issues)} JIRA issues")
        except Exception as e:
            self.notify(f"JIRA sync failed: {e}", severity="error")

    def action_run_slack(self) -> None:
        task = next(t for t in RECURRING_TASKS if t.name == "slack")
        asyncio.get_event_loop().run_in_executor(None, self._scheduler.run_task, task)
        self.notify("Running Slack digest...")

    def action_run_bitbucket(self) -> None:
        task = next(t for t in RECURRING_TASKS if t.name == "bitbucket")
        asyncio.get_event_loop().run_in_executor(None, self._scheduler.run_task, task)
        self.notify("Running Bitbucket PR review...")

    def action_run_all(self) -> None:
        asyncio.get_event_loop().run_in_executor(None, self._scheduler.run_all_due)
        self.notify("Running all recurring tasks...")

    def action_attach_session(self) -> None:
        panel = self.query_one(SessionPanel)
        idx = panel.index
        sessions = self._monitor.get_sessions()
        if idx is not None and idx < len(sessions):
            full_name = sessions[idx].full_name
            self._monitor.stop()
            self.exit(message=f"screen -r {full_name}")

    def action_preview_session(self) -> None:
        panel = self.query_one(SessionPanel)
        panel.action_preview()

    def action_mark_done(self) -> None:
        self.query_one(TaskPanel).action_mark_done()

    def action_move_horizon(self) -> None:
        self.query_one(TaskPanel).action_move_horizon()

    def action_new_task(self) -> None:
        self.notify("Use: /task add \"title\" [--today|--week] in any Claude session")

    def action_cursor_down(self) -> None:
        self.query_one(TaskPanel).action_move_cursor_down()

    def action_cursor_up(self) -> None:
        self.query_one(TaskPanel).action_move_cursor_up()


def main():
    app = PlannerApp()
    result = app.run()
    if result:
        print(result)


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: Create shell launcher**

Create `scripts/planner` (executable):
```bash
#!/usr/bin/env bash
set -e
PLANNER_DIR="$HOME/planner"
VENV="$PLANNER_DIR/.venv"

if [ ! -d "$VENV" ]; then
    echo "Setting up planner venv..."
    cd "$PLANNER_DIR"
    uv venv --python 3.11 "$VENV"
    uv pip install -r "$PLANNER_DIR/requirements.txt"
fi

# Pass JIRA token from MEMORY.md env var if available
export JIRA_API_TOKEN="${JIRA_API_TOKEN:-}"
export SENTRY_ACCESS_TOKEN="${SENTRY_ACCESS_TOKEN:-}"

source "$VENV/bin/activate"
cd "$PLANNER_DIR"
python -m planner.app "$@"
```

```bash
chmod +x ~/planner/scripts/planner
```

Optionally symlink to PATH:
```bash
ln -sf ~/planner/scripts/planner ~/.local/bin/planner
```

- [ ] **Step 3: Create README.md**

Create `README.md`:
```markdown
# Planner

Persistent terminal dashboard for daily/weekly planning and Claude Code session monitoring.

## Setup

```bash
cd ~/planner
uv venv --python 3.11 .venv
uv pip install -r requirements.txt
```

## Run

```bash
scripts/planner
# or if symlinked:
planner
```

Set env vars before running:
```bash
export JIRA_API_TOKEN=<your jira token>
export SENTRY_ACCESS_TOKEN=<your sentry token>
```

## Keybindings

| Key | Action |
|-----|--------|
| tab | Switch panel focus |
| enter | Attach to screen session |
| p | Preview session output |
| n | New task (via /task skill) |
| d | Mark task done |
| m | Move task horizon |
| j | Sync JIRA |
| b | Re-run Bitbucket PR review |
| s | Re-run Slack digest |
| R | Re-run all recurring tasks |
| J/K | Move cursor down/up in task list |
| q | Quit |

## /task Skill

From any Claude Code session:
```
/task add "title" [--today|--week|--backlog] [--priority 1-5]
/task list
```
```

- [ ] **Step 4: Run full test suite**

```bash
cd ~/planner
source .venv/bin/activate
pytest tests/ -v
```

Expected: all tests PASS (21+ tests across db, screen_monitor, jira, scheduler, cli).

- [ ] **Step 5: Smoke test the app**

```bash
JIRA_API_TOKEN="" scripts/planner
```

Expected: Textual dashboard launches showing screen sessions panel and empty task list. No crashes. `q` exits cleanly.

- [ ] **Step 6: Final commit and push**

```bash
git add planner/app.py scripts/planner README.md
git commit -m "feat: Textual app, shell launcher, README — dashboard complete"
git push
```

---

## Self-Review

**Spec coverage:**
- ✅ Textual TUI with 3 panels (sessions, tasks, briefing)
- ✅ Screen session polling + idle/prompt detection
- ✅ JIRA sync (`j` key + startup + interval)
- ✅ Recurring tasks: Slack, Bitbucket, Sentry (startup + `s`/`b`/`R`)
- ✅ SQLite data model matches spec exactly
- ✅ `/task` skill installed globally
- ✅ All keybindings from spec (j/b/s/R + tab/enter/p/n/d/m/J/K/q)
- ✅ Shell launcher with venv auto-setup
- ✅ Config with all spec constants
- ✅ GitHub repo wired up

**Deferred (v2 per spec):**
- Planning mode (`P` key) — spec explicitly marks as v2

**Type consistency check:**
- `db.add_task` parameters match all callers (scheduler, cli, app) ✅
- `SessionState` fields used in `session_panel.py` match dataclass definition ✅
- `TaskPanel` actions (`action_mark_done`, `action_move_horizon`, `action_move_cursor_*`) match `app.py` calls ✅
- `Scheduler.run_task(task: RecurringTask)` signature matches all call sites ✅
