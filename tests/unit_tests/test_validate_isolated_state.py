import importlib.util
import json
import sqlite3
from pathlib import Path


spec = importlib.util.spec_from_file_location(
    "validate_isolated_state",
    Path(__file__).resolve().parents[2] / "scripts" / "validate_isolated_state.py",
)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


def test_sample_keeps_relationships_and_discards_private_values():
    db = sqlite3.connect(":memory:")
    db.executescript("""
        CREATE TABLE session_contexts(session_id text, debt_id text, customer_id text);
        CREATE TABLE sessions(id text, data text);
        CREATE TABLE debts(id text, product text, days_overdue integer, eligibility text, identity_policy text);
        CREATE TABLE payment_agreements(agreement_id text, origin_session_id text, data text);
        CREATE TABLE payment_instructions(agreement_id text, method text, installment_number integer);
    """)
    secret = "PRIVATE_NAME_EMAIL_CPF"
    for n, method in enumerate(("pix", "boleto"), 1):
        db.execute("INSERT INTO session_contexts VALUES (?, ?, ?)", (f"s{n}", f"d{n}", f"c{n}"))
        db.execute("INSERT INTO sessions VALUES (?, ?)", (f"s{n}", json.dumps({"identity_verified": True, "fixture": {"name": secret}, "offers": {"unsafe": secret}})))
        db.execute("INSERT INTO debts VALUES (?, ?, ?, ?, ?)", (f"d{n}", "cartao_de_credito", 31, json.dumps({"can_negotiate": True, "private": secret}), json.dumps({"cpf_mode": "prefix3", "private": secret})))
        db.execute("INSERT INTO payment_agreements VALUES (?, ?, ?)", (f"a{n}", f"s{n}", json.dumps({"created": True, "payment_type": "cash" if method == "pix" else "installment", "installments": n, "is_simulation": True, "authorization_basis": secret})))
        db.execute("INSERT INTO payment_instructions VALUES (?, ?, ?)", (f"a{n}", method, n))
    examples = module.build_sample(db)
    sql = module.make_sql(examples)
    assert {example["method"] for example in examples} == {"pix", "boleto"}
    assert secret not in json.dumps(examples)
    assert secret not in sql
    assert "Sample Customer" in sql
    assert "SAMPLE-DO-NOT-PAY" in sql
    assert "'31'" not in sql  # overdue days remain numeric
