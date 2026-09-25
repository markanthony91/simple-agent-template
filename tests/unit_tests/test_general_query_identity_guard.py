from simple_agent.tool_middleware import (
    ACTIVE_IDENTITY_REPLY,
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


def test_active_opening_acceptance_does_not_repeat_agent_identity() -> None:
    response = (
        "Olá! Meu nome é Sophia, sou assistente virtual do Will Bank.\n\n"
        "Para que possamos conversar com segurança e eu possa confirmar sua "
        "identidade, você poderia me informar os 3 primeiros dígitos do seu CPF, "
        "por favor?"
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

    for acceptance in ("Podemos falar", "pode falar!", "SIM", "claro"):
        assert (
            _sanitize_identity_request(response, session, acceptance)
            == ACTIVE_IDENTITY_REPLY
        )
    assert "Sophia" not in ACTIVE_IDENTITY_REPLY


def test_unbound_whatsapp_never_turns_acceptance_into_identity_request() -> None:
    response = "Olá! Meu nome é Sophia. Para confirmar sua identidade, informe seu CPF."
    session = {
        "identity_verified": False,
        "unbound_session": True,
    }

    assert _sanitize_identity_request(response, session, "Podemos falar") == (
        "Para consultar ou negociar uma dívida, é necessário iniciar pelo formulário "
        "da demonstração."
    )
