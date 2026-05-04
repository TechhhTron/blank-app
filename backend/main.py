from __future__ import annotations

import os

from fastapi import FastAPI, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse

from .database import init_db
from .routes import broker, dashboard, payment, user

app = FastAPI(title="Tradematic Backend", version="1.0.0")


def _cors_origins() -> list[str]:
    configured = os.getenv("CORS_ORIGINS")
    if configured:
        return [origin.strip().rstrip("/") for origin in configured.split(",") if origin.strip()]
    return [
        "http://localhost",
        "http://localhost:8501",
        "http://localhost:8502",
        "http://127.0.0.1:8501",
        "http://127.0.0.1:8502",
        "https://api.thetradematic.in",
        "https://thetradematic.in",
        "https://www.thetradematic.in",
    ]


app.add_middleware(
    CORSMiddleware,
    allow_origins=_cors_origins(),
    allow_origin_regex=os.getenv("CORS_ALLOW_ORIGIN_REGEX", r"https://.*\.streamlit\.app"),
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.on_event("startup")
def startup() -> None:
    init_db()


@app.get("/", response_model=None)
def root(
    code: str | None = Query(default=None),
    auth_code: str | None = Query(default=None),
    state: str | None = Query(default=None),
):
    if code or auth_code:
        return broker.complete_broker_callback(code=code, auth_code=auth_code, state=state)
    return {"ok": True, "message": "Tradematic backend is running"}


@app.get("/health")
def health() -> dict:
    return {"ok": True, "service": "tradematic-backend"}


app.include_router(user.router, prefix="/api/auth")
app.include_router(dashboard.router, prefix="/api/dashboard")
app.include_router(payment.router, prefix="/api/payment")
app.include_router(broker.router, prefix="/api/broker")
