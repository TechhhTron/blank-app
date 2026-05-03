from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


class LoginRequest(BaseModel):
    email: str
    password: str


class LoginResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user: dict


class CapitalUpdateRequest(BaseModel):
    capital: float = Field(ge=0)
    index_name: str
    risk_mode: str


class BrokerCredentialsRequest(BaseModel):
    broker_app_id: str | None = None
    broker_secret_key: str | None = None
    broker_client_id: str | None = None
    broker_auth_code: str | None = None


class PaymentActivationRequest(BaseModel):
    plan_name: str
    payment_status: str = "active"
    payment_id: str | None = None
    demo_used: bool | None = None


class MessageResponse(BaseModel):
    ok: bool
    message: str
    data: dict | None = None

    model_config = ConfigDict(extra="allow")
