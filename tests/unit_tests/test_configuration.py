from langgraph.pregel import Pregel

from simple_agent.graph import calculator, graph, utc_now


def test_graph_compiles() -> None:
    assert isinstance(graph, Pregel)


def test_calculator_tool() -> None:
    result = calculator.invoke({"expression": "2 + 3 * 4"})
    assert result == "14"


def test_utc_now_tool() -> None:
    result = utc_now.invoke({})
    assert isinstance(result, str)
    assert "T" in result


def test_utc_now_legacy_name_returns_sao_paulo_even_across_midnight(monkeypatch):
    import importlib
    from datetime import datetime, timedelta

    module = importlib.import_module("simple_agent.graph")
    observed = []

    class Clock:
        @staticmethod
        def now(tz):
            observed.append(tz.key)
            return datetime.fromisoformat("2026-09-29T01:00:00+00:00").astimezone(tz)

    monkeypatch.setattr(module, "datetime", Clock)
    result = datetime.fromisoformat(utc_now.invoke({}))
    assert result.isoformat() == "2026-09-28T22:00:00-03:00"
    assert result.utcoffset() == timedelta(hours=-3)
    assert observed == ["America/Sao_Paulo"]
    assert "America/Sao_Paulo" in utc_now.description


def test_existing_registry_updates_legacy_clock_description_without_enabling(tmp_path):
    from simple_agent.services.tool_registry import ToolRegistry
    import json

    registry = ToolRegistry(tmp_path)
    data = json.loads(registry.registry_file.read_text())
    data["tools"]["utc_now"].update(
        description="Current UTC date and time.", enabled=False
    )
    registry.registry_file.write_text(json.dumps(data))
    entry = next(x for x in registry.list_tools() if x["name"] == "utc_now")
    assert "America/Sao_Paulo" in entry["description"] and entry["enabled"] is False
    data["tools"]["utc_now"]["description"] = "Custom operator description"
    registry.registry_file.write_text(json.dumps(data))
    assert (
        next(x for x in registry.list_tools() if x["name"] == "utc_now")["description"]
        == "Custom operator description"
    )
