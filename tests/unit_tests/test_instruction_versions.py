from concurrent.futures import ThreadPoolExecutor

import pytest

from simple_agent.services.raw_okf_compiler import RawOKFCompiler


def test_history_preserves_legacy_reload_restore_and_serializes_writes(isolated):
    compiler = RawOKFCompiler(isolated)
    compiler.agents_path.write_text("  Legacy exact content\n\n", encoding="utf-8")
    assert compiler.get_agents_versions() == {"versions": []}
    assert compiler.save_agents("New instructions")["version"] == 2
    reloaded = RawOKFCompiler(isolated)
    assert reloaded.get_agents()["content"] == "New instructions\n"
    history = reloaded.get_agents_versions()["versions"]
    assert [v["version"] for v in history] == [2, 1]
    assert history[1]["content"] == "  Legacy exact content\n\n"
    assert reloaded.save_agents(history[1]["content"])["version"] == 3
    with ThreadPoolExecutor(max_workers=4) as pool:
        results = list(pool.map(compiler.save_agents, [f"Edit {i}" for i in range(4)]))
    assert sorted(v["version"] for v in results) == [4, 5, 6, 7]
    assert [v["version"] for v in compiler.get_agents_versions(2, 2)["versions"]] == [
        5,
        4,
    ]
    assert compiler.agents_path.read_text() == "  Legacy exact content\n\n"


def test_history_atomic_failure_and_validation(isolated, monkeypatch):
    compiler = RawOKFCompiler(isolated)
    default = compiler.get_agents()["content"]
    compiler.save_agents("First")
    assert compiler.get_agents_versions()["versions"][-1]["content"] == default
    for content in [" ", "x" * 50001]:
        with pytest.raises(ValueError):
            compiler.save_agents(content)
    for limit, offset in [(0, 0), (101, 0), (True, 0), (1, -1), (1, "0")]:
        with pytest.raises(ValueError):
            compiler.get_agents_versions(limit, offset)

    def fail(*args):
        raise OSError("Controlled disk failure")

    monkeypatch.setattr("simple_agent.services.atomic_files.os.replace", fail)
    with pytest.raises(OSError, match="disk failure"):
        compiler.save_agents("Must not be saved")
    assert compiler.get_agents()["content"] == "First\n"
    assert len(compiler.get_agents_versions()["versions"]) == 2
    assert not list(compiler.raw_root.glob("*.tmp"))
