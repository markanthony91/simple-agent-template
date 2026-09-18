"""Validate synthetic fixtures without retaining legacy authorization state."""

from decimal import Decimal
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, StrictInt

Amount = Annotated[Decimal, Field(ge=0, allow_inf_nan=False)]


class Debt(BaseModel):
    model_config = ConfigDict(extra="allow")
    debt_id: str
    current_amount: Amount
    original_amount: Amount | None = None
    due_date: str | None = None


class Eligibility(BaseModel):
    can_negotiate: bool = False
    max_installments: Annotated[StrictInt, Field(ge=1, le=360)] = 1
    max_discount_percentage: Annotated[
        Decimal, Field(ge=0, le=100, allow_inf_nan=False)
    ] = Decimal(0)


class IdentityPolicy(BaseModel):
    model_config = ConfigDict(extra="forbid")
    cpf_mode: Literal["full", "first3", "first4", "last4"] = "full"
    secondary: Literal["none", "full_name", "birth_date", "both", "either"] = "either"
    max_attempts: Annotated[StrictInt, Field(ge=1, le=10)] = 3


class Fixture(BaseModel):
    model_config = ConfigDict(extra="ignore")
    customer_id: str
    full_name: str
    cpf: str
    phone: str | None = None
    birth_date: str
    institution: str
    product: str
    debt: Debt
    eligibility: Eligibility
    identity_policy: IdentityPolicy = Field(default_factory=IdentityPolicy)


def normalize_fixture(value: dict) -> dict:
    return Fixture.model_validate(value).model_dump(mode="json", exclude_none=True)
