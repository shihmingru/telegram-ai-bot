"""User-scoped text workspace backed by the existing PostgreSQL database.

This intentionally stores text only and never executes uploaded or saved code.
"""
from __future__ import annotations

import re
import psycopg

_FILENAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._ -]{0,99}$")
MAX_FILE_CHARS = 50_000


def validate_filename(filename: str) -> str:
    value = " ".join((filename or "").strip().split())
    if (not value or not _FILENAME_RE.fullmatch(value) or ".." in value
            or value.startswith(".") or value.endswith(".")):
        raise ValueError("Use a simple filename of up to 100 characters without folders or path traversal.")
    return value


def validate_content(content: str) -> str:
    value = str(content or "")
    if not value.strip():
        raise ValueError("File content cannot be empty.")
    if len(value) > MAX_FILE_CHARS:
        raise ValueError(f"Text files are limited to {MAX_FILE_CHARS} characters.")
    return value


def ensure_workspace_table(db: str) -> None:
    with psycopg.connect(db) as conn, conn.cursor() as cur:
        cur.execute("""
            CREATE TABLE IF NOT EXISTS agent_workspace_files (
                user_id TEXT NOT NULL,
                filename TEXT NOT NULL,
                content TEXT NOT NULL,
                updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                PRIMARY KEY (user_id, filename)
            )
        """)
        cur.execute("CREATE INDEX IF NOT EXISTS agent_workspace_user_idx ON agent_workspace_files(user_id, updated_at DESC)")
        conn.commit()


def list_files(db: str, user_id: str) -> list[dict]:
    ensure_workspace_table(db)
    with psycopg.connect(db) as conn, conn.cursor() as cur:
        cur.execute(
            "SELECT filename, char_length(content), updated_at FROM agent_workspace_files WHERE user_id=%s ORDER BY filename LIMIT 100",
            (str(user_id),),
        )
        return [{"filename": name, "characters": size, "updated_at": updated.isoformat()} for name, size, updated in cur.fetchall()]


def read_file(db: str, user_id: str, filename: str) -> dict | None:
    name = validate_filename(filename)
    ensure_workspace_table(db)
    with psycopg.connect(db) as conn, conn.cursor() as cur:
        cur.execute(
            "SELECT content, updated_at FROM agent_workspace_files WHERE user_id=%s AND filename=%s",
            (str(user_id), name),
        )
        row = cur.fetchone()
    return {"filename": name, "content": row[0], "updated_at": row[1].isoformat()} if row else None


def save_file(db: str, user_id: str, filename: str, content: str, overwrite: bool = False) -> dict:
    name = validate_filename(filename)
    body = validate_content(content)
    ensure_workspace_table(db)
    with psycopg.connect(db) as conn, conn.cursor() as cur:
        cur.execute(
            "SELECT 1 FROM agent_workspace_files WHERE user_id=%s AND filename=%s FOR UPDATE",
            (str(user_id), name),
        )
        exists = cur.fetchone() is not None
        if exists and not overwrite:
            return {"saved": False, "reason": "exists", "filename": name, "instruction": "Read the existing file first; set overwrite=true only when the user asks to replace it."}
        cur.execute(
            """INSERT INTO agent_workspace_files(user_id,filename,content)
               VALUES (%s,%s,%s)
               ON CONFLICT(user_id,filename) DO UPDATE
               SET content=EXCLUDED.content, updated_at=NOW()""",
            (str(user_id), name, body),
        )
        conn.commit()
    return {"saved": True, "filename": name, "characters": len(body), "overwritten": exists}


def delete_file(db: str, user_id: str, filename: str) -> bool:
    name = validate_filename(filename)
    ensure_workspace_table(db)
    with psycopg.connect(db) as conn, conn.cursor() as cur:
        cur.execute(
            "DELETE FROM agent_workspace_files WHERE user_id=%s AND filename=%s",
            (str(user_id), name),
        )
        changed = cur.rowcount == 1
        conn.commit()
        return changed
