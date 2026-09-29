"""Apply repository PostgreSQL migrations once, in filename order."""

from __future__ import annotations

import os
from pathlib import Path

import psycopg


def main() -> None:
    dsn = os.getenv("SESSION_DATABASE_URL", "").strip()
    if not dsn:
        raise SystemExit("SESSION_DATABASE_URL_required")
    root = Path(__file__).resolve().parents[1] / "migrations"
    with psycopg.connect(dsn) as db:
        db.execute("CREATE SCHEMA IF NOT EXISTS runtime")
        db.execute(
            """CREATE TABLE IF NOT EXISTS runtime.schema_migrations (
                   name text PRIMARY KEY,
                   applied_at timestamptz NOT NULL DEFAULT now()
               )"""
        )
        for path in sorted(root.glob("*.sql")):
            if db.execute(
                "SELECT 1 FROM runtime.schema_migrations WHERE name=%s", (path.name,)
            ).fetchone():
                continue
            db.execute(path.read_text(encoding="utf-8"))
            db.execute(
                "INSERT INTO runtime.schema_migrations(name) VALUES (%s)",
                (path.name,),
            )
            print(f"applied {path.name}")


if __name__ == "__main__":
    main()
