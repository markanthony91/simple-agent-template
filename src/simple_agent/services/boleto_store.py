"""Indexed simulated agreements, scoped by server-owned session bindings."""

import json
import sqlite3
from datetime import date, datetime
from zoneinfo import ZoneInfo


SCHEMA = """
CREATE TABLE IF NOT EXISTS payment_agreements (
  agreement_id TEXT PRIMARY KEY,
  origin_session_id TEXT NOT NULL REFERENCES sessions(id),
  data TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS payment_agreements_origin
  ON payment_agreements(origin_session_id);
CREATE TABLE IF NOT EXISTS payment_instructions (
  payment_id TEXT PRIMARY KEY,
  agreement_id TEXT NOT NULL REFERENCES payment_agreements(agreement_id) ON DELETE CASCADE,
  method TEXT NOT NULL,
  installment_number INTEGER NOT NULL,
  data TEXT NOT NULL,
  UNIQUE(agreement_id, method, installment_number)
);
CREATE INDEX IF NOT EXISTS session_contexts_customer_debt
  ON session_contexts(tenant_id, portfolio_id, customer_id, debt_id);
"""


def save_payments(db: sqlite3.Connection, session_id: str, state: dict) -> None:
    """Use the caller's transaction: session and indexed records commit together."""
    for agreement in state.get("agreements", {}).values():
        cursor = db.execute(
            """INSERT INTO payment_agreements VALUES(?,?,?)
               ON CONFLICT(agreement_id) DO UPDATE SET data=excluded.data
               WHERE payment_agreements.origin_session_id=excluded.origin_session_id""",
            (agreement["agreement_id"], session_id, json.dumps(agreement)),
        )
        if cursor.rowcount != 1:
            raise ValueError("agreement_origin_mismatch")
    for payment in state.get("payments", {}).values():
        owner = db.execute(
            "SELECT origin_session_id FROM payment_agreements WHERE agreement_id=?",
            (payment["agreement_id"],),
        ).fetchone()
        if not owner or owner[0] != session_id:
            raise ValueError("payment_origin_mismatch")
        cursor = db.execute(
            """INSERT INTO payment_instructions VALUES(?,?,?,?,?)
               ON CONFLICT(payment_id) DO UPDATE SET data=excluded.data
               WHERE payment_instructions.agreement_id=excluded.agreement_id
                 AND payment_instructions.method=excluded.method
                 AND payment_instructions.installment_number=excluded.installment_number""",
            (
                payment["payment_id"],
                payment["agreement_id"],
                payment["method"],
                payment["installment_number"],
                json.dumps(payment),
            ),
        )
        if cursor.rowcount != 1:
            raise ValueError("payment_origin_mismatch")


def second_copy(
    db: sqlite3.Connection,
    session_id: str,
    agreement_id: str,
    installment_number: int | None,
) -> dict:
    # Identity and lookup share one read transaction; a reset cannot split them.
    row = db.execute("SELECT data FROM sessions WHERE id=?", (session_id,)).fetchone()
    if not row or json.loads(row[0]).get("identity_verified") is not True:
        return {"found": False, "reason": "identity_verification_required"}
    context = db.execute(
        "SELECT tenant_id,portfolio_id,customer_id,debt_id FROM session_contexts WHERE session_id=?",
        (session_id,),
    ).fetchone()
    if context:
        rows = db.execute(
            """SELECT a.data FROM payment_agreements a JOIN session_contexts s
               ON s.session_id=a.origin_session_id
               WHERE (s.tenant_id,s.portfolio_id,s.customer_id,s.debt_id)=(?,?,?,?)
                 AND (?='' OR a.agreement_id=?) ORDER BY a.agreement_id LIMIT 21""",
            (*context, agreement_id, agreement_id),
        ).fetchall()
    else:
        # Playground fixtures do not establish cross-session customer ownership.
        rows = db.execute(
            """SELECT data FROM payment_agreements WHERE origin_session_id=?
               AND (?='' OR agreement_id=?) ORDER BY agreement_id LIMIT 21""",
            (session_id, agreement_id, agreement_id),
        ).fetchall()
    if not rows:
        return {"found": False, "reason": "boleto_not_found"}
    agreements = [json.loads(row[0]) for row in rows]
    if len(agreements) > 1:
        return {
            "found": False,
            "reason": "agreement_selection_required",
            "agreements": [
                {key: a[key] for key in ("agreement_id", "installments", "status")}
                for a in agreements[:20]
            ],
            "has_more": len(agreements) > 20,
        }
    agreement = agreements[0]
    if agreement.get("status") not in {"created", "payment_pending"}:
        return {
            "found": False,
            "reason": "agreement_not_payable",
            "status": agreement.get("status"),
        }
    payments = [
        json.loads(row[0])
        for row in db.execute(
            """SELECT data FROM payment_instructions WHERE agreement_id=? AND method='boleto'
               AND (? IS NULL OR installment_number=?) ORDER BY installment_number LIMIT 21""",
            (agreement["agreement_id"], installment_number, installment_number),
        ).fetchall()
    ]
    if not payments:
        return {"found": False, "reason": "boleto_not_issued"}
    if len(payments) > 1:
        return {
            "found": False,
            "reason": "installment_selection_required",
            "agreement_id": agreement["agreement_id"],
            "installments": [
                {key: p[key] for key in ("installment_number", "amount", "status")}
                for p in payments[:20]
            ],
            "has_more": len(payments) > 20,
        }
    payment = payments[0]
    if payment.get("status") != "pending":
        return {
            "found": False,
            "reason": "payment_not_payable",
            "status": payment.get("status"),
        }
    if (
        payment.get("is_simulation") is not True
        or agreement.get("is_simulation") is not True
    ):
        return {"found": False, "reason": "real_boleto_not_supported"}
    due_date = payment.get("due_date")
    if (
        due_date
        and date.fromisoformat(due_date)
        < datetime.now(ZoneInfo("America/Sao_Paulo")).date()
    ):
        return {"found": False, "reason": "boleto_reissue_required"}
    return {
        "found": True,
        "payment": {
            key: payment[key]
            for key in (
                "payment_id",
                "agreement_id",
                "method",
                "installment_number",
                "amount",
                "status",
                "payment_code",
                "is_simulation",
            )
        },
        "due_date": due_date,
        "is_down_payment": payment.get("is_down_payment", False),
        "due_date_available": bool(due_date),
    }
