from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import HTMLResponse

from ..auth import get_current_user
from ..database import (
    consume_broker_auth_request,
    create_broker_auth_request,
    get_user_by_id,
    public_user,
    update_user_fields,
)
from ..schemas import BrokerCredentialsRequest, MessageResponse
from ..services.fyers_service import (
    FyersError,
    configured_redirect_uri,
    exchange_auth_code,
    extract_auth_code,
    generate_auth_url,
    verify_profile,
)
from ..utils import iso_now

router = APIRouter(tags=["broker"])


def _credentials_from_payload(user: dict, payload: BrokerCredentialsRequest) -> dict:
    app_id = (payload.broker_app_id or user.get("broker_app_id") or "").strip()
    secret_key = (payload.broker_secret_key or user.get("broker_secret_key") or "").strip()
    client_id = (
        payload.broker_client_id
        or user.get("broker_client_id")
        or app_id
    ).strip()
    if not client_id:
        raise HTTPException(status_code=400, detail="Broker client ID is required")
    if not secret_key:
        raise HTTPException(status_code=400, detail="Broker secret key is required")
    return {
        "broker_app_id": app_id or client_id,
        "broker_secret_key": secret_key,
        "broker_client_id": client_id,
    }


@router.put("/credentials", response_model=MessageResponse)
def save_credentials(
    payload: BrokerCredentialsRequest,
    user: dict = Depends(get_current_user),
) -> MessageResponse:
    credentials = _credentials_from_payload(user, payload)
    updated = update_user_fields(user["id"], credentials)
    return MessageResponse(
        ok=True,
        message="Broker credentials saved",
        data={"user": public_user(updated)},
    )


@router.post("/start", response_model=MessageResponse)
def start_authorization(
    payload: BrokerCredentialsRequest,
    user: dict = Depends(get_current_user),
) -> MessageResponse:
    credentials = _credentials_from_payload(user, payload)
    updated = update_user_fields(user["id"], credentials)
    state = "sample"
    redirect_uri = configured_redirect_uri()
    create_broker_auth_request(updated["id"], state, redirect_uri)
    auth_url = generate_auth_url(updated["broker_client_id"], redirect_uri, state)
    return MessageResponse(
        ok=True,
        message="Broker authorization URL generated",
        data={"auth_url": auth_url, "user": public_user(updated)},
    )


def complete_broker_callback(
    code: str | None = None,
    auth_code: str | None = None,
    state: str | None = None,
) -> HTMLResponse:
    received_code = code or auth_code
    if not received_code:
        return HTMLResponse(
            "<h3>Broker authorization failed</h3><p>No auth code was returned.</p>",
            status_code=400,
        )

    request_row = consume_broker_auth_request(state)
    if not request_row:
        return HTMLResponse(
            "<h3>Broker authorization failed</h3><p>No pending authorization request was found.</p>",
            status_code=400,
        )

    user = get_user_by_id(int(request_row["user_id"]))
    if not user:
        return HTMLResponse(
            "<h3>Broker authorization failed</h3><p>The member account was not found.</p>",
            status_code=404,
        )

    client_id = user.get("broker_client_id") or user.get("broker_app_id")
    secret_key = user.get("broker_secret_key")
    if not client_id or not secret_key:
        return HTMLResponse(
            "<h3>Broker authorization failed</h3><p>Broker credentials are missing.</p>",
            status_code=400,
        )

    try:
        token_response = exchange_auth_code(client_id, secret_key, received_code)
    except FyersError as exc:
        update_user_fields(
            user["id"],
            {
                "broker_auth_code": received_code,
                "broker_connected": 0,
            },
        )
        return HTMLResponse(
            f"<h3>Broker authorization failed</h3><p>{exc}</p>",
            status_code=400,
        )

    access_token = token_response["access_token"]
    timestamp = iso_now()
    update_user_fields(
        user["id"],
        {
            "broker_auth_code": received_code,
            "broker_session_token": access_token,
            "broker_connected": 0,
            "last_authorized_at": timestamp,
        },
    )
    return HTMLResponse(
        """
        <h3>Broker authorization complete</h3>
        <p>The session token was saved. You can close this tab and click
        Save Broker Credentials in the Streamlit dashboard to verify the connection.</p>
        """
    )


@router.get("/callback")
def broker_callback(
    code: str | None = Query(default=None),
    auth_code: str | None = Query(default=None),
    state: str | None = Query(default=None),
) -> HTMLResponse:
    return complete_broker_callback(code=code, auth_code=auth_code, state=state)


@router.post("/confirm", response_model=MessageResponse)
def confirm_connection(
    payload: BrokerCredentialsRequest,
    user: dict = Depends(get_current_user),
) -> MessageResponse:
    credentials = _credentials_from_payload(user, payload)
    updated = update_user_fields(user["id"], credentials)
    submitted_auth_code = extract_auth_code(payload.broker_auth_code)
    if submitted_auth_code:
        try:
            token_response = exchange_auth_code(
                updated["broker_client_id"],
                updated["broker_secret_key"],
                submitted_auth_code,
            )
        except FyersError as exc:
            update_user_fields(
                updated["id"],
                {
                    "broker_auth_code": submitted_auth_code,
                    "broker_connected": 0,
                },
            )
            raise HTTPException(status_code=400, detail=str(exc)) from exc

        updated = update_user_fields(
            updated["id"],
            {
                "broker_auth_code": submitted_auth_code,
                "broker_session_token": token_response["access_token"],
                "broker_connected": 0,
                "last_authorized_at": iso_now(),
            },
        )

    token = updated.get("broker_session_token")
    if not token:
        raise HTTPException(
            status_code=400,
            detail=(
                "No broker session token found. Authorize the broker first. "
                "If FYERS redirects to an external page, paste the returned auth_code "
                "or full redirect URL before clicking Save Broker Credentials."
            ),
        )

    try:
        profile = verify_profile(updated["broker_client_id"], token)
    except FyersError as exc:
        update_user_fields(updated["id"], {"broker_connected": 0})
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    timestamp = iso_now()
    updated = update_user_fields(
        updated["id"],
        {
            "broker_connected": 1,
            "last_authorized_at": timestamp,
        },
    )
    return MessageResponse(
        ok=True,
        message="Broker connection verified",
        data={"user": public_user(updated), "profile": profile},
    )


@router.get("/status")
def broker_status(user: dict = Depends(get_current_user)) -> dict:
    return {
        "ok": True,
        "broker_connected": bool(user.get("broker_connected")),
        "broker_token_saved": bool(user.get("broker_session_token")),
        "last_authorized_at": user.get("last_authorized_at"),
    }
