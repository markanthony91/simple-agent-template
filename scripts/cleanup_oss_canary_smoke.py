"""Remove only synthetic smoke threads from the isolated migration canary."""

from __future__ import annotations

import os
import sys

import psycopg
from langgraph.checkpoint.postgres import PostgresSaver


def cleanup() -> dict[str, int]:
    if os.getenv("RAILWAY_SERVICE_ID") != "accedeb1-4a8d-455e-a7ed-f4d2d7d92dec":
        raise ValueError("wrong_service")
    if os.getenv("SESSION_BACKEND") != "postgres":
        raise ValueError("wrong_backend")
    with psycopg.connect(
        os.environ["SESSION_DATABASE_URL"], autocommit=True,
        options="-c search_path=langgraph",
    ) as db:
        ids = [str(row[0]) for row in db.execute(
            "SELECT thread_id FROM langgraph.oss_threads WHERE metadata->>'channel'='canary'"
        )]
        if len(ids) > 50:
            raise ValueError("too_many_test_threads")
        if not ids:
            return {"threads": 0, "sessions": 0}
        sessions = db.execute(
            "SELECT count(*) FROM runtime.sessions WHERE id::text=ANY(%s::text[])",
            (ids,),
        ).fetchone()[0]
        agreements = db.execute(
            "SELECT count(*) FROM runtime.payment_agreements WHERE origin_session_id::text=ANY(%s::text[])",
            (ids,),
        ).fetchone()[0]
        receipts = db.execute(
            "SELECT count(*) FROM okf.receipts WHERE session_id::text=ANY(%s::text[])",
            (ids,),
        ).fetchone()[0]
        archived = db.execute(
            "SELECT count(*) FROM langgraph.legacy_thread_state WHERE thread_id=ANY(%s::text[])",
            (ids,),
        ).fetchone()[0]
        if (sessions, agreements, receipts, archived) != (len(ids), 0, 0, 0):
            raise ValueError("test_thread_dependencies_changed")
        saver = PostgresSaver(db)
        for thread_id in ids:
            saver.delete_thread(thread_id)
        with db.transaction():
            db.execute("DELETE FROM runtime.sessions WHERE id::text=ANY(%s::text[])", (ids,))
            db.execute("DELETE FROM langgraph.oss_threads WHERE thread_id::text=ANY(%s::text[])", (ids,))
        return {"threads": len(ids), "sessions": sessions}


if __name__ == "__main__":
    try:
        print(cleanup())
    except Exception as exc:  # noqa: BLE001 - no operational content in output
        print(f"canary_cleanup_failed:{type(exc).__name__}", file=sys.stderr)
        raise SystemExit(1) from None
