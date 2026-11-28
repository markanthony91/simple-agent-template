"""Use separate interpreters and filesystem roots with the same test PostgreSQL."""

import hashlib
import json
import os
import shutil
import subprocess
import sys
from uuid import uuid4

import psycopg
import pytest

from scripts.apply_postgres_migrations import main as migrate
from simple_agent.services.okf_store import PersistentOKFStore
from simple_agent.services.session_store import SessionStore
from simple_agent.services.simulator_store import DEFAULT_FIXTURE, SimulatorStore
from simple_agent.services.tool_registry import ToolRegistry

DOC = "GLOBAL/guia.md"
ROOTS = {"OKF_DATA_ROOT": "okf", "SIMULATOR_ROOT": "sim", "TOOL_REGISTRY_ROOT": "tools"}


def bundle(word):
    return {
        "index.md": "# Index",
        "GLOBAL/guia.md": f"---\ntype: Concept\n---\n# Guia\nProtocolo {word}\n",
    }


def probe(keys):
    from simple_agent.tools.okf_tools import okf_read, okf_search
    from tests.unit_tests.test_collection_identity_gates import runtime

    reads = []
    for key, word in keys:
        rt = runtime(key)
        reads.append(
            (
                okf_search.func(query=word, scope="GLOBAL", runtime=rt),
                okf_read.func(path=DOC, runtime=rt),
            )
        )
    return {
        "reads": reads,
        "enabled": sorted(ToolRegistry().enabled_names()),
        "fixture": SimulatorStore.for_portfolio(7).load(),
        "active": PersistentOKFStore().active_bundle_id(),
    }


def test_two_filesystems_pin_old_and_new_until_one_receives_admin_writes(
    monkeypatch, tmp_path
):
    dsn = os.getenv("OSS_REDIS_TEST_DATABASE_URL")
    if not dsn:
        pytest.skip("requires disposable PostgreSQL")
    a, b = tmp_path / "A", tmp_path / "B"
    for var, directory in ROOTS.items():
        monkeypatch.setenv(var, str(a / directory))
    monkeypatch.setenv("SESSION_BACKEND", "postgres")
    monkeypatch.setenv("SESSION_DATABASE_URL", dsn)
    migrate()
    store = PersistentOKFStore()
    SimulatorStore().load()
    SimulatorStore.for_portfolio(7).save(DEFAULT_FIXTURE)
    ToolRegistry().set_enabled("calculator", False)
    prefix = f"replica-{uuid4()}"
    words = ["ametista", "safira"]
    sessions = []
    hashes = {}
    for word in words:
        files = bundle(word)
        release = store.import_bundle(word, "0.2", files)["bundle_id"]
        for replica in ("A", "B"):
            key = f"{prefix}-{replica}-{word}"
            SessionStore().ensure_portfolio(key, 7, "synthetic")
            sessions.append((key, word))
            hashes[key] = (release, hashlib.sha256(files[DOC].encode()).hexdigest())
    shutil.copytree(a, b)

    def run(root, command, args=(), check=True):
        env = {**os.environ, **{k: str(root / v) for k, v in ROOTS.items()}}
        return subprocess.run(
            [sys.executable, *command, *args],
            env=env,
            capture_output=True,
            text=True,
            timeout=45,
            check=check,
        )

    def read(root, pairs):
        return json.loads(
            run(
                root,
                ["-m", "tests.integration_tests.test_independent_replica_storage"],
                [json.dumps(pairs)],
            ).stdout
        )

    first_a = read(a, sessions[::2])
    first_b = read(b, sessions[1::2])
    assert first_a == first_b
    assert first_a["active"] == release and "calculator" not in first_a["enabled"]
    assert first_a["fixture"] == SimulatorStore.for_portfolio(7).load()
    for (search, text), word in zip(first_a["reads"], words, strict=True):
        assert DOC in search and word in search and word in text
    with psycopg.connect(dsn) as db:
        rows = db.execute(
            "SELECT session_id,snapshot_id,content_hash FROM okf.receipts WHERE session_id=ANY(%s) AND path=%s",
            (list(hashes), DOC),
        ).fetchall()
    assert {key: (snap, digest) for key, snap, digest in rows} == hashes
    assert read(b, sessions[::2]) == first_a

    auditor = ["scripts/audit_replica_storage.py"]
    manifest = tmp_path / "source.json"
    manifest.write_text(run(a, auditor).stdout)
    assert (
        json.loads(run(b, auditor, ["--compare", str(manifest)]).stdout)[
            "different_trees"
        ]
        == []
    )

    from simple_agent import admin_graph_v2 as admin

    monkeypatch.setattr(admin, "store", store)
    monkeypatch.setattr(admin, "registry", ToolRegistry())
    edits = [
        {"operation": "set_tool_enabled", "tool_name": "calculator", "enabled": True},
        {
            "operation": "save_simulator_fixture",
            "scope_id": 7,
            "fixture": {**DEFAULT_FIXTURE, "customer_id": "SYNTHETIC-A"},
        },
        {
            "operation": "import_bundle",
            "approved": True,
            "bundle_name": "third",
            "files": bundle("rubi"),
        },
    ]
    for edit in edits:
        assert not admin.execute(edit)["error"]
    newest = f"{prefix}-newest"
    SessionStore().ensure_portfolio(newest, 7, "synthetic")
    after_a, after_b = read(a, [(newest, "rubi")]), read(b, [(newest, "rubi")])
    assert after_a["active"] != after_b["active"] == release
    assert after_a["fixture"]["customer_id"] == "SYNTHETIC-A"
    assert after_b["fixture"] == first_b["fixture"]
    assert "calculator" in after_a["enabled"] and "calculator" not in after_b["enabled"]
    assert "rubi" in after_a["reads"][0][1]
    assert all(
        json.loads(output)["reason"] == "knowledge_lookup_failed"
        for output in after_b["reads"][0]
    )
    manifest.write_text(run(a, auditor).stdout)
    drift = run(b, auditor, ["--compare", str(manifest)], check=False)
    assert drift.returncode == 1
    assert json.loads(drift.stdout)["different_trees"] == ["okf", "simulator", "tools"]


if __name__ == "__main__":
    print(json.dumps(probe(json.loads(sys.argv[1]))))
