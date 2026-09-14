import json
from types import SimpleNamespace

import pytest

from simple_agent.services.raw_okf_compiler import RawOKFCompiler

OLD = "---\ntype: Policy\n---\n# Support\nUse the registered support channel.\n"
PATH = "GLOBAL/support.md"


def compiler(isolated, monkeypatch, files, conflicts=None):
    isolated.import_bundle("base", "0.2", {"index.md": "# Base", PATH: OLD})
    replies = iter([{"paths": [PATH]}, {"files": files, "conflicts": conflicts or []}])

    class Model:
        def invoke(self, messages):
            assert "untrusted_document" in str(messages)
            return SimpleNamespace(content=json.dumps(next(replies)))

    monkeypatch.setattr(
        "simple_agent.services.raw_okf_compiler.create_llm", lambda: Model()
    )
    return RawOKFCompiler(isolated)


def test_incremental_raw_root_index_log_and_idempotency(isolated, monkeypatch):
    instance = compiler(
        isolated,
        monkeypatch,
        [
            {"path": PATH, "action": "append", "content": "Keep the protocol number."},
            {
                "path": "GLOBAL/contact.md",
                "action": "create",
                "type": "Procedure",
                "content": "Use support.",
            },
        ],
    )
    analysis = instance.analyze("support.md", "Keep protocol. Use support.")
    assert instance.analyze("support.md", "Keep protocol. Use support.") == analysis
    result = instance.create_draft(analysis["ingestion_id"])
    assert result["validation"]["valid"]
    files = isolated.draft_files(result["draft_id"])
    assert files[PATH].startswith(OLD.rstrip())
    assert "Keep the protocol number." in files[PATH]
    assert "GLOBAL/" in files["index.md"]
    assert "support.md" in files["GLOBAL/index.md"]
    assert analysis["source_hash"] in files["log.md"]
    assert instance.create_draft(analysis["ingestion_id"]) == result
    raw = instance.raw_root / analysis["ingestion_id"] / "source.txt"
    assert raw.read_text() == "Keep protocol. Use support."
    assert isolated.read_file(PATH).endswith(OLD)  # Draft is not active.
    published = isolated.publish_draft(result["draft_id"])
    assert (
        isolated.publish_draft(result["draft_id"])["bundle_id"]
        == published["bundle_id"]
    )


def test_conflict_is_not_published(isolated, monkeypatch):
    instance = compiler(isolated, monkeypatch, [], ["Two sources disagree"])
    analysis = instance.analyze("bad.md", "contradiction")
    with pytest.raises(ValueError, match="conflict"):
        instance.create_draft(analysis["ingestion_id"])
    assert len(isolated.list_versions()) == 1


def test_partial_failure_cannot_publish(isolated, monkeypatch):
    instance = compiler(
        isolated,
        monkeypatch,
        [{"path": PATH, "action": "create", "content": "replacement"}],
    )
    analysis = instance.analyze("bad.md", "replace")
    with pytest.raises(ValueError, match="append"):
        instance.create_draft(analysis["ingestion_id"])
    for draft in isolated.list_drafts():
        with pytest.raises(ValueError, match="incomplete"):
            isolated.publish_draft(draft["draft_id"])


@pytest.mark.parametrize(
    "plan",
    [
        {"files": [{"path": "../escape.md", "content": "x"}]},
        {"files": [{"path": "AGENTS.md", "content": "x"}]},
        {"files": [{"path": "GLOBAL/a.md", "action": "replace", "content": "x"}]},
        {"files": "not a list"},
    ],
)
def test_invalid_plan_rejected(isolated, plan):
    with pytest.raises(ValueError):
        RawOKFCompiler(isolated)._normalize_plan(plan)


def test_invalid_json_rejected():
    with pytest.raises(ValueError, match="invalid JSON"):
        RawOKFCompiler._parse_json("{broken")
