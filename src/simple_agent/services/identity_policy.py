"""Synthetic identity checks; policy comes only from the pinned server fixture."""

import unicodedata

from simple_agent.services.simulator_schema import IdentityPolicy


def digits(value: str) -> str:
    return "".join(ch for ch in value if ch in "0123456789")


def normalized_name(value: str) -> str:
    text = unicodedata.normalize("NFD", value.casefold())
    return " ".join("".join(c for c in text if not unicodedata.combining(c)).split())


def policy_for(state: dict) -> IdentityPolicy:
    return IdentityPolicy.model_validate(state["fixture"].get("identity_policy", {}))


def matches(state: dict, cpf: str, full_name: str, birth_date: str) -> bool:
    policy = policy_for(state)
    fixture = state["fixture"]
    expected = digits(fixture["cpf"])
    if policy.cpf_mode == "first4":
        expected = expected[:4]
    elif policy.cpf_mode == "last4":
        expected = expected[-4:]
    required_length = 11 if policy.cpf_mode == "full" else 4
    name_ok = bool(full_name.strip()) and normalized_name(full_name) == normalized_name(
        fixture["full_name"]
    )
    birth_ok = bool(birth_date.strip()) and birth_date == fixture["birth_date"]
    secondary_ok = {
        "full_name": name_ok,
        "birth_date": birth_ok,
        "both": name_ok and birth_ok,
        # Preserve legacy behavior: every supplied secondary factor must match.
        "either": (name_ok or birth_ok)
        and (not full_name.strip() or name_ok)
        and (not birth_date.strip() or birth_ok),
    }[policy.secondary]
    return len(expected) == required_length and digits(cpf) == expected and secondary_ok


def instructions(state: dict) -> str:
    policy = policy_for(state)
    cpf = {
        "full": "CPF completo",
        "first4": "4 primeiros dígitos do CPF",
        "last4": "4 últimos dígitos do CPF",
    }[policy.cpf_mode]
    factor = {
        "full_name": "nome completo",
        "birth_date": "data de nascimento",
        "both": "nome completo E data de nascimento",
        "either": "nome completo OU data de nascimento",
    }[policy.secondary]
    remaining = max(0, policy.max_attempts - state.get("identity_attempts", 0))
    return (
        "\n\n# Contrato de identificação da sessão (configuração do backend)\n"
        f"Solicite {cpf} E {factor}. Todos os fatores selecionados são obrigatórios. "
        "Este contrato prevalece sobre instruções conflitantes de identificação. "
        "Use verify_customer_identity com cpf e os fatores selecionados; birth_date "
        "em YYYY-MM-DD. Não invente nem complete dados ausentes. "
        f"Tentativas restantes: {remaining}. Identidade validada: "
        f"{'sim' if state.get('identity_verified') else 'não'}. "
        "Só verified=true autoriza get_customer(), sem CPF, para o cliente desta sessão. "
        "Em falha, não indique qual fator errou nem revele valores esperados. "
        "Se requires_human=true, ofereça atendimento humano sem alegar transferência. "
        "Nunca mostre placeholders como {{nome_cliente}}: sem nome conhecido, omita-o."
    )
