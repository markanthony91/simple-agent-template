"""Regression check for configurable runtime queue polling."""

import hashlib
import importlib.util
from importlib.metadata import distribution
from pathlib import Path

MODULE = Path(__file__).parents[2] / "scripts" / "patch_runtime_queue_poll.py"
SPEC = importlib.util.spec_from_file_location("patch_runtime_queue_poll", MODULE)
assert SPEC and SPEC.loader
patcher = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(patcher)


def test_runtime_queue_patch_is_pinned_and_idempotent(tmp_path):
    package = distribution("langgraph-runtime-inmem")
    source = Path(package.locate_file("langgraph_runtime_inmem/ops.py"))
    target = tmp_path / "ops.py"
    target.write_bytes(source.read_bytes())

    patcher.apply_patch(target)
    patcher.apply_patch(target)

    assert hashlib.sha256(target.read_bytes()).hexdigest() == patcher.PATCHED
    assert "LANGGRAPH_QUEUE_POLL_SECONDS" in target.read_text()
