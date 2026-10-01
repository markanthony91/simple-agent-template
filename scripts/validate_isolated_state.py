"""Copy two anonymized SQLite examples into the disconnected Railway PostgreSQL.

The source is opened read-only. Only allowlisted fields leave its container.
No application configuration is changed.
"""

import base64
import json
import re
import shlex
import sqlite3
import subprocess
import sys
from pathlib import Path


PROJECT = "511a294c-8d6a-4906-bd26-e8e33011eac5"
ENVIRONMENT = "8830dd97-8668-467d-b2f5-6ebcb8807969"
SOURCE = "861cf8e9-935f-4673-baf0-6bb438eac5fb"
TARGET = "e1d98011-cd52-4005-866d-f863a99871a5"
PREFIX = "isolated-sample-20260930"


def build_sample(connection):
    """Use real record shape and policy fields, replacing all identifying values."""
    query = """
        SELECT sc.customer_id, s.data, d.product, d.days_overdue,
               d.eligibility, d.identity_policy, pa.data,
               pi.method, pi.installment_number
        FROM session_contexts sc
        JOIN sessions s ON s.id = sc.session_id
        JOIN debts d ON d.id = sc.debt_id
        JOIN payment_agreements pa ON pa.origin_session_id = sc.session_id
        JOIN payment_instructions pi ON pi.agreement_id = pa.agreement_id
        WHERE pi.method = ? AND sc.customer_id <> ?
        ORDER BY sc.session_id LIMIT 1
    """
    selected = []
    for method in ("pix", "boleto"):
        row = connection.execute(
            query, (method, selected[0][0] if selected else "")
        ).fetchone()
        if row is None:
            raise ValueError(f"no linked {method} example with a distinct customer")
        selected.append(row)

    examples = []
    for number, row in enumerate(selected, 1):
        _, state_text, product, days_overdue, eligibility_text, policy_text, agreement_text, method, installment_number = row
        state = json.loads(state_text)
        agreement = json.loads(agreement_text)
        eligibility = json.loads(eligibility_text)
        policy = json.loads(policy_text)
        if not re.fullmatch(r"[a-z0-9_]{1,80}", product):
            raise ValueError("product is not a safe catalog slug")
        if method not in ("pix", "boleto") or not 1 <= installment_number <= 360:
            raise ValueError("invalid payment example")
        examples.append({
            "n": number,
            "product": product,
            "days_overdue": days_overdue,
            "eligibility": {key: eligibility[key] for key in (
                "can_negotiate", "max_installments", "max_discount_percentage"
            ) if key in eligibility},
            "identity_policy": {key: policy[key] for key in (
                "cpf_mode", "secondary", "max_attempts"
            ) if key in policy},
            "state": {
                "identity_verified": bool(state.get("identity_verified")),
                "offers": {}, "agreements": {}, "payments": {},
                "deliveries": {}, "receipts": {},
                "sample_only": True,
            },
            "agreement": {
                "created": bool(agreement.get("created")),
                "payment_type": agreement.get("payment_type"),
                "installments": agreement.get("installments"),
                "is_simulation": bool(agreement.get("is_simulation")),
                "sample_only": True,
            },
            "method": method,
            "installment_number": installment_number,
        })
    return examples


def sql_literal(value):
    return "'" + str(value).replace("'", "''") + "'"


def sql_json(value):
    return sql_literal(json.dumps(value, ensure_ascii=True)) + "::jsonb"


def make_sql(examples):
    if len(examples) != 2 or {e["method"] for e in examples} != {"pix", "boleto"}:
        raise ValueError("expected one PIX and one boleto example")
    lines = ["BEGIN;", "SET LOCAL statement_timeout = '15s';"]
    tenant = PREFIX + "-tenant"
    portfolio = PREFIX + "-portfolio"
    lines.append(f"INSERT INTO runtime.tenants VALUES ({sql_literal(tenant)}, 'Anonymized validation', now());")
    lines.append(f"INSERT INTO runtime.portfolios VALUES ({sql_literal(portfolio)}, {sql_literal(tenant)}, 'Anonymized validation', 'Anonymized validation', now());")
    for e in examples:
        n = e["n"]
        customer = f"{PREFIX}-customer-{n}"
        debt = f"{PREFIX}-debt-{n}"
        session = f"{PREFIX}-session-{n}"
        agreement = f"{PREFIX}-agreement-{n}"
        payment = f"{PREFIX}-payment-{n}"
        debt_data = {"debt_id": debt, "current_amount": "100.00", "original_amount": "100.00", "days_overdue": e["days_overdue"], "status": "sample"}
        agreement_data = {**e["agreement"], "agreement_id": agreement, "customer_id": customer, "debt_id": debt, "negotiated_amount": "100.00"}
        payment_data = {"payment_id": payment, "agreement_id": agreement, "method": e["method"], "installment_number": e["installment_number"], "amount": "100.00", "payment_code": "SAMPLE-DO-NOT-PAY", "sample_only": True}
        lines.extend([
            f"INSERT INTO runtime.customers VALUES ({sql_literal(customer)}, {sql_literal(tenant)}, 'Sample Customer', '000', '000', '2000-01-01', now());",
            f"INSERT INTO runtime.debts VALUES ({sql_literal(debt)}, {sql_literal(tenant)}, {sql_literal(portfolio)}, {sql_literal(customer)}, {sql_literal(e['product'])}, '100.00', {int(e['days_overdue'])}, {sql_json(debt_data)}, {sql_json(e['eligibility'])}, {sql_json(e['identity_policy'])}, now());",
            f"INSERT INTO runtime.sessions(id, tenant_id, portfolio_id, customer_id, debt_id, state) VALUES ({sql_literal(session)}, {sql_literal(tenant)}, {sql_literal(portfolio)}, {sql_literal(customer)}, {sql_literal(debt)}, {sql_json(e['state'])});",
            f"INSERT INTO runtime.session_contexts VALUES ({sql_literal(session)}, {sql_literal(tenant)}, {sql_literal(portfolio)}, {sql_literal(customer)}, {sql_literal(debt)}, now());",
            f"INSERT INTO runtime.payment_agreements(agreement_id, origin_session_id, data) VALUES ({sql_literal(agreement)}, {sql_literal(session)}, {sql_json(agreement_data)});",
            f"INSERT INTO runtime.payment_instructions(payment_id, agreement_id, method, installment_number, data) VALUES ({sql_literal(payment)}, {sql_literal(agreement)}, {sql_literal(e['method'])}, {int(e['installment_number'])}, {sql_json(payment_data)});",
        ])
    lines.extend([
        f"DO $$ BEGIN ASSERT (SELECT count(*) FROM runtime.session_contexts WHERE tenant_id={sql_literal(tenant)})=2; ASSERT (SELECT count(*) FROM runtime.payment_instructions WHERE payment_id LIKE {sql_literal(PREFIX + '-payment-%')})=2; END $$;",
        "COMMIT;",
    ])
    return "\n".join(lines)


def railway_ssh(service, command):
    return ["railway", "ssh", "--project", PROJECT, "--environment", ENVIRONMENT,
            "--service", service, "sh", "-lc", command]


def run():
    script = base64.b64encode(Path(__file__).read_bytes()).decode("ascii")
    remote_python = f"import base64;exec(compile(base64.b64decode('{script}'),'<sample>','exec'))"
    source_command = f"python -c {shlex.quote(remote_python)} --source"
    source = subprocess.run(railway_ssh(SOURCE, source_command), capture_output=True, text=True, timeout=45, check=True)
    examples = json.loads(source.stdout[source.stdout.index("["):])
    target_command = "psql -X -v ON_ERROR_STOP=1 -U \"$POSTGRES_USER\" -d \"$POSTGRES_DB\" -c " + shlex.quote(make_sql(examples))
    target = subprocess.run(railway_ssh(TARGET, target_command), capture_output=True, text=True, timeout=45, check=True)
    if "COMMIT" not in target.stdout:
        raise RuntimeError("PostgreSQL transaction did not commit")
    print("PASS: 2 anonymized linked samples copied (PIX and boleto); PostgreSQL transaction committed")


if __name__ == "__main__":
    if sys.argv[1:] == ["--source"]:
        db = sqlite3.connect("file:/data/sessions/sessions.sqlite3?mode=ro", uri=True)
        print(json.dumps(build_sample(db), ensure_ascii=True))
    elif sys.argv[1:] == ["--run"]:
        run()
    else:
        raise SystemExit("usage: validate_isolated_state.py --run")
