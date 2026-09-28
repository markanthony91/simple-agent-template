"""Regression checks for checkpoint reads without production data."""

import os

os.environ.setdefault("DATABASE_URI", ":memory:")
os.environ.setdefault("REDIS_URI", "fake")
os.environ.setdefault("LANGGRAPH_RUNTIME_EDITION", "inmem")
os.environ.setdefault("LANGSMITH_LANGGRAPH_API_VARIANT", "local_dev")

from langgraph.checkpoint.memory import PersistentDict
from langgraph_runtime_inmem import _persistence, checkpoint


def test_history_view_reuses_loaded_maps_without_reloading(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    checkpoint.MEMORY = None
    _persistence.stop_flush_loop()
    _persistence._stores.clear()
    loads = 0
    original_load = PersistentDict.load

    def count_loads(store):
        nonlocal loads
        loads += 1
        return original_load(store)

    monkeypatch.setattr(PersistentDict, "load", count_loads)
    owner = checkpoint.Checkpointer()
    view = checkpoint.Checkpointer(unpack_hook=lambda _code, data: data)

    assert loads == 3
    assert view.storage is owner.storage
    assert view.writes is owner.writes
    assert view.blobs is owner.blobs
    assert not view.stack._exit_callbacks

    view.stack.close()
    _persistence.stop_flush_loop()
    owner.stack.close()
    checkpoint.MEMORY = None
    _persistence._stores.clear()
