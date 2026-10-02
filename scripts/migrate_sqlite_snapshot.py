"""Copy a consistent SQLite session snapshot into an empty PostgreSQL canary."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sqlite3
import sys
from pathlib import Path


def _json(value: str) -> dict:
    result = json.loads(value)
    if not isinstance(result, dict):
        raise ValueError("invalid_snapshot_json")
    return result


def _canonical(value: object) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()


def read_snapshot(path: Path) -> dict:
    with sqlite3.connect(f"file:{path}?mode=ro", uri=True) as source:
        if source.execute("PRAGMA quick_check").fetchone()[0] != "ok":
            raise ValueError("sqlite_quick_check_failed")
        if source.execute("PRAGMA foreign_key_check").fetchone():
            raise ValueError("sqlite_foreign_key_check_failed")

        bindings = {}
        for row in source.execute(
            """SELECT x.session_id,x.tenant_id,x.portfolio_id,c.id,c.full_name,
                      c.cpf,c.phone,c.birth_date,p.creditor_name,d.id,d.product,
                      d.data,d.eligibility,d.identity_policy
               FROM session_contexts x
               JOIN customers c ON (c.tenant_id,c.id)=(x.tenant_id,x.customer_id)
               JOIN portfolios p ON (p.tenant_id,p.id)=(x.tenant_id,x.portfolio_id)
               JOIN debts d ON (d.tenant_id,d.id)=(x.tenant_id,x.debt_id)"""
        ):
            (
                thread, tenant, portfolio, customer, full_name, cpf, phone,
                birth_date, creditor, debt_id, product, debt_raw,
                eligibility_raw, policy_raw,
            ) = row
            debt = _json(debt_raw)
            fixture = {
                "customer_id": customer,
                "full_name": full_name,
                "cpf": cpf,
                "phone": phone,
                "birth_date": birth_date,
                "institution": creditor,
                "creditor_name": creditor,
                "product": product,
                "debt": debt,
                "eligibility": _json(eligibility_raw),
                "identity_policy": _json(policy_raw),
            }
            if debt.get("company"):
                fixture["company"] = debt["company"]
            bindings[thread] = (tenant, portfolio, customer, debt_id, fixture)

        sessions, receipts = [], []
        for thread, raw in source.execute("SELECT id,data FROM sessions ORDER BY id"):
            state = _json(raw)
            binding = bindings.get(thread)
            if binding:
                tenant, portfolio, customer, debt_id, fixture = binding
                state["fixture"] = fixture
            else:
                fixture = state.get("fixture")
                if not isinstance(fixture, dict) and state.get("unbound_session") is not True:
                    raise ValueError("session_without_fixture_or_binding")
                tenant = portfolio = None
                customer = fixture.get("customer_id") if isinstance(fixture, dict) else None
                debt_id = fixture.get("debt", {}).get("debt_id") if isinstance(fixture, dict) else None
            sessions.append((thread, tenant, portfolio, customer, debt_id, state))
            for receipt_path, receipt in state.get("receipts", {}).items():
                if not isinstance(receipt, dict) or not receipt.get("hash"):
                    raise ValueError("invalid_okf_receipt")
                receipts.append(
                    (thread, receipt.get("snapshot_id") or state.get("snapshot_id"), receipt_path, receipt["hash"])
                )
        if len(bindings) != sum(row[0] in bindings for row in sessions):
            raise ValueError("orphan_session_binding")

        agreements = [
            (agreement_id, thread, _json(raw))
            for agreement_id, thread, raw in source.execute(
                "SELECT agreement_id,origin_session_id,data FROM payment_agreements ORDER BY agreement_id"
            )
        ]
        instructions = [
            (payment_id, agreement_id, method, number, _json(raw))
            for payment_id, agreement_id, method, number, raw in source.execute(
                """SELECT payment_id,agreement_id,method,installment_number,data
                   FROM payment_instructions ORDER BY payment_id"""
            )
        ]
    return {
        "sessions": sessions,
        "receipts": receipts,
        "agreements": agreements,
        "instructions": instructions,
    }


def _digest(rows: list[tuple]) -> str:
    h = hashlib.sha256()
    for row in rows:
        h.update(_canonical(row))
        h.update(b"\n")
    return h.hexdigest()


def import_snapshot(snapshot: dict, dsn: str) -> None:
    import psycopg
    from psycopg.types.json import Jsonb

    with psycopg.connect(dsn, connect_timeout=10) as target:
        target.execute("SET LOCAL lock_timeout = '5s'")
        tables = (
            "runtime.sessions", "runtime.payment_agreements",
            "runtime.payment_instructions", "okf.receipts",
        )
        if any(target.execute(f"SELECT 1 FROM {table} LIMIT 1").fetchone() for table in tables):
            raise ValueError("target_not_empty")
        with target.cursor() as cursor:
            cursor.executemany(
                """INSERT INTO runtime.sessions
                   (id,tenant_id,portfolio_id,customer_id,debt_id,state)
                   VALUES (%s,%s,%s,%s,%s,%s)""",
                [(*row[:5], Jsonb(row[5])) for row in snapshot["sessions"]],
            )
            cursor.executemany(
                """INSERT INTO runtime.payment_agreements
                   (agreement_id,origin_session_id,data) VALUES (%s,%s,%s)""",
                [(row[0], row[1], Jsonb(row[2])) for row in snapshot["agreements"]],
            )
            cursor.executemany(
                """INSERT INTO runtime.payment_instructions
                   (payment_id,agreement_id,method,installment_number,data)
                   VALUES (%s,%s,%s,%s,%s)""",
                [(*row[:4], Jsonb(row[4])) for row in snapshot["instructions"]],
            )
            cursor.executemany(
                """INSERT INTO okf.receipts
                   (session_id,snapshot_id,path,content_hash) VALUES (%s,%s,%s,%s)""",
                snapshot["receipts"],
            )
        copied = [
            (row[0], row[1], row[2], row[3], row[4], row[5])
            for row in target.execute(
                """SELECT id,tenant_id,portfolio_id,customer_id,debt_id,state
                   FROM runtime.sessions ORDER BY id"""
            )
        ]
        if _digest(copied) != _digest(snapshot["sessions"]):
            raise ValueError("session_parity_failed")
        checks = (
            ("agreements", "SELECT agreement_id,origin_session_id,data FROM runtime.payment_agreements ORDER BY agreement_id"),
            ("instructions", "SELECT payment_id,agreement_id,method,installment_number,data FROM runtime.payment_instructions ORDER BY payment_id"),
            ("receipts", "SELECT session_id,snapshot_id,path,content_hash FROM okf.receipts ORDER BY session_id,path"),
        )
        for key, query in checks:
            copied_rows = list(target.execute(query))
            original_rows = snapshot[key]
            if key == "receipts":
                copied_rows = sorted(copied_rows, key=lambda row: (row[0], row[2]))
                original_rows = sorted(original_rows, key=lambda row: (row[0], row[2]))
            if _digest(copied_rows) != _digest(original_rows):
                raise ValueError("record_parity_failed")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("snapshot", type=Path)
    parser.add_argument("--expected-sha256", required=True)
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--expected-service-id")
    args = parser.parse_args()
    with args.snapshot.open("rb") as source:
        actual_hash = hashlib.file_digest(source, "sha256").hexdigest()
    if actual_hash != args.expected_sha256:
        raise SystemExit("snapshot_hash_mismatch")
    snapshot = read_snapshot(args.snapshot)
    if args.apply:
        if not args.expected_service_id or os.getenv("RAILWAY_SERVICE_ID") != args.expected_service_id:
            raise SystemExit("canary_service_mismatch")
        if os.getenv("SESSION_BACKEND") != "postgres":
            raise SystemExit("postgres_backend_required")
        import_snapshot(snapshot, os.environ["SESSION_DATABASE_URL"])
    print(json.dumps({"applied": args.apply, "counts": {key: len(value) for key, value in snapshot.items()},
                      "sessions_digest": _digest(snapshot["sessions"])}))


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print(f"migration_failed:{type(exc).__name__}", file=sys.stderr)
        raise SystemExit(1) from None
