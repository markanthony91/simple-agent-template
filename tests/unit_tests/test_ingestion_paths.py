import pytest

from simple_agent.services.ingestion_paths import ingestion_path
from simple_agent.services.raw_okf_compiler import RawOKFCompiler


def test_new_roots_are_uppercase_and_existing_paths_unchanged():
    assert (
        ingestion_path("institutions/aurora/rule.md", "create", "GLOBAL", set())
        == "INSTITUTIONS/aurora/rule.md"
    )
    legacy = "institutions/Aurora/rule.md"
    assert ingestion_path(legacy, "append", "GLOBAL", {legacy}) == legacy
    assert ingestion_path("rule.md", "create", "PRODUCTS", set()) == "PRODUCTS/rule.md"


@pytest.mark.parametrize(
    "path,existing",
    [
        ("INSTITUTIONS/a/INSTITUTIONS/b.md", set()),
        ("INSTITUTIONS/a/rule.md", {"institutions/a/rule.md"}),
        ("INSTITUTIONS/a/new.md", {"institutions/a/old.md"}),
        ("INSTITUTIONS/A/new.md", {"INSTITUTIONS/a/old.md"}),
    ],
)
def test_conflicts_are_not_silently_merged(path, existing):
    with pytest.raises(ValueError, match="requires_review"):
        ingestion_path(path, "create", "GLOBAL", existing)


def test_duplicate_case_in_single_plan_rejected(isolated):
    with pytest.raises(ValueError, match="duplicate"):
        RawOKFCompiler(isolated)._normalize_plan(
            {
                "files": [
                    {"path": "institutions/a.md", "content": "one"},
                    {"path": "INSTITUTIONS/a.md", "content": "two"},
                ]
            }
        )


def test_raw_default_and_persistent_override_are_explicit(isolated):
    compiler = RawOKFCompiler(isolated)
    assert compiler.get_agents()["source"] == "default"
    assert "Only NEW segments BELOW" in compiler.get_agents()["content"]
    compiler.save_agents("# Custom operator instructions\nPreserve me.")
    assert compiler.get_agents()["source"] == "runtime_override"
    assert compiler.get_agents()["content"].endswith("Preserve me.\n")
