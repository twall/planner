import pytest
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
