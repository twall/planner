import pytest
from unittest.mock import patch
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
