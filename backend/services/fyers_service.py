from __future__ import annotations

import hashlib
import os
from typing import Any
from urllib.parse import parse_qs, urlencode, urlparse

import requests


FYERS_AUTH_URL = "https://api-t1.fyers.in/api/v3/generate-authcode"
FYERS_TOKEN_URL = "https://api-t1.fyers.in/api/v3/validate-authcode"
FYERS_PROFILE_ENDPOINTS = (
    "https://api-t1.fyers.in/api/v3/profile",
    "https://api.fyers.in/api/v3/profile",
)


class FyersError(RuntimeError):
    pass


def configured_redirect_uri() -> str:
    return os.getenv(
        "FYERS_REDIRECT_URI",
        "https://api.thetradematic.in/api/broker/callback",
    )


def generate_auth_url(client_id: str, redirect_uri: str, state: str = "sample") -> str:
    params = {
        "client_id": client_id,
        "redirect_uri": redirect_uri,
        "response_type": "code",
        "state": state,
    }
    return f"{FYERS_AUTH_URL}?{urlencode(params)}"


def app_id_hash(client_id: str, secret_key: str) -> str:
    hash_format = os.getenv("FYERS_APP_ID_HASH_FORMAT", "concat").strip().lower()
    if hash_format == "colon":
        raw_value = f"{client_id}:{secret_key}"
    else:
        raw_value = f"{client_id}{secret_key}"
    return hashlib.sha256(raw_value.encode("utf-8")).hexdigest()


def extract_auth_code(value: str | None) -> str | None:
    if not value:
        return None
    cleaned = value.strip()
    if not cleaned:
        return None
    if "://" not in cleaned and "auth_code=" not in cleaned and "code=" not in cleaned:
        return cleaned

    parsed = urlparse(cleaned)
    query = parse_qs(parsed.query)
    for key in ("auth_code", "code"):
        if query.get(key):
            return query[key][0]
    return cleaned


def exchange_auth_code(client_id: str, secret_key: str, auth_code: str) -> dict[str, Any]:
    payload = {
        "grant_type": "authorization_code",
        "appIdHash": app_id_hash(client_id, secret_key),
        "code": auth_code.strip(),
    }
    try:
        response = requests.post(FYERS_TOKEN_URL, json=payload, timeout=20)
        data = response.json()
    except requests.RequestException as exc:
        raise FyersError(f"Fyers token request failed: {exc}") from exc
    except ValueError as exc:
        raise FyersError("Fyers token response was not JSON") from exc

    if response.ok and data.get("access_token"):
        return data
    if str(data.get("s", "")).lower() == "ok" and data.get("access_token"):
        return data

    raise FyersError(f"Fyers token exchange failed: {data}")


def verify_profile(client_id: str, access_token: str) -> dict[str, Any]:
    auth_headers = (
        {"Authorization": f"{client_id}:{access_token}"},
        {"Authorization": f"Bearer {access_token}"},
    )
    last_response: Any = None

    for endpoint in FYERS_PROFILE_ENDPOINTS:
        for headers in auth_headers:
            try:
                response = requests.get(endpoint, headers=headers, timeout=20)
                data = response.json()
            except requests.RequestException as exc:
                last_response = str(exc)
                continue
            except ValueError:
                last_response = response.text
                continue

            last_response = data
            status_value = str(data.get("s", "")).lower()
            if response.ok and status_value != "error":
                return data

    raise FyersError(f"Fyers profile verification failed: {last_response}")
