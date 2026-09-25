"""Authenticated HTTP adapters mounted by the existing LangGraph server."""

from __future__ import annotations

import hmac
import json
import os
from decimal import Decimal
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator
from starlette.applications import Starlette
from starlette.concurrency import run_in_threadpool
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Route

from simple_agent.services.session_store import SessionStore
from simple_agent.tools.payment_tools import (
    send_payment_instruction_for_session,
    send_voice_demo_email,
)


class VoiceEmailRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    session_id: str
    payment_id: str = Field(pattern=r"^PAY-[0-9a-f]{32}$")
    email: str = Field(min_length=3, max_length=254)
    latest_user_message: str = Field(min_length=3, max_length=2_000)

    @field_validator("session_id")
    @classmethod
    def valid_session_id(cls, value: str) -> str:
        try:
            parsed = UUID(value)
        except (TypeError, ValueError) as exc:
            raise ValueError("invalid_session_id") from exc
        return str(parsed)


class VoiceDemoEmailRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    session_id: str
    contact_name: str = Field(min_length=1, max_length=100)
    credor: str = Field(min_length=1, max_length=100)
    valor_divida: str = Field(min_length=1, max_length=64)
    email: str = Field(min_length=3, max_length=254)
    latest_user_message: str = Field(min_length=3, max_length=2_000)
    forma_pagamento: Literal["PIX", "BOLETO", "pix", "boleto"]
    parcelas: int = Field(ge=1, le=10)
    valor_total: Decimal | None = Field(default=None, gt=0, le=1_000_000_000)
    valor_parcela: Decimal | None = Field(default=None, gt=0, le=1_000_000_000)

    @field_validator("session_id")
    @classmethod
    def valid_session_id(cls, value: str) -> str:
        try:
            parsed = UUID(value)
        except (TypeError, ValueError) as exc:
            raise ValueError("invalid_session_id") from exc
        return str(parsed)


def _authorized(request: Request) -> bool:
    expected = os.getenv("ELEVENLABS_RUNTIME_API_TOKEN", "").strip()
    supplied = request.headers.get("authorization", "")
    return (
        len(expected) >= 32
        and supplied.startswith("Bearer ")
        and hmac.compare_digest(supplied[7:], expected)
    )


async def send_payment_instruction(request: Request) -> JSONResponse:
    if not _authorized(request):
        return JSONResponse(
            {"success": False, "error": "unauthorized"}, status_code=401
        )
    body = bytearray()
    async for chunk in request.stream():
        body.extend(chunk)
        if len(body) > 16_384:
            return JSONResponse(
                {"success": False, "error": "payload_too_large"}, status_code=413
            )
    try:
        payload = VoiceEmailRequest.model_validate(json.loads(body))
    except (json.JSONDecodeError, ValidationError, ValueError, TypeError):
        return JSONResponse(
            {"success": False, "error": "invalid_request"}, status_code=400
        )
    store = SessionStore()
    if not store.exists(payload.session_id):
        return JSONResponse(
            {"success": False, "error": "session_not_found"}, status_code=404
        )
    result = await run_in_threadpool(
        send_payment_instruction_for_session,
        payload.session_id,
        payload.payment_id,
        payload.email,
        payload.latest_user_message,
    )
    return JSONResponse({"success": result.get("sent") is True, **result})


async def send_demo_email(request: Request) -> JSONResponse:
    if not _authorized(request):
        return JSONResponse(
            {"success": False, "error": "unauthorized"}, status_code=401
        )
    body = bytearray()
    async for chunk in request.stream():
        body.extend(chunk)
        if len(body) > 16_384:
            return JSONResponse(
                {"success": False, "error": "payload_too_large"}, status_code=413
            )
    try:
        payload = VoiceDemoEmailRequest.model_validate(json.loads(body))
    except (json.JSONDecodeError, ValidationError, ValueError, TypeError):
        return JSONResponse(
            {"success": False, "error": "invalid_request"}, status_code=400
        )
    result = await run_in_threadpool(
        send_voice_demo_email,
        payload.session_id,
        payload.contact_name,
        payload.credor,
        payload.valor_divida,
        payload.email,
        payload.latest_user_message,
        payload.forma_pagamento,
        payload.parcelas,
        payload.valor_total,
        payload.valor_parcela,
    )
    return JSONResponse({"success": result.get("sent") is True, **result})


app = Starlette(
    routes=[
        Route(
            "/integrations/elevenlabs/send-payment-instruction",
            send_payment_instruction,
            methods=["POST"],
        ),
        Route(
            "/integrations/elevenlabs/send-demo-email",
            send_demo_email,
            methods=["POST"],
        ),
    ]
)
