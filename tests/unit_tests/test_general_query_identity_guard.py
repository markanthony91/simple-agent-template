from simple_agent.tool_middleware import (
    _sanitize_identity_request,
)


def test_first3_only_identity_request_drops_other_factors() -> None:
    response = (
        "Para validar sua identidade, informe os 3 primeiros dígitos do CPF, "
        "nome completo e data de nascimento."
    )
    session = {
        "identity_verified": False,
        "fixture": {
            "identity_policy": {
                "cpf_mode": "first3",
                "secondary": "none",
                "max_attempts": 3,
            }
        },
    }

    sanitized = _sanitize_identity_request(response, session)

    assert "3 primeiros dígitos" in sanitized
    assert "nome completo" not in sanitized
    assert "data de nascimento" not in sanitized


def test_vague_identity_process_becomes_exact_cpf_request() -> None:
    response = (
        "Para consultar os detalhes, preciso primeiro realizar a sua identificação."
    )
    session = {
        "identity_verified": False,
        "fixture": {
            "identity_policy": {
                "cpf_mode": "first3",
                "secondary": "none",
                "max_attempts": 3,
            }
        },
    }

    assert _sanitize_identity_request(response, session) == (
        "Para consultar sua dívida, preciso validar sua identidade. "
        "Informe apenas os 3 primeiros dígitos do seu CPF."
    )


def test_security_verification_becomes_exact_cpf_request() -> None:
    response = (
        "Para consultar se existe alguma pendência, preciso realizar uma breve "
        "verificação de segurança."
    )
    session = {
        "identity_verified": False,
        "fixture": {
            "identity_policy": {
                "cpf_mode": "first3",
                "secondary": "none",
                "max_attempts": 3,
            }
        },
    }

    assert _sanitize_identity_request(response, session) == (
        "Para consultar sua dívida, preciso validar sua identidade. "
        "Informe apenas os 3 primeiros dígitos do seu CPF."
    )
