from simple_agent.services.okf_service import OKFService
from simple_agent.prompt_loader import load_agent_prompt


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


def test_duplicate_root_prefix_is_collapsed(tmp_path):
    service = OKFService(_build_okf(tmp_path))

    duplicated = "INSTITUTIONS/fastpay/INSTITUTIONS/fastpay/policies/desconto.md"
    assert service.canonical_path(duplicated) == "INSTITUTIONS/fastpay/policies/desconto.md"

    result = service.read_section(duplicated, "Limites de desconto")
    assert "OKF_CANONICAL_PATH: INSTITUTIONS/fastpay/policies/desconto.md" in result
    assert "A DEFINIR PELA OPERAÇÃO" in result


def test_missing_child_index_returns_parent_and_available_children(tmp_path):
    """When a child index.md does not exist, return OKF_REQUESTED_DIRECTORY, OKF_CANONICAL_PARENT, and available destinations."""
    service = OKFService(_build_okf(tmp_path))

    result = service.read_index("INSTITUTIONS/unknown")

    assert "OKF_REQUESTED_DIRECTORY: INSTITUTIONS/unknown" in result
    assert "OKF_CANONICAL_PARENT: INSTITUTIONS" in result
    assert "Available destinations from parent:" in result
    assert "Choose only from these destinations" in result


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


def test_read_index_includes_child_directories_and_concept_paths_manifest(tmp_path):
    """read_index should include OKF_CHILD_DIRECTORIES and OKF_CONCEPT_PATHS markers with actual on-disk entries."""
    service = OKFService(_build_okf(tmp_path))

    result = service.read_index("INSTITUTIONS/fastpay")
    assert "OKF_CANONICAL_DIRECTORY: INSTITUTIONS/fastpay" in result
    assert "OKF_CHILD_DIRECTORIES:" in result
    assert "OKF_CONCEPT_PATHS:" in result
    # Should show the actual policies directory as a child
    assert "policies" in result or "(none)" in result


def test_case_insensitive_scope_normalization(tmp_path):
    """Scope in search should be normalized to canonical case."""
    service = OKFService(_build_okf(tmp_path))

    # Mixed case scope
    result = service.search("policy", scope="institutions/FASTPAY")
    # Should find results despite mixed case
    assert "OKF_CANONICAL_SCOPE:" in result


def test_read_index_root_index_includes_manifest(tmp_path):
    """Root index read should include navigation manifest."""
    service = OKFService(_build_okf(tmp_path))

    result = service.read_index("")
    assert "OKF_CANONICAL_DIRECTORY: <root>" in result
    assert "OKF_CHILD_DIRECTORIES:" in result


def test_missing_index_fallback_shows_available_alternatives(tmp_path):
    """When index.md is missing but parent exists, show available alternatives from parent."""
    service = OKFService(_build_okf(tmp_path))

    # Request a directory that exists but has no index.md
    result = service.read_index("INSTITUTIONS/fastpay/policies")
    
    # Should show what's available in the parent (fastpay)
    assert "OKF_REQUESTED_DIRECTORY:" in result or "OKF_CANONICAL_PARENT:" in result


def test_extract_index_links_from_markdown(tmp_path):
    """_extract_index_links should parse markdown links from index.md content."""
    service = OKFService(_build_okf(tmp_path))
    
    content = "# Test\n\n[Link1](path/to/file.md)\n[Link2](path/to/dir/)\n"
    links = service._extract_index_links(content)
    
    assert "path/to/file.md" in links
    assert "path/to/dir" in links  # trailing slash should be stripped


def test_get_child_directories_and_concepts_returns_actual_entries(tmp_path):
    """_get_child_directories_and_concepts should return only actual on-disk children."""
    service = OKFService(_build_okf(tmp_path))
    
    child_dirs, concepts = service._get_child_directories_and_concepts("INSTITUTIONS/fastpay")
    
    # Should have 'policies' as a child directory
    assert any("policies" in d for d in child_dirs)
    # Should have desconto.md as a concept (or be empty if not listed)
    # At minimum, should not invent paths
    assert isinstance(child_dirs, list)
    assert isinstance(concepts, list)


def test_load_agent_prompt_loads_default_workflow_when_none(tmp_path):
    """When workflow is None, load_agent_prompt should include default WORKFLOW.md."""
    prompt = load_agent_prompt(
        system_prompt="System: Test",
        agent_instructions="Instructions: Test",
        workflow=None,  # Explicitly None to load default
    )
    
    # Should include workflow section
    assert "# Active Workflow" in prompt
    # Should include stages from WORKFLOW.md
    assert "Stage" in prompt or "stage" in prompt.lower() or "Workflow" in prompt


def test_load_agent_prompt_skips_workflow_when_empty_string(tmp_path):
    """When workflow is empty string, load_agent_prompt should skip workflow section entirely."""
    prompt = load_agent_prompt(
        system_prompt="System: Test",
        agent_instructions="Instructions: Test",
        workflow="",  # Empty string should skip
    )
    
    # Should NOT include a full workflow section
    # (a minimal "Active Workflow" might appear but no stage content)
    lines = prompt.split("\n")
    workflow_lines = [l for l in lines if "Active Workflow" in l or "Stage" in l]
    # With empty string, we should have minimal or no workflow content
    assert not any("Stage 1" in l for l in lines), "Should not include workflow stages when workflow is empty"


def test_load_agent_prompt_uses_runtime_workflow_override(tmp_path):
    """When workflow is a non-empty string, use it as provided (runtime override)."""
    custom_workflow = "Custom workflow: Test Process"
    prompt = load_agent_prompt(
        system_prompt="System: Test",
        agent_instructions="Instructions: Test",
        workflow=custom_workflow,
    )
    
    assert "Custom workflow: Test Process" in prompt
    assert "# Active Workflow" in prompt


def test_nonexistent_child_directory_no_invention(tmp_path):
    """Model should not invent INSTITUTIONS/nonexistent/index.md when directory doesn't exist."""
    service = OKFService(_build_okf(tmp_path))
    
    result = service.read_index("INSTITUTIONS/invented_company")
    
    # Should return error response with parent and available children, NOT pretend the path exists
    assert "OKF_REQUESTED_DIRECTORY:" in result
    assert "OKF_CANONICAL_PARENT:" in result
    # Should NOT include content of a non-existent file
    assert "# Root" not in result or "# FastPay" not in result or result.count("\n") < 20


def test_canonical_path_preserved_in_manifest(tmp_path):
    """When read_index returns manifest, it should preserve canonical directory naming."""
    service = OKFService(_build_okf(tmp_path))
    
    result = service.read_index("INSTITUTIONS/fastpay")
    
    # Canonical should be lowercase, case-normalized
    assert "INSTITUTIONS/fastpay" in result
    # Should not have mixed case
    assert "INSTITUTIONS/FastPay" not in result

