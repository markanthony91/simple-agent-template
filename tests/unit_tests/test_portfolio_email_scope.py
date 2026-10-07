import pytest

from simple_agent.services import channel_console
from simple_agent.tools import payment_tools


def test_portfolio_catalog_never_falls_back_to_another_scope(monkeypatch):
    calls = []

    def catalog(path, payload=None, timeout=15, scope_id=1):
        calls.append((path, scope_id))
        return {
            "scope_id": scope_id,
            "scope_revision": 2,
            "channels": [{
                "channel": "email", "enabled": True,
                "template_id": "template", "template_revision": 1,
                "required": [],
            }],
        }

    monkeypatch.setattr(payment_tools, "request_json", catalog)
    payment_tools._email_plan({}, 2)
    assert calls == [("/api/engine/v1/channels", 2)]
    def wrong_scope(*args, **kwargs):
        response = catalog(*args, **kwargs)
        response["scope_id"] = 1
        return response

    monkeypatch.setattr(payment_tools, "request_json", wrong_scope)
    with pytest.raises(channel_console.ChannelConsoleError, match="email_catalog_scope_mismatch"):
        payment_tools._email_plan({}, 2)


def test_portfolio_token_has_no_legacy_fallback(monkeypatch):
    monkeypatch.setenv("CHANNEL_CONSOLE_URL", "https://channels.example")
    monkeypatch.setenv("CHANNEL_CONSOLE_AGENT_RUNTIME_TOKEN", "legacy-token")
    monkeypatch.delenv("CHANNEL_CONSOLE_RUNTIME_TOKEN_SCOPE_2", raising=False)
    with pytest.raises(channel_console.ChannelConsoleError, match="channel_console_not_configured"):
        channel_console.request_json("/api/engine/v1/channels", scope_id=2)
