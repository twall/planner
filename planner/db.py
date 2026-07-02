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
    horizon         TEXT DEFAULT 'today',
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
        for col, typedef in [
            ("claude_session_id", "TEXT"),
            ("session_pid", "TEXT"),
            ("cwd", "TEXT"),
            ("disposable", "INTEGER DEFAULT 0"),
            ("is_prompt", "INTEGER DEFAULT 1"),
            ("rt_frequency", "TEXT"),
            ("rt_time", "TEXT"),
            ("rt_days", "TEXT"),
            ("rt_day", "TEXT"),
            ("rt_interval_hours", "REAL"),
        ]:
            try:
                conn.execute(f"ALTER TABLE tasks ADD COLUMN {col} {typedef}")
                conn.commit()
            except Exception:
                pass


def add_task(db_path: Path, source: str, title: str, horizon: str = "today",
             priority: int = 3, description: str = None, jira_key: str = None,
             screen_session: str = None, cwd: str = None, disposable: bool = False,
             is_prompt: bool = True) -> int:
    with _conn(db_path) as conn:
        cur = conn.execute(
            "INSERT INTO tasks (source, title, horizon, priority, description, jira_key, screen_session, cwd, disposable, is_prompt) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (source, title, horizon, priority, description, jira_key, screen_session, cwd, int(disposable), int(is_prompt))
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
    horizon_order = "CASE horizon WHEN 'today' THEN 0 WHEN 'this_week' THEN 1 ELSE 2 END"
    with _conn(db_path) as conn:
        rows = conn.execute(
            f"SELECT * FROM tasks {where} ORDER BY {horizon_order}, priority ASC, created_at ASC",
            params
        ).fetchall()
    return [dict(r) for r in rows]


def update_task(db_path: Path, task_id: int, **fields) -> None:
    allowed = {"title", "description", "priority", "horizon", "status",
               "screen_session", "claude_session_id", "session_pid", "cwd", "disposable", "is_prompt",
               "rt_frequency", "rt_time", "rt_days", "rt_day", "rt_interval_hours"}
    updates = {k: v for k, v in fields.items() if k in allowed}
    if not updates:
        return
    set_clause = ", ".join(f"{k} = ?" for k in updates)
    set_clause += ", updated_at = datetime('now')"
    values = [v for k, v in updates.items()]
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
