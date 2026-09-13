from simple_agent.services.okf_service import OKFService


def _build_okf(tmp_path):
    root = tmp_path / "okf"
    institution = root / "INSTITUTIONS" / "fastpay"
    policies = institution / "policies"
    policies.mkdir(parents=True)

    (root / "index.md").write_text(
        "# Root\n\n[Institutions](INSTITUTIONS/)\n",
        encoding="utf-8",
    )
    (institution / "index.md").write_text(
        "# FastPay\n\n[Discount](INSTITUTIONS/fastpay/policies/desconto.md)\n",
        encoding="utf-8",
    )
    (policies / "desconto.md").write_text(
        "---\ntype: policy\n---\n\n# Limites de desconto\n\nA DEFINIR PELA OPERAÇÃO.\n",
        encoding="utf-8",
    )
    return root


def test_directory_resolution_is_case_insensitive(tmp_path):
    service = OKFService(_build_okf(tmp_path))

    assert service.canonical_directory("INSTITUTIONS/FastPay") == "INSTITUTIONS/fastpay"

    result = service.read_index("INSTITUTIONS/FastPay")
    assert "OKF_CANONICAL_DIRECTORY: INSTITUTIONS/fastpay" in result
    assert "# FastPay" in result


def test_duplicate_root_prefix_is_collapsed(tmp_path):
    service = OKFService(_build_okf(tmp_path))

    duplicated = "INSTITUTIONS/fastpay/INSTITUTIONS/fastpay/policies/desconto.md"
    assert service.canonical_path(duplicated) == "INSTITUTIONS/fastpay/policies/desconto.md"

    result = service.read_section(duplicated, "Limites de desconto")
    assert "OKF_CANONICAL_PATH: INSTITUTIONS/fastpay/policies/desconto.md" in result
    assert "A DEFINIR PELA OPERAÇÃO" in result


def test_missing_child_index_points_to_parent_before_list(tmp_path):
    service = OKFService(_build_okf(tmp_path))

    result = service.read_index("INSTITUTIONS/unknown")

    assert "Parent index: INSTITUTIONS" in result
    assert "scoped okf_search" in result
    assert "okf_list only as a last fallback" in result
