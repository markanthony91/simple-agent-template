from concurrent.futures import ThreadPoolExecutor
from unittest.mock import patch

import pytest

from simple_agent.services import okf_service
from simple_agent.services.okf_service import OKFService
from simple_agent.services.okf_search_index import SearchIndexCache
from simple_agent.tool_timing import capture_timing


def bundle(root, text="3 parcelas no boleto"):
    (root / "COMPANIES").mkdir(parents=True)
    (root / "GLOBAL").mkdir()
    for path, content in {
        "index.md": "# 3 parcelas no boleto",
        "COMPANIES/index.md": "# PIX boleto",
        "COMPANIES/a.md": "# Cartão de crédito\n" + text + "\nÀ vista PIX",
        "COMPANIES/b.md": "# Cartão de crédito\n" + text + "\nDesconto",
        "GLOBAL/empty.md": "",
        "GLOBAL/info.md": "# Contato\nNão reconheço a dívida.\nTerceiro familiar",
        "GLOBAL/log.md": "# boleto",
    }.items():
        (root / path).write_text(content, encoding="utf-8")
    return root


@pytest.fixture
def cache(monkeypatch):
    instance = SearchIndexCache()
    monkeypatch.setattr(okf_service, "SEARCH_INDEX_CACHE", instance)
    return instance


@pytest.mark.parametrize("scope", ["", "companies", "GLOBAL", "MISSING"])
@pytest.mark.parametrize("query", ["3x", "crédito", "nao reconheco", "zzmissing"])
def test_same_results_and_no_document_reads_on_hit(tmp_path, cache, scope, query):
    root = bundle(tmp_path / "published")
    reference = OKFService(root).search(query, scope)
    indexed = OKFService(root, immutable_bundle=True)
    assert indexed.search(query, scope) == reference
    with patch.object(
        indexed, "read_file", side_effect=AssertionError("unexpected read")
    ):
        with capture_timing() as metrics:
            assert indexed.search(query, scope) == reference
    assert metrics["counters"] == {"okf_cache_hit": 1}
    if query == "3x" and scope == "":
        assert reference.splitlines()[2:] == [
            "COMPANIES/a.md:4: 3 parcelas no boleto",
            "COMPANIES/b.md:4: 3 parcelas no boleto",
        ]


def test_snapshot_storage_scope_and_limit_are_in_cache_key(tmp_path, cache):
    a = OKFService(
        bundle(tmp_path / "tenant-a/v1", "10 parcelas"), immutable_bundle=True
    )
    b = OKFService(
        bundle(tmp_path / "tenant-b/v1", "2 parcelas"), immutable_bundle=True
    )
    c = OKFService(
        bundle(tmp_path / "tenant-a/v2", "5 parcelas"), immutable_bundle=True
    )
    assert "10 parcelas" in a.search("10x")
    assert "10 parcelas" not in b.search("10x")
    assert "5 parcelas" in c.search("5x")
    assert len(cache.entries) == 2
    assert cache.size <= cache.max_bytes
    assert "10 parcelas" in a.search(
        "10x"
    )  # Evicted old pinned version rebuilds correctly.
    short = OKFService(a.root, max_chars_per_file=1, immutable_bundle=True)
    assert "No OKF matches" in short.search("10x")


def test_drafts_overrides_and_active_selection_bypass_cache(tmp_path, cache):
    root = bundle(tmp_path / "draft")
    service = OKFService(root)
    service.search("3x")
    assert not cache.entries
    (root / "COMPANIES/a.md").write_text("7 parcelas")
    assert "7 parcelas" in service.search("7x")
    published = OKFService(root, immutable_bundle=True)
    published.search("7x")
    assert "8 parcelas" in published.search(
        "8x", overrides={"COMPANIES/a.md": "8 parcelas"}
    )
    result = published.search("3x", active_files={"GLOBAL/info.md"})
    assert "No OKF matches" in result
    with pytest.raises(ValueError):
        published.search("boleto", "../escape")
    with pytest.raises(ValueError):
        published.search(" ")


def test_one_build_for_concurrent_searches_and_budget_fallback(tmp_path, cache):
    service = OKFService(bundle(tmp_path / "v1"), immutable_bundle=True)
    with patch.object(service, "read_file", wraps=service.read_file) as reader:
        with ThreadPoolExecutor(max_workers=4) as pool:
            results = list(pool.map(lambda _: service.search("3x"), range(8)))
    assert len(set(results)) == 1
    assert reader.call_count == 4  # Excludes indexes and log.md.
    small = SearchIndexCache(max_bytes=1)
    assert small.get(service) is None
    with patch.object(
        service, "read_file", side_effect=AssertionError("rebuilt oversize")
    ):
        assert small.get(service) is None
    assert small.size == 0
    with patch.object(okf_service, "SEARCH_INDEX_CACHE", small):
        assert service.search("3x") == results[0]


def test_total_byte_budget_evicts_without_changing_results(tmp_path, cache):
    a = OKFService(bundle(tmp_path / "v1"), immutable_bundle=True)
    b = OKFService(bundle(tmp_path / "v2"), immutable_bundle=True)
    a.search("3x")
    cache.max_bytes = cache.size + 100
    b.search("3x")
    assert len(cache.entries) == 1
    assert next(iter(cache.entries))[0] == str(b.root)
    assert cache.size <= cache.max_bytes


def test_cold_index_rejects_symlink_escape(tmp_path, cache):
    root = bundle(tmp_path / "v1")
    outside = tmp_path / "private.md"
    outside.write_text("private marker")
    (root / "COMPANIES/escape.md").symlink_to(outside)
    with pytest.raises(ValueError):
        OKFService(root, immutable_bundle=True).search("marker")
    assert not cache.entries
