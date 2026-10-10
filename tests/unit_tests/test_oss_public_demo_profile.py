import asyncio
import json
from contextlib import nullcontext
from types import SimpleNamespace

from simple_agent import oss_runtime


def test_public_demo_profile_is_pinned_to_assistant_scope(monkeypatch):
    pinned = []

    class DB:
        def execute(self, _sql, args):
            return SimpleNamespace(
                fetchone=lambda: {
                    "thread_id": args[0],
                    "metadata": args[1].obj,
                    "status": "idle",
                }
            )

    class Store:
        def ensure_portfolio(self, *args, **kwargs):
            pinned.append((args, kwargs))

    class Request:
        async def json(self):
            return {
                "thread_id": "00000000-0000-4000-8000-000000000099",
                "metadata": {
                    "assistant_id": "00000000-0000-4000-8000-000000000002",
                    "zerai_scope_id": "2",
                    "demo_session_id": "1" * 32,
                },
                "demo_profile": {
                    "full_name": "Mariane",
                    "current_amount": "456.00",
                    "days_overdue": 60,
                },
            }

    monkeypatch.setattr(oss_runtime, "_db", lambda: nullcontext(DB()))
    monkeypatch.setattr(oss_runtime, "_thread", lambda _db, _id: None)
    monkeypatch.setattr(
        oss_runtime,
        "_assistant",
        lambda _db, _id: {
            "context": {"portfolio_context": {"scope_id": "2", "tenant_id": "usedigi"}}
        },
    )
    monkeypatch.setattr(oss_runtime, "PostgresSessionStore", Store)
    monkeypatch.setattr(oss_runtime, "portfolio_okf_configured", lambda: False)
    request = Request()

    response = asyncio.run(oss_runtime.thread_create(request))
    assert response.status_code == 200
    assert json.loads(response.body)["metadata"]["zerai_scope_id"] == "2"
    assert pinned[0][0] == ("00000000-0000-4000-8000-000000000099", 2, "usedigi")
    assert pinned[0][1]["demo_profile"] == {
        "full_name": "Mariane",
        "current_amount": "456.00",
        "days_overdue": 60,
    }

    async def wrong_scope():
        body = await Request().json()
        body["metadata"]["zerai_scope_id"] = "1"
        return body

    request.json = wrong_scope
    assert asyncio.run(oss_runtime.thread_create(request)).status_code == 400
    assert len(pinned) == 1
