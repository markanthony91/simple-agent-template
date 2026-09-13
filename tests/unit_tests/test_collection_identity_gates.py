import json

from simple_agent.tools import collection_tools


class FakeStore:
    def __init__(self, fixture):
        self.fixture = fixture

    def load(self):
        return self.fixture

    def save(self, fixture):
        self.fixture = fixture

    def days_overdue(self, due_date: str) -> int:
        return 156


def _fixture():
    return {
        "customer_id": "CUS-001",
        "full_name": "João da Silva",
        "cpf": "12345678900",
        "birth_date": "1985-04-17",
        "institution": "FastPay",
        "product": "cartao_de_credito",
        "debt": {
            "debt_id": "DEBT-001",
            "current_amount": 5873.42,
            "due_date": "2026-04-10",
        },
        "eligibility": {
            "can_negotiate": True,
            "max_installments": 10,
            "max_discount_percentage": 20,
        },
        "_runtime": {},
    }


def test_get_customer_hides_financial_data_until_verified(monkeypatch):
    fake = FakeStore(_fixture())
    monkeypatch.setattr(collection_tools, "store", fake)

    payload = json.loads(collection_tools.get_customer.invoke({"cpf": "123.456.789-00"}))

    assert payload["found"] is True
    assert payload["identity_validated"] is False
    assert payload["financial_data_available"] is False
    assert "debt" not in payload
    assert "eligibility" not in payload
    assert "full_name" not in payload
    assert "birth_date" not in payload


def test_failed_secondary_factor_revokes_previous_verification(monkeypatch):
    fixture = _fixture()
    fixture["_runtime"] = {
        "identity_verified": True,
        "verification_id": "VER-OLD",
        "offers": {"OFF-OLD": {"status": "available"}},
    }
    fake = FakeStore(fixture)
    monkeypatch.setattr(collection_tools, "store", fake)

    payload = json.loads(
        collection_tools.verify_customer_identity.invoke(
            {"cpf": "12345678900", "birth_date": "17/04/1985"}
        )
    )

    assert payload == {"verified": False, "reason": "secondary_factor_not_matched"}
    assert fake.fixture["_runtime"]["identity_verified"] is False
    assert "verification_id" not in fake.fixture["_runtime"]
    assert fake.fixture["_runtime"]["offers"] == {}


def test_verified_customer_receives_debt_but_not_commercial_limits(monkeypatch):
    fake = FakeStore(_fixture())
    monkeypatch.setattr(collection_tools, "store", fake)

    verified = json.loads(
        collection_tools.verify_customer_identity.invoke(
            {"cpf": "12345678900", "full_name": "João da Silva"}
        )
    )
    assert verified["verified"] is True

    payload = json.loads(collection_tools.get_customer.invoke({"cpf": "12345678900"}))
    assert payload["identity_validated"] is True
    assert payload["debt"]["current_amount"] == 5873.42
    assert "eligibility" not in payload
    assert "birth_date" not in payload


def test_generate_offer_requires_verified_identity(monkeypatch):
    fake = FakeStore(_fixture())
    monkeypatch.setattr(collection_tools, "store", fake)

    payload = json.loads(
        collection_tools.generate_offer.invoke(
            {
                "payment_type": "installment",
                "installments": 6,
                "discount_percentage": 10,
            }
        )
    )

    assert payload == {"available": False, "reason": "identity_verification_required"}
