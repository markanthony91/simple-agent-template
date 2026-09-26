import json
from concurrent.futures import ThreadPoolExecutor
from contextvars import copy_context
from types import SimpleNamespace

import pytest

from simple_agent.tool_timing import (
    capture_timing,
    count_event,
    timed_phase,
    timing_summary,
)
from simple_agent.services.session_store import SessionStore
from simple_agent.tools import okf_tools
from simple_agent.tool_middleware import filter_enabled_tools


def test_timing_propagates_to_executor_and_resets_after_failure():
    assert timing_summary() == {}
    with capture_timing():
        with ThreadPoolExecutor(max_workers=1) as pool:

            def worker():
                with timed_phase("worker"):
                    count_event("calls")

            pool.submit(copy_context().run, worker).result(timeout=2)
        assert timing_summary()["counters"] == {"calls": 1}
        with pytest.raises(ValueError), capture_timing():
            count_event("inner")
            raise ValueError("synthetic")
        assert timing_summary()["counters"] == {"calls": 1}
    assert timing_summary() == {}
    with timed_phase("disabled"):
        count_event("disabled")
    assert timing_summary() == {}


def test_concurrent_calls_do_not_share_measurements():
    def worker(name):
        with capture_timing():
            with timed_phase(name):
                count_event(name)
            return timing_summary()

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(worker, ["a", "b"]))
    assert results[0]["counters"] == {"a": 1}
    assert results[1]["counters"] == {"b": 1}


def test_logs_include_phases_and_keep_search_distinct_from_read_receipt(
    isolated, caplog
):
    isolated.import_bundle(
        "timing",
        "0.2",
        {
            "index.md": "# Index\n[Policy](policy.md)",
            "policy.md": "---\ntype: Policy\n---\n# Policy\nSynthetic rule.",
        },
    )
    rt = SimpleNamespace(config={"configurable": {"thread_id": "timing-thread"}})
    SessionStore().read("timing-thread")
    caplog.set_level("INFO", logger="simple_agent.tools")
    for call_id, name, kwargs in [
        ("search", "okf_search", {"query": "Synthetic"}),
        ("read", "okf_read", {"path": "policy.md"}),
    ]:
        request = SimpleNamespace(
            tool_call={"name": name, "id": call_id, "args": kwargs}
        )
        tool = getattr(okf_tools, name)
        result = filter_enabled_tools.wrap_tool_call(
            request, lambda _: tool.func(runtime=rt, **kwargs)
        )
        assert "Synthetic" in result
        if name == "okf_search":
            assert not SessionStore().read("timing-thread")["receipts"]
    assert SessionStore().read("timing-thread")["receipts"]["policy.md"]["hash"]
    logs = [
        json.loads(r.message) for r in caplog.records if r.name == "simple_agent.tools"
    ]
    completed = [row for row in logs if row["status"] == "success"]
    assert len(completed) == 2
    search, read = completed
    assert search["counters"]["okf_cache_miss"] == 1
    assert "okf_index_build" in search["phases_ms"]
    for phase in (
        "tool_execution",
        "session_write_wait",
        "session_save",
        "session_commit",
        "okf_receipt",
    ):
        assert read["phases_ms"][phase] >= 0
    assert read["duration_ms"] >= read["phases_ms"]["tool_execution"] - 0.01
    assert (
        "runtime"
        not in okf_tools.okf_read.tool_call_schema.model_json_schema()["properties"]
    )


def test_timing_is_logged_for_failures_and_context_cleared(caplog):
    caplog.set_level("INFO", logger="simple_agent.tools")
    req = SimpleNamespace(tool_call={"name": "okf_read", "id": "failure", "args": {}})

    def fail(_):
        with timed_phase("synthetic_phase"):
            raise RuntimeError("synthetic_error")

    with pytest.raises(RuntimeError):
        filter_enabled_tools.wrap_tool_call(req, fail)
    event = json.loads(caplog.records[-1].message)
    assert event["status"] == "error"
    assert "synthetic_phase" in event["phases_ms"]
    assert timing_summary() == {}
