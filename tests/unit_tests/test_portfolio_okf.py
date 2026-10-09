import io
import json
import zipfile
from types import SimpleNamespace

import pytest

from simple_agent.services.okf_store import PersistentOKFStore
from simple_agent.services.portfolio_okf import active_snapshot
from simple_agent.services.session_store import SessionStore


def test_new_portfolio_sessions_pin_activated_release_without_changing_old_chats(
    isolated, monkeypatch
):
    from simple_agent import tool_middleware
    from langchain.agents.middleware import ModelRequest
    from langgraph.runtime import Runtime
    from simple_agent import managed_graph

    versions = {"2": "release-a", "3": None}
    contents = {"release-a": "# Versão A", "release-b": "# Versão B"}
    archive_reads = []

    def urlopen(request, timeout):
        assert request.get_header("Authorization") == "Bearer synthetic-token"
        url = request.full_url
        scope = url.split("/portfolios/")[1].split("/")[0]
        if url.endswith("/status"):
            active = versions[scope]
            return io.BytesIO(
                json.dumps(
                    {
                        "data": {
                            "active": bool(active),
                            "active_bundle_id": active,
                        }
                    }
                ).encode()
            )
        release = url.split("/bundles/")[1].split("/")[0]
        archive_reads.append(release)
        output = io.BytesIO()
        with zipfile.ZipFile(output, "w") as archive:
            archive.writestr("index.md", "# Índice")
            archive.writestr("GLOBAL/index.md", "# Global")
            archive.writestr(
                "GLOBAL/atendimento.md",
                f"---\ntype: knowledge\n---\n{contents[release]}",
            )
        return io.BytesIO(output.getvalue())

    monkeypatch.setenv("PORTFOLIO_OKF_SERVICE_URL", "https://okf.invalid")
    monkeypatch.setenv("PORTFOLIO_OKF_SERVICE_TOKEN", "synthetic-token")
    monkeypatch.setattr(
        "urllib.request.build_opener", lambda *_: SimpleNamespace(open=urlopen)
    )
    thread = ["chat-a"]
    monkeypatch.setattr(
        tool_middleware,
        "get_config",
        lambda: {"configurable": {"thread_id": thread[0]}},
    )
    request = ModelRequest(
        model=managed_graph.create_llm(),
        messages=[],
        tools=[],
        runtime=Runtime(
            context={"portfolio_context": {"scope_id": 2, "tenant_id": "tenant-test"}}
        ),
        state={"messages": []},
    )
    tool_middleware.filter_enabled_tools._filtered_request(request)
    first = SessionStore().read("chat-a")["snapshot_id"]
    assert (
        "Versão A"
        in (
            PersistentOKFStore().bundle_root(first) / "GLOBAL/atendimento.md"
        ).read_text()
    )
    versions["2"] = "release-b"
    thread[0] = "chat-b"
    tool_middleware.filter_enabled_tools._filtered_request(request)
    second = SessionStore().read("chat-b")["snapshot_id"]
    assert second != first
    assert (
        "Versão B"
        in (
            PersistentOKFStore().bundle_root(second) / "GLOBAL/atendimento.md"
        ).read_text()
    )
    thread[0] = "chat-a"
    tool_middleware.filter_enabled_tools._filtered_request(request)
    assert SessionStore().read("chat-a")["snapshot_id"] == first
    assert archive_reads == ["release-a", "release-b"]

    request = request.override(
        runtime=Runtime(
            context={"portfolio_context": {"scope_id": 3, "tenant_id": "tenant-test"}}
        )
    )
    thread[0] = "chat-empty"
    tool_middleware.filter_enabled_tools._filtered_request(request)
    assert SessionStore().read("chat-empty")["snapshot_id"] is None


def test_portfolio_archive_rejects_unsafe_path_without_caching(isolated, monkeypatch):
    monkeypatch.setenv("PORTFOLIO_OKF_SERVICE_URL", "https://okf.invalid")
    monkeypatch.setenv("PORTFOLIO_OKF_SERVICE_TOKEN", "synthetic-token")

    def urlopen(request, timeout):
        if request.full_url.endswith("/status"):
            return io.BytesIO(
                json.dumps(
                    {"data": {"active": True, "active_bundle_id": "release-a"}}
                ).encode()
            )
        output = io.BytesIO()
        with zipfile.ZipFile(output, "w") as archive:
            archive.writestr("../secret.md", "bad")
        return io.BytesIO(output.getvalue())

    monkeypatch.setattr(
        "urllib.request.build_opener", lambda *_: SimpleNamespace(open=urlopen)
    )
    with pytest.raises(ValueError, match="Invalid OKF path"):
        active_snapshot(2, "tenant-test")
    assert not list(PersistentOKFStore().bundles_root.iterdir())
