"""The backfill must preserve normalized bindings and negotiation records."""

import json
import sqlite3

from scripts.migrate_sqlite_snapshot import read_snapshot


def test_read_snapshot_rebuilds_bound_fixture_and_preserves_records(tmp_path):
    path = tmp_path / "sessions.sqlite3"
    with sqlite3.connect(path) as db:
        db.executescript(
            """
            CREATE TABLE sessions(id TEXT PRIMARY KEY,data TEXT NOT NULL);
            CREATE TABLE session_contexts(session_id TEXT,tenant_id TEXT,portfolio_id TEXT,customer_id TEXT,debt_id TEXT);
            CREATE TABLE customers(id TEXT,tenant_id TEXT,full_name TEXT,cpf TEXT,phone TEXT,birth_date TEXT);
            CREATE TABLE portfolios(id TEXT,tenant_id TEXT,creditor_name TEXT);
            CREATE TABLE debts(id TEXT,tenant_id TEXT,product TEXT,data TEXT,eligibility TEXT,identity_policy TEXT);
            CREATE TABLE payment_agreements(agreement_id TEXT,origin_session_id TEXT,data TEXT);
            CREATE TABLE payment_instructions(payment_id TEXT,agreement_id TEXT,method TEXT,installment_number INTEGER,data TEXT);
            """
        )
        db.execute("INSERT INTO sessions VALUES (?,?)", ("bound", json.dumps({"identity_verified": True, "receipts": {"policy.md": {"snapshot_id": "snap", "hash": "abc"}}})))
        db.execute("INSERT INTO sessions VALUES (?,?)", ("unbound", json.dumps({"unbound_session": True})))
        db.execute("INSERT INTO customers VALUES (?,?,?,?,?,?)", ("customer", "tenant", "Test Customer", "123", "555", "2000-01-01"))
        db.execute("INSERT INTO portfolios VALUES (?,?,?)", ("portfolio", "tenant", "Test Bank"))
        db.execute("INSERT INTO debts VALUES (?,?,?,?,?,?)", ("debt", "tenant", "test_product", json.dumps({"debt_id": "debt", "current_amount": "100"}), "{}", "{}"))
        db.execute("INSERT INTO session_contexts VALUES (?,?,?,?,?)", ("bound", "tenant", "portfolio", "customer", "debt"))
        db.execute("INSERT INTO payment_agreements VALUES (?,?,?)", ("agreement", "bound", json.dumps({"agreement_id": "agreement"})))
        db.execute("INSERT INTO payment_instructions VALUES (?,?,?,?,?)", ("payment", "agreement", "boleto", 1, json.dumps({"payment_id": "payment"})))

    snapshot = read_snapshot(path)
    bound = snapshot["sessions"][0]
    assert bound[:5] == ("bound", "tenant", "portfolio", "customer", "debt")
    assert bound[5]["fixture"]["institution"] == "Test Bank"
    assert bound[5]["fixture"]["debt"]["current_amount"] == "100"
    assert snapshot["sessions"][1][5]["unbound_session"] is True
    assert snapshot["receipts"] == [("bound", "snap", "policy.md", "abc")]
    assert len(snapshot["agreements"]) == len(snapshot["instructions"]) == 1
