import pytest

from simple_agent.services.okf_service import OKFService
from simple_agent.services.okf_validator import validate_document


@pytest.mark.parametrize(
    "body",
    [
        "---\ntype:\n---\nBody",
        "---\ntype: [invalid\n---\nBody",
        "---\ntype: Policy\ntype: Other\n---\nBody",
        "---\ntype: &a Policy\ncopy: *a\n---\nBody",
        "---\ntype: []\n---\nBody",
        "Missing frontmatter",
    ],
)
def test_yaml_rejected(body):
    with pytest.raises(ValueError):
        validate_document("GLOBAL/test.md", body)


def test_search_multiple_files(isolated):
    isolated.import_bundle(
        "test",
        "0.2",
        {
            "index.md": "# Index",
            "GLOBAL/a.md": "---\ntype: Policy\n---\nPayment alpha",
            "GLOBAL/b.md": "---\ntype: Policy\n---\nPayment beta",
        },
    )
    assert len(isolated.service().list_files().splitlines()) == 3
    result = isolated.service().search("Payment")
    assert "a.md" in result and "b.md" in result


def test_search_ranks_whole_policy_and_returns_each_document_once(isolated):
    pilot = "COMPANIES/will/policies/negociacao-piloto.md"
    generic = "COMPANIES/will/knowledge/formas-pagamento.md"
    isolated.import_bundle(
        "ranked",
        "0.2",
        {
            "index.md": "# Index",
            pilot: (
                "---\ntype: Policy\ninstitution: Will Bank\n"
                "product: cartao_de_credito\nnegotiation:\n  max_installments: 3\n"
                "payment:\n  methods: [pix, boleto]\n---\n"
                "# Negociação\nAté três parcelas, sem desconto."
            ),
            generic: (
                "---\ntype: Knowledge\ntags: [Will Bank, cartão de crédito]\n---\n"
                "# Formas de pagamento\nBoleto é um meio de pagamento.\n"
                "Boleto pode ser consultado."
            ),
        },
    )

    result = isolated.service().search(
        "Will Bank cartao_de_credito boleto parcelado 3x", scope="COMPANIES"
    )
    matches = result.splitlines()[2:]
    assert matches[0].startswith(pilot)
    assert sum(line.startswith(pilot) for line in matches) == 1
    assert sum(line.startswith(generic) for line in matches) == 1


@pytest.mark.parametrize(
    "path", ["/etc/passwd.md", "../outside.md", "GLOBAL/../../a.md", "a.txt"]
)
def test_paths_rejected(isolated, path):
    with pytest.raises(ValueError):
        isolated.import_bundle(
            "bad", "0.2", {"index.md": "# Index", path: "---\ntype: Policy\n---\nx"}
        )


def test_symlink_rejected(tmp_path):
    root = tmp_path / "root"
    root.mkdir()
    outside = tmp_path / "outside.md"
    outside.write_text("secret")
    (root / "escape.md").symlink_to(outside)
    with pytest.raises(ValueError):
        OKFService(root).read_file("escape.md")


def test_publish_approval_validation_replay_and_stale_base(isolated):
    original = isolated.import_bundle("first", "0.2", {"index.md": "# Original"})
    draft = isolated.create_draft("update")
    isolated.write_draft_file(draft["draft_id"], "index.md", "# New")
    new = isolated.publish_draft(draft["draft_id"])
    assert new["bundle_id"] != original["bundle_id"]
    assert isolated.publish_draft(draft["draft_id"])["bundle_id"] == new["bundle_id"]
    assert (
        isolated.bundle_root(original["bundle_id"]) / "index.md"
    ).read_text() == "# Original"
    isolated.activate_bundle(original["bundle_id"])
    assert isolated.active_bundle_id() == original["bundle_id"]
    blocked = isolated.create_draft("incomplete", building=True)
    with pytest.raises(ValueError, match="incomplete"):
        isolated.publish_draft(blocked["draft_id"])
    stale = isolated.create_draft("stale")
    isolated.import_bundle("third", "0.2", {"index.md": "# Third"})
    with pytest.raises(ValueError, match="base"):
        isolated.publish_draft(stale["draft_id"])
