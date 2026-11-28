import json
import shutil
import sys

import pytest

from scripts.audit_replica_storage import fingerprint, main
from simple_agent.services.okf_store import PersistentOKFStore
from simple_agent.services.simulator_store import DEFAULT_FIXTURE, SimulatorStore
from simple_agent.services.tool_registry import ToolRegistry


def test_replica_restores_pinned_okf_scoped_fixture_and_disabled_tool(
    tmp_path, monkeypatch, capsys
):
    primary, replica = tmp_path / "primary", tmp_path / "replica"

    def point(root):
        for env, subdir in (
            ("OKF_DATA_ROOT", "okf"),
            ("SIMULATOR_ROOT", "simulator"),
            ("TOOL_REGISTRY_ROOT", "tools"),
        ):
            monkeypatch.setenv(env, str(root / subdir))

    point(primary)
    store = PersistentOKFStore()
    first = store.import_bundle("first", "0.2", {"index.md": "# Original"})["bundle_id"]
    active = store.import_bundle("second", "0.2", {"index.md": "# Current"})[
        "bundle_id"
    ]
    store.create_draft("draft")
    SimulatorStore.for_portfolio(7).save(DEFAULT_FIXTURE)
    ToolRegistry().set_enabled("calculator", False)
    monkeypatch.setattr(sys, "argv", ["audit"])
    assert main() == 0
    baseline = tmp_path / "report.json"
    baseline.write_text(capsys.readouterr().out)
    shutil.copytree(primary, replica)
    point(replica)
    monkeypatch.setattr(sys, "argv", ["audit", "--compare", str(baseline)])
    assert main() == 0
    assert PersistentOKFStore().active_bundle_id() == active
    assert (
        PersistentOKFStore().bundle_root(first) / "index.md"
    ).read_text() == "# Original"
    assert (
        SimulatorStore.for_portfolio(7).load()["customer_id"]
        == DEFAULT_FIXTURE["customer_id"]
    )
    assert "calculator" not in ToolRegistry().enabled_names()
    capsys.readouterr()
    ToolRegistry().set_enabled("calculator", True)
    assert main() == 1
    assert json.loads(capsys.readouterr().out)["different_trees"] == ["tools"]


def test_fingerprint_rejects_symlinks(tmp_path):
    (tmp_path / "outside").symlink_to(tmp_path.parent)
    with pytest.raises(ValueError, match="unexpected_symlink"):
        fingerprint(tmp_path)


def test_manifest_rejects_different_database_references(tmp_path, monkeypatch, capsys):
    from scripts import audit_replica_storage

    for variable in ("OKF_DATA_ROOT", "SIMULATOR_ROOT", "TOOL_REGISTRY_ROOT"):
        monkeypatch.setenv(variable, str(tmp_path))
    report = tmp_path.parent / (tmp_path.name + ".json")
    pg = {
        "references_sha256": "source",
        "pins_missing_index": 0,
        "receipts_missing_or_changed": 0,
    }
    monkeypatch.setattr(audit_replica_storage, "postgres_state", lambda *args: pg)
    monkeypatch.setattr(sys, "argv", ["audit", "--postgres", "--scope", "7"])
    assert main() == 0
    report.write_text(capsys.readouterr().out)
    monkeypatch.setattr(
        sys, "argv", ["audit", "--postgres", "--scope", "7", "--compare", str(report)]
    )
    assert main() == 0
    pg["references_sha256"] = "different"
    assert main() == 1
