import json
import sqlite3
from types import SimpleNamespace

import pytest
import httpx
from langchain_core.messages import AIMessage, HumanMessage
from langgraph.graph.message import add_messages

from simple_agent.services.future_demo import (
    channel_creditor,
    create_future_demo_session,
)
from simple_agent.services.session_store import SessionStore
from simple_agent.services.simulator_store import SimulatorStore
from simple_agent.tool_middleware import (
    RESET_DEMO_REPLY,
    RESET_DEMO_UNAVAILABLE,
    demo_reset,
    is_reset_demo_command,
)
from simple_agent.tools.collection_tools import get_customer, verify_customer_identity


FORM = {
    "full_name": "Marcelo de Teste",
    "cpf": "529.982.247-25",
    "phone": "+5511949994528",
    "amount": "850.00",
    "days_overdue": 42,
}


def runtime(key: str, call: str = "call-1", text: str = ""):
    return SimpleNamespace(
        config={"configurable": {"thread_id": key}},
        tool_call_id=call,
        state={"messages": [HumanMessage(content=text)]},
    )


def test_form_creates_isolated_tool_session_without_changing_playground(
    isolated, monkeypatch, tmp_path
):
    session_root = tmp_path / "sessions"
    simulator_root = tmp_path / "simulator"
    monkeypatch.setenv("SESSION_ROOT", str(session_root))
    monkeypatch.setenv("SIMULATOR_ROOT", str(simulator_root))
    simulator = SimulatorStore(simulator_root)
    original = simulator.file.read_bytes()

    result = create_future_demo_session(
        "future-form-thread",
        FORM,
        creditor_loader=lambda: "Credor cadastrado em Canais",
        session_store=SessionStore(session_root),
        simulator_store=simulator,
    )

    assert result == {
        "thread_id": "future-form-thread",
        "creditor": "Credor cadastrado em Canais",
        "cpf_masked": "***.***.***-25",
        "phone_masked": "***4528",
        "amount": "850.00",
        "days_overdue": 42,
        "identity_policy": "cpf_first3",
        "created": True,
    }
    assert simulator.file.read_bytes() == original
    with SessionStore(session_root).transaction("future-form-thread") as state:
        fixture = state["fixture"]
        assert fixture["full_name"] == FORM["full_name"]
        assert fixture["phone"] == FORM["phone"]
        assert fixture["institution"] == "Credor cadastrado em Canais"
        assert fixture["creditor_name"] == "Credor cadastrado em Canais"
        assert fixture["debt"]["current_amount"] == "850.00"
        assert fixture["debt"]["days_overdue"] == 42
        assert fixture["identity_policy"] == {
            "cpf_mode": "first3",
            "secondary": "none",
            "max_attempts": 3,
        }

    verified = json.loads(
        verify_customer_identity.func(
            runtime=runtime("future-form-thread", text="529"), cpf="529"
        )
    )
    assert verified["verified"] is True
    customer = json.loads(
        get_customer.func(runtime=runtime("future-form-thread", "call-2"))
    )
    assert customer["institution"] == "Credor cadastrado em Canais"
    assert customer["phone"] == "***4528"
    assert customer["debt"]["days_overdue"] == 42
    assert customer["debt"]["current_amount"] == "850.00"

    replay = create_future_demo_session(
        "future-form-thread",
        FORM,
        creditor_loader=lambda: "Credor cadastrado em Canais",
        session_store=SessionStore(session_root),
        simulator_store=simulator,
    )
    assert replay["created"] is False

    with sqlite3.connect(SessionStore(session_root).database) as database:
        assert database.execute("select count(*) from tenants").fetchone()[0] == 1
        assert database.execute("select count(*) from portfolios").fetchone()[0] == 1
        assert database.execute("select count(*) from customers").fetchone()[0] == 1
        assert database.execute("select count(*) from debts").fetchone()[0] == 1
        assert (
            database.execute("select count(*) from session_contexts").fetchone()[0] == 1
        )
        assert database.execute("pragma foreign_key_check").fetchall() == []
        stored = json.loads(
            database.execute(
                "select data from sessions where id='future-form-thread'"
            ).fetchone()[0]
        )
        assert "fixture" not in stored

    with pytest.raises(ValueError, match="session_already_exists"):
        create_future_demo_session(
            "future-form-thread",
            {**FORM, "amount": "851.00"},
            creditor_loader=lambda: "Credor cadastrado em Canais",
            session_store=SessionStore(session_root),
            simulator_store=simulator,
        )


def test_schema_upgrade_preserves_existing_playground_sessions(isolated, tmp_path):
    root = tmp_path / "legacy-sessions"
    root.mkdir()
    database = root / "sessions.sqlite3"
    fixture = SimulatorStore(tmp_path / "legacy-simulator").load()
    state = {
        "fixture": fixture,
        "identity_verified": False,
        "offers": {},
        "agreements": {},
        "payments": {},
        "deliveries": {},
        "receipts": {},
        "snapshot_id": "legacy-snapshot",
    }
    with sqlite3.connect(database) as connection:
        connection.execute(
            "create table sessions (id text primary key, data text not null)"
        )
        connection.execute(
            "insert into sessions(id,data) values(?,?)",
            ("legacy-thread", json.dumps(state)),
        )

    store = SessionStore(root)
    with store.transaction("legacy-thread") as preserved:
        assert preserved["fixture"] == fixture
        assert preserved["snapshot_id"] == "legacy-snapshot"
    with sqlite3.connect(database) as connection:
        assert connection.execute("select count(*) from sessions").fetchone()[0] == 1
        assert connection.execute("select count(*) from tenants").fetchone()[0] == 0


def test_direct_whatsapp_session_has_no_customer_or_debt(isolated, tmp_path):
    store = SessionStore(tmp_path / "unbound-sessions")
    assert store.ensure_unbound("whatsapp-direct") is True
    assert store.ensure_unbound("whatsapp-direct") is False
    with store.transaction("whatsapp-direct") as state:
        assert state["unbound_session"] is True
        assert "fixture" not in state
        assert state["identity_verified"] is False

    with pytest.raises(ValueError, match="session_already_exists"):
        create_future_demo_session(
            "whatsapp-direct",
            FORM,
            creditor_loader=lambda: "Credor",
            session_store=store,
            simulator_store=SimulatorStore(tmp_path / "simulator-unbound"),
        )


def test_existing_legacy_session_must_reset_before_whatsapp(isolated, tmp_path):
    store = SessionStore(tmp_path / "legacy-whatsapp")
    fixture = SimulatorStore(tmp_path / "legacy-simulator").load()
    store.create("legacy-thread", fixture)

    with pytest.raises(ValueError, match="whatsapp_session_requires_reset"):
        store.ensure_unbound("legacy-thread")
    with store.transaction("legacy-thread") as state:
        assert state["fixture"] == fixture
        assert "unbound_session" not in state


@pytest.mark.parametrize(
    "change",
    [
        {"full_name": "x"},
        {"cpf": "111.111.111-11"},
        {"phone": "11949994528"},
        {"amount": "0"},
        {"amount": "850.001"},
        {"days_overdue": -1},
        {"days_overdue": True},
    ],
)
def test_form_rejects_invalid_data_without_writing(isolated, tmp_path, change):
    payload = {**FORM, **change}
    sessions = SessionStore(tmp_path / "sessions")
    with pytest.raises(ValueError, match="invalid_demo_form"):
        create_future_demo_session(
            "invalid-thread",
            payload,
            creditor_loader=lambda: "Credor",
            session_store=sessions,
            simulator_store=SimulatorStore(tmp_path / "simulator"),
        )
    assert sessions.database.stat().st_size > 0
    import sqlite3

    with sqlite3.connect(sessions.database) as database:
        assert database.execute("select count(*) from sessions").fetchone()[0] == 0


def test_channel_creditor_uses_server_configuration(monkeypatch):
    captured = {}

    def open_request(method, url, **kwargs):
        captured["authorization"] = kwargs["headers"]["Authorization"]
        captured["url"] = url
        captured["timeout"] = kwargs["timeout"]
        captured["follow_redirects"] = kwargs["follow_redirects"]
        return httpx.Response(
            200,
            json={"creditor_name": "Fastpay", "portfolio_name": "Will Bank"},
            request=httpx.Request(method, url),
        )

    monkeypatch.setenv("CHANNEL_CONSOLE_URL", "channels.example.test")
    monkeypatch.setenv("CHANNEL_CONSOLE_ENGINE_TOKEN", "synthetic-token")
    monkeypatch.setattr("httpx.request", open_request)
    assert channel_creditor() == "Will Bank"
    assert captured == {
        "authorization": "Bearer synthetic-token",
        "url": "https://channels.example.test/api/engine/v1/channels",
        "timeout": 5,
        "follow_redirects": False,
    }


def test_reset_demo_clears_operational_state_and_active_history(
    isolated, monkeypatch, tmp_path
):
    session_root = tmp_path / "sessions"
    monkeypatch.setenv("SESSION_ROOT", str(session_root))
    sessions = SessionStore(session_root)
    create_future_demo_session(
        "demo-reset-thread",
        FORM,
        creditor_loader=lambda: "Credor",
        session_store=sessions,
        simulator_store=SimulatorStore(tmp_path / "simulator"),
    )
    with sessions.transaction("demo-reset-thread") as state:
        fixture = state["fixture"]
        snapshot = state["snapshot_id"]
        state.update(
            identity_verified=True,
            identity_attempts=2,
            debt_read=True,
            offers={"offer": {"value": "100.00"}},
            agreements={"agreement": {"status": "created"}},
            payments={"payment": {"status": "pending"}},
            deliveries={"delivery": {"status": "captured"}},
            receipts={"policy.md": {"hash": "synthetic"}},
        )

    monkeypatch.setattr(
        "simple_agent.tool_middleware.get_config",
        lambda: {"configurable": {"thread_id": "demo-reset-thread"}},
    )
    history = [
        HumanMessage(content="mensagem anterior", id="old-human"),
        AIMessage(content="resposta anterior", id="old-ai"),
        HumanMessage(content=" /RESET-DEMO\n", id="reset-command"),
    ]
    update = demo_reset.before_model({"messages": history}, None)

    assert update["jump_to"] == "end"
    messages = add_messages(history, update["messages"])
    assert len(messages) == 1
    assert messages[0].content == RESET_DEMO_REPLY
    with sessions.transaction("demo-reset-thread") as state:
        assert state["fixture"] == fixture
        assert state["snapshot_id"] == snapshot
        assert state["demo_session"] is True
        assert state["identity_verified"] is False
        assert state["offers"] == state["agreements"] == state["receipts"] == {}
        assert state["payments"] == state["deliveries"] == {}
        assert state["reset_count"] == 1
        assert state["last_reset_at"]
        assert "identity_attempts" not in state
        assert "debt_read" not in state


def test_reset_demo_is_unavailable_outside_future_demo(isolated, monkeypatch, tmp_path):
    session_root = tmp_path / "sessions"
    monkeypatch.setenv("SESSION_ROOT", str(session_root))
    sessions = SessionStore(session_root)
    sessions.create("playground-thread", SimulatorStore(tmp_path / "simulator").load())
    monkeypatch.setattr(
        "simple_agent.tool_middleware.get_config",
        lambda: {"configurable": {"thread_id": "playground-thread"}},
    )
    history = [HumanMessage(content="/reset-demo", id="reset-command")]

    update = demo_reset.before_model({"messages": history}, None)

    assert update == {
        "jump_to": "end",
        "messages": [AIMessage(content=RESET_DEMO_UNAVAILABLE)],
    }
    assert len(add_messages(history, update["messages"])) == 2
    with sessions.transaction("playground-thread") as state:
        assert "demo_session" not in state
        assert "reset_count" not in state


@pytest.mark.parametrize(
    ("content", "expected"),
    [
        ("/reset-demo", True),
        (" /RESET-DEMO\n", True),
        ("reset-demo", False),
        ("quero /reset-demo agora", False),
        ([{"type": "text", "text": "/reset-demo"}], True),
    ],
)
def test_reset_demo_requires_exact_command(content, expected):
    assert is_reset_demo_command(content) is expected
