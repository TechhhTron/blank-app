from __future__ import annotations

from fastapi import APIRouter, HTTPException, status

from ..auth import create_access_token, verify_password
from ..database import get_user_by_email, public_user
from ..schemas import LoginRequest, LoginResponse

router = APIRouter(tags=["auth"])


@router.post("/login", response_model=LoginResponse)
def login(payload: LoginRequest) -> LoginResponse:
    user = get_user_by_email(payload.email)
    if not user or not verify_password(payload.password, user["password_hash"]):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid email or password",
        )
    return LoginResponse(access_token=create_access_token(user), user=public_user(user))

