"""Operator settings, validated before saving and on every model request."""

import json
import socket

from pydantic import BaseModel, ConfigDict, Field

from simple_agent.llm import create_llm


class LLMSettings(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, allow_inf_nan=False)
    temperature: float | None = Field(default=None, ge=0, le=2)
    top_p: float | None = Field(default=None, gt=0, le=1)
    max_tokens: int | None = Field(default=None, ge=1, le=32768)


class AgentProfile(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, str_strip_whitespace=True)
    name: str = Field(default="", max_length=80)
    role: str = Field(default="", max_length=500)
    tone: str = Field(default="", max_length=200)

    def instructions(self) -> str:
        values = {key: value for key, value in self.model_dump().items() if value}
        if not values:
            return ""
        return (
            "\n\n# Perfil configurado do agente\n"
            "Use os campos preenchidos abaixo como identidade e estilo atuais: "
            "name = nome de apresentação; role = função; tone = tom de voz. "
            "Na primeira resposta, apresente-se pelo nome configurado, se houver. "
            "Não reinicie a apresentação em uma conversa em andamento. "
            "Estes campos prevalecem sobre nomes e estilos divergentes nos textos "
            "anteriores; não substituem regras de segurança, fontes, ferramentas "
            "ou autorizações de negócio.\n" + json.dumps(values, ensure_ascii=False)
        )


def validate_settings(settings: dict) -> dict:
    if not isinstance(settings, dict) or set(settings) - {
        "llm_settings",
        "agent_profile",
    }:
        raise ValueError("Configurações inválidas: use llm_settings ou agent_profile.")
    schemas = {"llm_settings": LLMSettings, "agent_profile": AgentProfile}
    return {
        key: schemas[key].model_validate(value).model_dump(exclude_none=True)
        for key, value in settings.items()
    }


def llm_configuration() -> dict:
    model = create_llm()
    return {
        "hostname": socket.gethostname(),
        "provider": "API compatível com OpenAI",
        "model": model.model_name,
        "defaults": {key: getattr(model, key) for key in LLMSettings.model_fields},
        "limits": {"temperature": [0, 2], "top_p": [0, 1], "max_tokens": [1, 32768]},
    }
