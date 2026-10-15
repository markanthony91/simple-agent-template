from simple_agent.tool_middleware import (
    ACTIVE_IDENTITY_REPLY,
    _chat_name_was_given,
    _sanitize_identity_request,
)
from langchain_core.messages import AIMessage, HumanMessage
from types import SimpleNamespace


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


def test_name_from_form_is_not_requested_again_or_used_as_verification() -> None:
    session = {
        "identity_verified": False,
        "name_context": {"provided": True, "source": "form"},
        "fixture": {
            "identity_policy": {
                "cpf_mode": "first3",
                "secondary": "none",
                "max_attempts": 3,
            }
        },
    }
    question = "Para iniciar, poderia me informar seu nome, por gentileza?"
    assert _sanitize_identity_request(question, session) == (
        "Para consultar seu contrato com segurança, informe apenas os "
        "3 primeiros dígitos do seu CPF."
    )
    assert session["identity_verified"] is False
    assert (
        _sanitize_identity_request(question, {**session, "name_context": {}})
        == question
    )


def test_name_answer_is_detected_only_after_question_or_explicit_introduction() -> None:
    def request(*messages):
        return SimpleNamespace(
            state={"messages": list(messages)}, messages=list(messages)
        )

    question = AIMessage(content="Poderia me informar seu nome?")
    assert _chat_name_was_given(
        request(question, HumanMessage(content="Marcelo Silva"))
    )
    assert _chat_name_was_given(request(HumanMessage(content="Meu nome é Marcelo")))
    assert not _chat_name_was_given(
        request(question, HumanMessage(content="Prefiro não informar"))
    )
    assert not _chat_name_was_given(
        request(HumanMessage(content="Empréstimo consignado"))
    )


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
