from simple_agent.tool_observability import sanitize_result, sanitize_tool_args


def test_sensitive_tool_args_are_redacted() -> None:
    payload = sanitize_tool_args(
        "verify_customer_identity",
        {"cpf": "123.456.789-00", "full_name": "João da Silva", "birth_date": "1985-04-17"},
    )
    assert payload["cpf"].endswith("00")
    assert "123" not in payload["cpf"]
    assert payload["full_name"] == "<redacted>"
    assert payload["birth_date"] == "<redacted>"


def test_okf_args_only_keep_metadata() -> None:
    payload = sanitize_tool_args(
        "okf_read_section",
        {"path": "GLOBAL/policy.md", "heading": "Discounts", "ignored": "secret"},
    )
    assert payload == {"path": "GLOBAL/policy.md", "heading": "Discounts"}


def test_okf_result_does_not_log_document_body() -> None:
    result = sanitize_result("okf_read", "very sensitive institutional content")
    assert result == {"content_length": len("very sensitive institutional content")}
