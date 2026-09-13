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
        "---\ntype: policy\n---\n\n# Limites de desconto\n\nA DEFINIR PELA OPERAÇÃO.\n\n# Installments\n\nUp to 12 installments.\n",
        encoding="utf-8",
    )
    return root


def test_directory_resolution_is_case_insensitive(tmp_path):
    service = OKFService(_build_okf(tmp_path))

    assert service.canonical_directory("INSTITUTIONS/FastPay") == "INSTITUTIONS/fastpay"

    result = service.read_index("INSTITUTIONS/FastPay")
    assert "OKF_CANONICAL_DIRECTORY: INSTITUTIONS/fastpay" in result
    assert "OKF_CANONICAL_SCOPE: INSTITUTIONS/fastpay" in result
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
    assert "OKF_CANONICAL_SCOPE:" in result


def test_search_canonicalizes_scope_case_insensitive(tmp_path):
    """Search scope should be case-insensitive and always return OKF_CANONICAL_SCOPE marker."""
    service = OKFService(_build_okf(tmp_path))

    # Case-insensitive scope
    result = service.search("desconto", scope="INSTITUTIONS/fastpay/POLICIES")
    assert "OKF_CANONICAL_SCOPE:" in result


def test_search_returns_canonical_scope_even_when_no_matches(tmp_path):
    """Search always includes OKF_CANONICAL_SCOPE marker, even when no matches found."""
    service = OKFService(_build_okf(tmp_path))

    result = service.search("nonexistent_term_xyz", scope="INSTITUTIONS/fastpay")
    assert "OKF_CANONICAL_SCOPE: INSTITUTIONS/fastpay" in result
    assert "No OKF matches found" in result


def test_read_section_exact_heading_only_no_fuzzy(tmp_path):
    """read_section should match exact heading only; fuzzy matching is removed."""
    service = OKFService(_build_okf(tmp_path))

    # Exact match should work
    result = service.read_section("INSTITUTIONS/fastpay/policies/desconto.md", "Limites de desconto")
    assert "A DEFINIR PELA OPERAÇÃO" in result
    assert "OKF_CANONICAL_PATH:" in result


def test_read_section_missing_heading_lists_available_and_requires_retry(tmp_path):
    """When exact heading is missing, return available headings and require exact retry."""
    service = OKFService(_build_okf(tmp_path))

    # Nonexistent heading (no fuzzy fallback)
    result = service.read_section("INSTITUTIONS/fastpay/policies/desconto.md", "Nonexistent Heading")
    
    assert "not found (no fuzzy match)" in result
    assert "Available headings" in result
    assert '"Limites de desconto"' in result
    assert '"Installments"' in result
    assert "Retry with one of these exact headings" in result
    assert "OKF_CANONICAL_PATH:" in result


def test_duplicate_root_collapse_before_existence_check(tmp_path):
    """Duplicate-root collapse should resolve before existence checks."""
    service = OKFService(_build_okf(tmp_path))

    # Multiple repeated roots should collapse to canonical
    tripled = "INSTITUTIONS/fastpay/INSTITUTIONS/fastpay/INSTITUTIONS/fastpay/policies/desconto.md"
    canonical = service.canonical_path(tripled)
    assert canonical == "INSTITUTIONS/fastpay/policies/desconto.md"


def test_read_index_includes_canonical_scope_marker(tmp_path):
    """read_index should include OKF_CANONICAL_SCOPE marker in response."""
    service = OKFService(_build_okf(tmp_path))

    result = service.read_index("INSTITUTIONS/fastpay")
    assert "OKF_CANONICAL_DIRECTORY: INSTITUTIONS/fastpay" in result
    assert "OKF_CANONICAL_SCOPE: INSTITUTIONS/fastpay" in result


def test_case_insensitive_scope_normalization(tmp_path):
    """Scope in search should be normalized to canonical case."""
    service = OKFService(_build_okf(tmp_path))

    # Mixed case scope
    result = service.search("policy", scope="institutions/FASTPAY")
    # Should find results despite mixed case
    assert "OKF_CANONICAL_SCOPE:" in result

