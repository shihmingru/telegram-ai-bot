"""Platform integrations for the Telegram AI agent.

All credentials are read from environment variables. Mutating tools are queued
for explicit Telegram approval; the model never executes them directly.
"""
import json
import os
import uuid
from datetime import datetime, timedelta, timezone
from urllib.parse import quote

import requests


TIMEOUT = 20
GITHUB_API = "https://api.github.com"
RENDER_API = "https://api.render.com/v1"
TODOIST_API = "https://api.todoist.com/api/v1"
GOOGLE_TOKEN_URL = "https://oauth2.googleapis.com/token"
GOOGLE_CALENDAR_API = "https://www.googleapis.com/calendar/v3"


def is_allowed_telegram_user(user_id, configured=None):
    """Fail closed unless the Telegram account ID is explicitly allowlisted."""
    if configured is None:
        configured = os.getenv("TELEGRAM_OWNER_IDS", "")
    allowed = {item.strip() for item in configured.split(",") if item.strip()}
    return bool(allowed) and str(user_id) in allowed


def _request(method, url, *, headers=None, params=None, payload=None):
    response = requests.request(
        method, url, headers=headers, params=params, json=payload, timeout=TIMEOUT
    )
    if not response.ok:
        excerpt = response.text[:500]
        raise RuntimeError(f"Platform API returned HTTP {response.status_code}: {excerpt}")
    if response.status_code == 204 or not response.content:
        return {"ok": True}
    return response.json()


def _github_headers():
    token = os.getenv("GITHUB_TOKEN")
    if not token:
        raise RuntimeError("GitHub integration is not configured. Add GITHUB_TOKEN in Render.")
    return {"Authorization": f"Bearer {token}", "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28"}


def _render_headers():
    token = os.getenv("RENDER_API_KEY")
    if not token:
        raise RuntimeError("Render integration is not configured. Add RENDER_API_KEY in Render.")
    return {"Authorization": f"Bearer {token}", "Accept": "application/json"}


def _todoist_headers():
    token = os.getenv("TODOIST_API_TOKEN")
    if not token:
        raise RuntimeError("Todoist integration is not configured. Add TODOIST_API_TOKEN in Render.")
    return {"Authorization": f"Bearer {token}", "Accept": "application/json"}


def _google_access_token():
    client_id = os.getenv("GOOGLE_OAUTH_CLIENT_ID")
    client_secret = os.getenv("GOOGLE_OAUTH_CLIENT_SECRET")
    refresh_token = os.getenv("GOOGLE_OAUTH_REFRESH_TOKEN")
    if not all((client_id, client_secret, refresh_token)):
        raise RuntimeError(
            "Google Calendar is not configured. Add GOOGLE_OAUTH_CLIENT_ID, "
            "GOOGLE_OAUTH_CLIENT_SECRET, and GOOGLE_OAUTH_REFRESH_TOKEN in Render."
        )
    result = _request("POST", GOOGLE_TOKEN_URL, payload={
        "client_id": client_id,
        "client_secret": client_secret,
        "refresh_token": refresh_token,
        "grant_type": "refresh_token",
    })
    token = result.get("access_token")
    if not token:
        raise RuntimeError("Google OAuth did not return an access token.")
    return token


def _google_headers():
    return {"Authorization": f"Bearer {_google_access_token()}",
            "Accept": "application/json", "Content-Type": "application/json"}


def _calendar_id():
    return os.getenv("GOOGLE_CALENDAR_ID", "primary")


def ensure_approval_table(database_url):
    import psycopg
    with psycopg.connect(database_url) as conn:
        with conn.cursor() as cur:
            cur.execute("""
                CREATE TABLE IF NOT EXISTS agent_pending_actions (
                    action_id TEXT PRIMARY KEY,
                    user_id TEXT NOT NULL,
                    tool_name TEXT NOT NULL,
                    arguments JSONB NOT NULL,
                    status TEXT NOT NULL DEFAULT 'pending',
                    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                    completed_at TIMESTAMPTZ,
                    result JSONB
                )
            """)
        conn.commit()


def queue_action(database_url, user_id, tool_name, arguments):
    import psycopg
    action_id = uuid.uuid4().hex[:8].upper()
    ensure_approval_table(database_url)
    with psycopg.connect(database_url) as conn:
        with conn.cursor() as cur:
            cur.execute(
                """INSERT INTO agent_pending_actions
                   (action_id, user_id, tool_name, arguments, status)
                   VALUES (%s, %s, %s, %s::jsonb, 'pending')""",
                (action_id, str(user_id), tool_name, json.dumps(arguments)),
            )
        conn.commit()
    return {
        "status": "awaiting_approval",
        "action_id": action_id,
        "summary": _action_summary(tool_name, arguments),
        "instruction": f"Ask the user to approve with /approve {action_id} or reject with /cancel {action_id}. Do not claim the action has been performed."
    }


def _action_summary(tool_name, args):
    summaries = {
        "github_create_issue": f"Create GitHub issue in {args.get('repository')}: {args.get('title')}",
        "render_trigger_deploy": f"Trigger a Render deployment for service {args.get('service_id')}",
        "todoist_create_task": f"Create Todoist task: {args.get('content')}",
        "google_calendar_create_event": f"Create calendar event: {args.get('summary')} from {args.get('start')} to {args.get('end')}",
    }
    return summaries.get(tool_name, f"Run {tool_name} with the requested arguments")


def execute_approved_action(database_url, user_id, action_id):
    import psycopg
    ensure_approval_table(database_url)
    with psycopg.connect(database_url) as conn:
        with conn.cursor() as cur:
            cur.execute(
                """SELECT tool_name, arguments, status FROM agent_pending_actions
                   WHERE action_id=%s AND user_id=%s""",
                (action_id.upper(), str(user_id)),
            )
            row = cur.fetchone()
            if not row:
                return {"ok": False, "message": "No pending action with that ID belongs to your account."}
            tool_name, arguments, status = row
            if status != "pending":
                return {"ok": False, "message": f"This action is already {status}."}
            cur.execute(
                "UPDATE agent_pending_actions SET status='executing' WHERE action_id=%s AND status='pending'",
                (action_id.upper(),),
            )
        conn.commit()
    try:
        result = execute_platform_tool(tool_name, dict(arguments), allow_mutation=True)
        with psycopg.connect(database_url) as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """UPDATE agent_pending_actions SET status='completed',
                       completed_at=NOW(), result=%s::jsonb WHERE action_id=%s""",
                    (json.dumps(result, default=str), action_id.upper()),
                )
            conn.commit()
        return {"ok": True, "action_id": action_id.upper(), "result": result}
    except Exception as exc:
        with psycopg.connect(database_url) as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """UPDATE agent_pending_actions SET status='failed',
                       completed_at=NOW(), result=%s::jsonb WHERE action_id=%s""",
                    (json.dumps({"error": str(exc)}), action_id.upper()),
                )
            conn.commit()
        return {"ok": False, "action_id": action_id.upper(), "error": str(exc)}


def cancel_action(database_url, user_id, action_id):
    import psycopg
    ensure_approval_table(database_url)
    with psycopg.connect(database_url) as conn:
        with conn.cursor() as cur:
            cur.execute(
                """UPDATE agent_pending_actions SET status='cancelled', completed_at=NOW()
                   WHERE action_id=%s AND user_id=%s AND status='pending'""",
                (action_id.upper(), str(user_id)),
            )
            changed = cur.rowcount
        conn.commit()
    return changed == 1


def platform_tool_declarations(types):
    declarations = [
        ("github_search_repositories", "Search public GitHub repositories or your accessible repositories.",
         {"query": {"type": "STRING", "description": "Repository search query"}}, ["query"]),
        ("github_get_file", "Read a text file from a GitHub repository. Defaults to the configured GITHUB_DEFAULT_REPOSITORY.",
         {"path": {"type": "STRING", "description": "File path"},
          "repository": {"type": "STRING", "description": "owner/repository; optional"}},
         ["path"]),
        ("github_create_issue", "Create a GitHub issue. This changes GitHub and always requires user approval.",
         {"repository": {"type": "STRING", "description": "owner/repository"},
          "title": {"type": "STRING", "description": "Issue title"},
          "body": {"type": "STRING", "description": "Issue body"}},
         ["repository", "title"]),
        ("render_list_services", "List services in the connected Render account.",
         {}, []),
        ("render_list_deploys", "List recent deployments for a Render service.",
         {"service_id": {"type": "STRING", "description": "Render service ID"}},
         ["service_id"]),
        ("render_trigger_deploy", "Trigger a Render deployment. This changes service state and always requires user approval.",
         {"service_id": {"type": "STRING", "description": "Render service ID"}},
         ["service_id"]),
        ("todoist_list_tasks", "List active tasks in Todoist.",
         {}, []),
        ("todoist_create_task", "Create a Todoist task. This changes Todoist and always requires user approval.",
         {"content": {"type": "STRING", "description": "Task title"},
          "due_string": {"type": "STRING", "description": "Optional natural-language due date"}},
         ["content"]),
        ("google_calendar_list_events", "List events from Google Calendar in a time window. Use RFC3339 date-time strings; defaults to the next 7 days.",
         {"time_min": {"type": "STRING", "description": "Optional RFC3339 start"},
          "time_max": {"type": "STRING", "description": "Optional RFC3339 end"}},
         []),
        ("google_calendar_create_event", "Create a Google Calendar event. This changes the calendar and always requires user approval. Use RFC3339 date-times with timezone offsets.",
         {"summary": {"type": "STRING", "description": "Event title"},
          "start": {"type": "STRING", "description": "RFC3339 start datetime with timezone"},
          "end": {"type": "STRING", "description": "RFC3339 end datetime with timezone"},
          "description": {"type": "STRING", "description": "Optional event description"}},
         ["summary", "start", "end"]),
    ]
    funcs = []
    for name, description, properties, required in declarations:
        funcs.append(types.FunctionDeclaration(
            name=name,
            description=description,
            parameters={"type": "OBJECT", "properties": properties, "required": required},
        ))
    return funcs


def execute_platform_tool(name, args, allow_mutation=False):
    """Execute a tool with strict argument validation and API-side result checking."""
    if name in {"github_create_issue", "render_trigger_deploy", "todoist_create_task",
                "google_calendar_create_event"} and not allow_mutation:
        return {"error": "Mutation blocked: explicit approval is required."}

    if name == "github_search_repositories":
        query = str(args.get("query", "")).strip()
        if not query:
            return {"error": "A search query is required."}
        result = _request("GET", f"{GITHUB_API}/search/repositories",
                          headers=_github_headers(), params={"q": query, "per_page": 8})
        return {"total_count": result.get("total_count", 0), "items": [
            {"full_name": item.get("full_name"), "description": item.get("description"),
             "html_url": item.get("html_url"), "private": item.get("private"),
             "default_branch": item.get("default_branch")}
            for item in result.get("items", [])
        ]}

    if name == "github_get_file":
        repo = str(args.get("repository") or os.getenv("GITHUB_DEFAULT_REPOSITORY", "")).strip()
        path = str(args.get("path", "")).strip().lstrip("/")
        if not repo or "/" not in repo or not path or ".." in path.split("/"):
            return {"error": "Provide a valid repository (owner/name) and safe file path."}
        result = _request("GET", f"{GITHUB_API}/repos/{quote(repo, safe='/')}/contents/{quote(path, safe='/')}",
                          headers=_github_headers())
        if result.get("type") != "file":
            return {"error": "The path is not a single file."}
        import base64
        content = base64.b64decode(result.get("content", "")).decode("utf-8", errors="replace")
        return {"repository": repo, "path": path, "html_url": result.get("html_url"),
                "content": content[:20000], "truncated": len(content) > 20000}

    if name == "github_create_issue":
        repo = str(args.get("repository", "")).strip()
        title = str(args.get("title", "")).strip()
        if not repo or "/" not in repo or not title:
            return {"error": "A repository in owner/name format and issue title are required."}
        if not allow_mutation:
            return {"error": "Explicit approval required."}
        result = _request("POST", f"{GITHUB_API}/repos/{quote(repo, safe='/')}/issues",
                          headers=_github_headers(),
                          payload={"title": title, "body": str(args.get("body", ""))})
        return {"number": result.get("number"), "title": result.get("title"), "html_url": result.get("html_url"),
                "state": result.get("state")}

    if name == "render_list_services":
        result = _request("GET", f"{RENDER_API}/services", headers=_render_headers(),
                          params={"limit": 20})
        items = result if isinstance(result, list) else result.get("items", [])
        return {"services": [{
            "id": (item.get("service") or item).get("id"),
            "name": (item.get("service") or item).get("name"),
            "type": (item.get("service") or item).get("type"),
            "status": (item.get("service") or item).get("suspended"),
        } for item in items]}

    if name == "render_list_deploys":
        service_id = str(args.get("service_id", "")).strip()
        if not service_id:
            return {"error": "A Render service ID is required."}
        result = _request("GET", f"{RENDER_API}/services/{quote(service_id, safe='')}/deploys",
                          headers=_render_headers(), params={"limit": 10})
        items = result if isinstance(result, list) else result.get("items", [])
        return {"deploys": [{
            "id": (item.get("deploy") or item).get("id"),
            "status": (item.get("deploy") or item).get("status"),
            "createdAt": (item.get("deploy") or item).get("createdAt"),
            "commit": (item.get("deploy") or item).get("commit"),
        } for item in items]}

    if name == "render_trigger_deploy":
        service_id = str(args.get("service_id", "")).strip()
        if not service_id:
            return {"error": "A Render service ID is required."}
        result = _request("POST", f"{RENDER_API}/services/{quote(service_id, safe='')}/deploys",
                          headers=_render_headers(), payload={})
        return {"deploy_id": result.get("id"), "status": result.get("status"),
                "createdAt": result.get("createdAt")}

    if name == "todoist_list_tasks":
        result = _request("GET", f"{TODOIST_API}/tasks", headers=_todoist_headers(),
                          params={"limit": 50})
        items = result if isinstance(result, list) else result.get("results", result.get("items", []))
        return {"tasks": [{"id": x.get("id"), "content": x.get("content"),
                           "due": x.get("due"), "url": x.get("url")}
                          for x in items[:50]]}

    if name == "todoist_create_task":
        content = str(args.get("content", "")).strip()
        if not content:
            return {"error": "Task content is required."}
        payload = {"content": content}
        if str(args.get("due_string", "")).strip():
            payload["due_string"] = str(args["due_string"]).strip()
        result = _request("POST", f"{TODOIST_API}/tasks", headers=_todoist_headers(), payload=payload)
        return {"id": result.get("id"), "content": result.get("content"),
                "url": result.get("url"), "due": result.get("due")}

    if name == "google_calendar_list_events":
        now = datetime.now(timezone.utc)
        time_min = str(args.get("time_min") or now.isoformat()).strip()
        time_max = str(args.get("time_max") or (now + timedelta(days=7)).isoformat()).strip()
        result = _request("GET", f"{GOOGLE_CALENDAR_API}/calendars/{quote(_calendar_id(), safe='')}/events",
                          headers=_google_headers(),
                          params={"timeMin": time_min, "timeMax": time_max, "singleEvents": "true",
                                  "orderBy": "startTime", "maxResults": 50})
        return {"events": [{
            "id": x.get("id"), "summary": x.get("summary"),
            "start": x.get("start"), "end": x.get("end"),
            "htmlLink": x.get("htmlLink"), "status": x.get("status")}
            for x in result.get("items", [])]}

    if name == "google_calendar_create_event":
        summary = str(args.get("summary", "")).strip()
        start = str(args.get("start", "")).strip()
        end = str(args.get("end", "")).strip()
        if not summary or not start or not end:
            return {"error": "Event title, start, and end are required."}
        payload = {"summary": summary, "start": {"dateTime": start},
                   "end": {"dateTime": end}}
        if str(args.get("description", "")).strip():
            payload["description"] = str(args["description"]).strip()
        result = _request("POST", f"{GOOGLE_CALENDAR_API}/calendars/{quote(_calendar_id(), safe='')}/events",
                          headers=_google_headers(), payload=payload)
        return {"id": result.get("id"), "summary": result.get("summary"),
                "htmlLink": result.get("htmlLink"), "start": result.get("start"),
                "end": result.get("end"), "status": result.get("status")}

    return {"error": f"Unknown platform tool: {name}"}
