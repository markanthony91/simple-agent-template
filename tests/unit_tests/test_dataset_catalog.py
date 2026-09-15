import pytest

from simple_agent.services.dataset_catalog import catalog, read_document


def bundle(store, body="A indenização é analisada conforme a política."):
    return store.import_bundle(
        "search-test",
        "0.2",
        {
            "index.md": "# Navegação",
            "GLOBAL/rules.md": "---\ntype: Policy\ntitle: Regras especiais\nstatus: draft\n---\n# Regras\n"
            + body,
            "INSTITUTIONS/a/index.md": "# Instituição",
            "INSTITUTIONS/a/tools.md": "---\ntype: Tool\ntitle: Consulta de contrato\n---\n# Consulta\nTeste sintético.",
        },
    )


def test_catalog_content_metadata_and_accent_search(isolated):
    saved = bundle(isolated)
    original = isolated._root_files(isolated.bundle_root(saved["bundle_id"]))
    all_docs = catalog(isolated)
    assert all_docs["total"] == 4
    assert all_docs["type_counts"] == {"POLICY": 1, "INDEX": 2, "TOOL": 1}
    match = catalog(isolated, "INDENIZACAO")
    assert len(match["documents"]) == 1
    doc = match["documents"][0]
    assert doc["path"] == "GLOBAL/rules.md"
    assert doc["title"] == "Regras especiais"
    assert doc["status"] == "draft"  # Never claim published means approved.
    assert "indenização" in doc["snippet"]
    assert doc["line"] == 7
    assert catalog(isolated, "contrato")["documents"][0]["type"] == "TOOL"
    assert len(catalog(isolated, "INSTITUTIONS")["documents"]) == 2
    assert catalog(isolated, "not-found")["documents"] == []
    assert isolated._root_files(isolated.bundle_root(saved["bundle_id"])) == original


def test_full_content_beyond_runtime_excerpt_and_pinned_snapshot(isolated):
    first = bundle(isolated, "x" * 16000 + "\nPalavra exclusiva.")
    bundle(isolated, "Conteúdo novo.")
    match = catalog(isolated, "exclusiva", first["bundle_id"])
    assert len(match["documents"]) == 1
    assert catalog(isolated, "exclusiva")["documents"] == []
    assert "exclusiva" in read_document(isolated, first["bundle_id"], "GLOBAL/rules.md")
    assert len(match["documents"][0]["snippet"]) <= 241


def test_empty_bundle_and_bad_query(isolated):
    assert catalog(isolated)["documents"] == []
    for query in ["x" * 201, 123, None]:
        with pytest.raises(ValueError):
            catalog(isolated, query)
    with pytest.raises(ValueError):
        catalog(isolated, bundle_id=123)


def test_path_and_symlink_limits(isolated, tmp_path):
    first = bundle(isolated)
    for path in ["../outside.md", "/tmp/data.md", "GLOBAL/file.txt"]:
        with pytest.raises(ValueError):
            read_document(isolated, first["bundle_id"], path)
    for snapshot in ["../../bad", "/tmp", "missing"]:
        with pytest.raises((ValueError, FileNotFoundError)):
            catalog(isolated, bundle_id=snapshot)
    root = isolated.bundle_root(first["bundle_id"])
    (tmp_path / "outside.md").write_text("Never leak outside text.")
    (root / "leak.md").symlink_to(tmp_path / "outside.md")
    with pytest.raises(ValueError):
        catalog(isolated, "leak")
    with pytest.raises(ValueError):
        read_document(isolated, first["bundle_id"], "leak.md")


def test_invalid_metadata_is_labeled_not_invented(isolated):
    first = bundle(isolated)
    root = isolated.bundle_root(first["bundle_id"])
    (root / "bad.md").write_text("---\ntype: [oops\n---\n# Broken metadata")
    (root / "untyped.md").write_text("# Title only")
    bad = {doc["path"]: doc for doc in catalog(isolated)["documents"]}
    assert bad["bad.md"]["metadata_warning"] is True
    assert bad["untyped.md"]["type"] == "SEM TIPO"
    assert bad["index.md"]["metadata_warning"] is False


def test_oversized_document_rejected(isolated):
    first = bundle(isolated)
    root = isolated.bundle_root(first["bundle_id"])
    (root / "big.md").write_text("x" * 200001)
    with pytest.raises(ValueError):
        catalog(isolated)
    with pytest.raises(ValueError):
        read_document(isolated, first["bundle_id"], "big.md")


def test_admin_catalog_is_read_only(isolated, monkeypatch):
    from simple_agent import admin_graph_v2 as admin

    bundle(isolated)
    monkeypatch.setattr(admin, "store", isolated)
    state = admin.execute({"operation": "catalog", "query": "indenizacao"})
    assert state["error"] == ""
    assert len(state["result"]["documents"]) == 1
    read = admin.execute(
        {
            "operation": "read",
            "path": "GLOBAL/rules.md",
            "bundle_id": state["result"]["bundle_id"],
        }
    )
    assert read["error"] == ""
    assert "indenização" in read["result"]["content"]
    assert isolated.list_drafts() == []
