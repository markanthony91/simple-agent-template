"""Per-call timing only: no arguments, customer data or document content."""

from contextlib import contextmanager
from contextvars import ContextVar
from time import perf_counter
from functools import wraps
from typing import get_type_hints

_current: ContextVar[dict | None] = ContextVar("tool_timing", default=None)


@contextmanager
def capture_timing():
    measurements = {"phases_ms": {}, "counters": {}}
    token = _current.set(measurements)
    try:
        yield measurements
    finally:
        _current.reset(token)


@contextmanager
def timed_phase(name: str):
    measurements = _current.get()
    if measurements is None:
        yield
        return
    started = perf_counter()
    try:
        yield
    finally:
        phases = measurements["phases_ms"]
        phases[name] = phases.get(name, 0.0) + (perf_counter() - started) * 1000


def count_event(name: str, amount: int = 1):
    measurements = _current.get()
    if measurements is not None:
        counters = measurements["counters"]
        counters[name] = counters.get(name, 0) + amount


def timing_summary() -> dict:
    measurements = _current.get()
    if measurements is None:
        return {}
    return {
        "phases_ms": {k: round(v, 3) for k, v in measurements["phases_ms"].items()},
        "counters": dict(measurements["counters"]),
    }


def timed_tool(function):
    """Measure synchronous tool execution after executor dispatch, preserving its schema."""

    @wraps(function)
    def measured(*args, **kwargs):
        with timed_phase("tool_execution"):
            return function(*args, **kwargs)

    measured.__annotations__ = get_type_hints(function)
    return measured
