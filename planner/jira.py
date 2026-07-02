import httpx

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
    def __init__(self, token: str, cloud_id: str):
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

    def fetch_assigned_issues(self, projects: list[str]) -> list[dict]:
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
