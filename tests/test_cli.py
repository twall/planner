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
