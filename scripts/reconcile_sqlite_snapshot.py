"""Reconcile a fresh SQLite snapshot into the existing PostgreSQL canary."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
from collections import Counter
from pathlib import Path

import psycopg
from migrate_sqlite_snapshot import _digest, read_snapshot
from psycopg.types.json import Jsonb

QUERIES = {
    "sessions": "SELECT id,tenant_id,portfolio_id,customer_id,debt_id,state FROM runtime.sessions ORDER BY id",
    "agreements": "SELECT agreement_id,origin_session_id,data FROM runtime.payment_agreements ORDER BY agreement_id",
    "instructions": "SELECT payment_id,agreement_id,method,installment_number,data FROM runtime.payment_instructions ORDER BY payment_id",
    "receipts": "SELECT session_id,snapshot_id,path,content_hash FROM okf.receipts ORDER BY session_id,path",
}


def key(name: str, row: tuple) -> object:
    return (row[0], row[2]) if name == "receipts" else row[0]


def reconcile(snapshot: dict, dsn: str) -> dict:
    changes: Counter[str] = Counter()
    with psycopg.connect(dsn, connect_timeout=10) as target:
        target.execute("SET LOCAL lock_timeout = '5s'")
        existing = {
            name: {key(name, row): row for row in target.execute(query)}
            for name, query in QUERIES.items()
        }
        for name, rows in snapshot.items():
            if set(existing[name]) - {key(name, row) for row in rows}:
                raise ValueError("unexpected_canary_rows")
        with target.cursor() as cursor:
            for row in snapshot["sessions"]:
                old = existing["sessions"].get(row[0])
                if old == row:
                    continue
                changes["sessions_inserted" if old is None else "sessions_updated"] += 1
                cursor.execute(
                    """INSERT INTO runtime.sessions
                       (id,tenant_id,portfolio_id,customer_id,debt_id,state)
                       VALUES (%s,%s,%s,%s,%s,%s)
                       ON CONFLICT (id) DO UPDATE SET tenant_id=excluded.tenant_id,
                         portfolio_id=excluded.portfolio_id,customer_id=excluded.customer_id,
                         debt_id=excluded.debt_id,state=excluded.state""",
                    (*row[:5], Jsonb(row[5])),
                )
            for row in snapshot["agreements"]:
                old = existing["agreements"].get(row[0])
                if old == row:
                    continue
                changes["agreements_inserted" if old is None else "agreements_updated"] += 1
                cursor.execute(
                    """INSERT INTO runtime.payment_agreements
                       (agreement_id,origin_session_id,data) VALUES (%s,%s,%s)
                       ON CONFLICT (agreement_id) DO UPDATE SET
                         origin_session_id=excluded.origin_session_id,data=excluded.data""",
                    (row[0], row[1], Jsonb(row[2])),
                )
            for row in snapshot["instructions"]:
                old = existing["instructions"].get(row[0])
                if old == row:
                    continue
                changes["instructions_inserted" if old is None else "instructions_updated"] += 1
                cursor.execute(
                    """INSERT INTO runtime.payment_instructions
                       (payment_id,agreement_id,method,installment_number,data)
                       VALUES (%s,%s,%s,%s,%s)
                       ON CONFLICT (payment_id) DO UPDATE SET
                         agreement_id=excluded.agreement_id,method=excluded.method,
                         installment_number=excluded.installment_number,data=excluded.data""",
                    (*row[:4], Jsonb(row[4])),
                )
            for row in snapshot["receipts"]:
                old = existing["receipts"].get(key("receipts", row))
                if old == row:
                    continue
                changes["receipts_inserted" if old is None else "receipts_updated"] += 1
                cursor.execute(
                    """INSERT INTO okf.receipts
                       (session_id,snapshot_id,path,content_hash) VALUES (%s,%s,%s,%s)
                       ON CONFLICT (session_id,path) DO UPDATE SET
                         snapshot_id=excluded.snapshot_id,content_hash=excluded.content_hash""",
                    row,
                )
        for name, query in QUERIES.items():
            actual = list(target.execute(query))
            expected = snapshot[name]
            if name == "receipts":
                actual = sorted(actual, key=lambda row: (row[0], row[2]))
                expected = sorted(expected, key=lambda row: (row[0], row[2]))
            if _digest(actual) != _digest(expected):
                raise ValueError(f"reconciliation_parity_failed:{name}")
    return {"counts": {name: len(rows) for name, rows in snapshot.items()},
            "changes": dict(changes)}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("snapshot", type=Path)
    parser.add_argument("--expected-sha256", required=True)
    args = parser.parse_args()
    if os.getenv("RAILWAY_SERVICE_ID") != "accedeb1-4a8d-455e-a7ed-f4d2d7d92dec":
        raise ValueError("wrong_service")
    if os.getenv("SESSION_BACKEND") != "postgres":
        raise ValueError("wrong_backend")
    if hashlib.sha256(args.snapshot.read_bytes()).hexdigest() != args.expected_sha256:
        raise ValueError("snapshot_hash_mismatch")
    print(json.dumps(reconcile(read_snapshot(args.snapshot), os.environ["SESSION_DATABASE_URL"])))


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:  # noqa: BLE001 - suppress operational data in errors
        code = str(exc)
        if code not in {
            "wrong_service", "wrong_backend", "snapshot_hash_mismatch",
            "unexpected_canary_rows",
        } and code not in {f"reconciliation_parity_failed:{name}" for name in QUERIES}:
            code = type(exc).__name__
        print(f"session_reconciliation_failed:{code}", file=sys.stderr)
        raise SystemExit(1) from None
