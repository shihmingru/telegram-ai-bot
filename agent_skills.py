"""Persistent, reviewable user skills for the zero-cost Telegram agent.

Skill changes proposed by the model are staged in Postgres and only become active
after the owner explicitly approves them in Telegram.
"""
from __future__ import annotations

import re
import psycopg

from agent_features import SKILLS as BUILTIN_SKILLS


_NAME_RE = re.compile(r"^[a-z0-9][a-z0-9 -]{1,39}$")


def validate_skill(name: str, instructions: str) -> tuple[str, str]:
    name = " ".join((name or "").lower().split())
    instructions = (instructions or "").strip()
    if not _NAME_RE.fullmatch(name):
        raise ValueError("Skill names must be 2–40 characters using letters, numbers, spaces, or hyphens.")
    if len(instructions) < 20 or len(instructions) > 6000:
        raise ValueError("Skill instructions must contain 20–6000 characters.")
    return name, instructions


def ensure_skill_tables(db: str) -> None:
    with psycopg.connect(db) as conn, conn.cursor() as cur:
        cur.execute("""
            CREATE TABLE IF NOT EXISTS agent_custom_skills (
                name TEXT PRIMARY KEY,
                instructions TEXT NOT NULL,
                updated_by TEXT NOT NULL,
                updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
            )
        """)
        cur.execute("""
            CREATE TABLE IF NOT EXISTS agent_skill_proposals (
                id BIGSERIAL PRIMARY KEY,
                user_id TEXT NOT NULL,
                action TEXT NOT NULL CHECK (action IN ('create', 'update')),
                name TEXT NOT NULL,
                instructions TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'pending'
                    CHECK (status IN ('pending', 'approved', 'rejected')),
                created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                decided_at TIMESTAMPTZ
            )
        """)
        cur.execute("CREATE INDEX IF NOT EXISTS agent_skill_proposals_user_idx ON agent_skill_proposals(user_id, status, id DESC)")
        conn.commit()


def list_skills(db: str) -> list[dict]:
    result = [{"name": name, "source": "built-in"} for name in sorted(BUILTIN_SKILLS, key=str.casefold)]
    ensure_skill_tables(db)
    with psycopg.connect(db) as conn, conn.cursor() as cur:
        cur.execute("SELECT name FROM agent_custom_skills ORDER BY name")
        result.extend({"name": row[0], "source": "custom"} for row in cur.fetchall())
    return result


def get_skill(db: str, name: str) -> dict | None:
    key = " ".join((name or "").lower().split())
    if key in BUILTIN_SKILLS:
        return {"name": key, "instructions": BUILTIN_SKILLS[key], "source": "built-in"}
    ensure_skill_tables(db)
    with psycopg.connect(db) as conn, conn.cursor() as cur:
        cur.execute("SELECT instructions FROM agent_custom_skills WHERE name=%s", (key,))
        row = cur.fetchone()
    return {"name": key, "instructions": row[0], "source": "custom"} if row else None


def propose_skill(db: str, user_id: str, action: str, name: str, instructions: str) -> int:
    name, instructions = validate_skill(name, instructions)
    if action not in {"create", "update"}:
        raise ValueError("Action must be create or update.")
    if name in BUILTIN_SKILLS:
        raise ValueError("Built-in skills cannot be overwritten.")
    ensure_skill_tables(db)
    with psycopg.connect(db) as conn, conn.cursor() as cur:
        cur.execute("SELECT 1 FROM agent_custom_skills WHERE name=%s", (name,))
        exists = cur.fetchone() is not None
        if action == "create" and exists:
            raise ValueError("That custom skill already exists. Propose an update instead.")
        if action == "update" and not exists:
            raise ValueError("That custom skill does not exist. Propose a create instead.")
        cur.execute(
            "INSERT INTO agent_skill_proposals(user_id,action,name,instructions) VALUES (%s,%s,%s,%s) RETURNING id",
            (str(user_id), action, name, instructions),
        )
        ident = cur.fetchone()[0]
        conn.commit()
    return ident


def list_pending_skills(db: str, user_id: str) -> list[tuple]:
    ensure_skill_tables(db)
    with psycopg.connect(db) as conn, conn.cursor() as cur:
        cur.execute(
            "SELECT id,action,name,created_at FROM agent_skill_proposals WHERE user_id=%s AND status='pending' ORDER BY id DESC LIMIT 20",
            (str(user_id),),
        )
        return cur.fetchall()


def decide_skill(db: str, user_id: str, ident: int, approve: bool) -> bool:
    ensure_skill_tables(db)
    with psycopg.connect(db) as conn, conn.cursor() as cur:
        cur.execute(
            "SELECT action,name,instructions FROM agent_skill_proposals WHERE id=%s AND user_id=%s AND status='pending' FOR UPDATE",
            (int(ident), str(user_id)),
        )
        proposal = cur.fetchone()
        if not proposal:
            return False
        action, name, instructions = proposal
        if approve:
            cur.execute(
                """INSERT INTO agent_custom_skills(name,instructions,updated_by,updated_at)
                   VALUES (%s,%s,%s,NOW())
                   ON CONFLICT(name) DO UPDATE SET instructions=EXCLUDED.instructions,
                     updated_by=EXCLUDED.updated_by, updated_at=NOW()""",
                (name, instructions, str(user_id)),
            )
            status = "approved"
        else:
            status = "rejected"
        cur.execute(
            "UPDATE agent_skill_proposals SET status=%s,decided_at=NOW() WHERE id=%s AND user_id=%s",
            (status, int(ident), str(user_id)),
        )
        conn.commit()
        return True


def delete_custom_skill(db: str, name: str) -> bool:
    """Delete one custom skill by exact normalized name; built-ins are protected."""
    key = " ".join((name or "").lower().split())
    if not key:
        raise ValueError("Provide the exact custom skill name.")
    if key in BUILTIN_SKILLS:
        raise ValueError("Built-in skills cannot be deleted.")
    ensure_skill_tables(db)
    with psycopg.connect(db) as conn, conn.cursor() as cur:
        cur.execute("DELETE FROM agent_custom_skills WHERE name=%s", (key,))
        changed = cur.rowcount == 1
        conn.commit()
        return changed
