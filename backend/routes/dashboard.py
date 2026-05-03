from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException

from ..auth import get_current_user
from ..database import public_user, update_user_fields
from ..schemas import CapitalUpdateRequest, MessageResponse

router = APIRouter(tags=["dashboard"])

VALID_INDEXES = {"None", "Nifty", "Sensex"}
VALID_RISK_MODES = {"Low", "Medium", "High"}


@router.get("/me")
def me(user: dict = Depends(get_current_user)) -> dict:
    return {"ok": True, "user": public_user(user)}


@router.put("/capital", response_model=MessageResponse)
def update_capital(
    payload: CapitalUpdateRequest,
    user: dict = Depends(get_current_user),
) -> MessageResponse:
    if payload.index_name not in VALID_INDEXES:
        raise HTTPException(status_code=400, detail="Invalid index selected")
    if payload.risk_mode not in VALID_RISK_MODES:
        raise HTTPException(status_code=400, detail="Invalid risk mode selected")

    updated = update_user_fields(
        user["id"],
        {
            "capital": payload.capital,
            "index_name": payload.index_name,
            "risk_mode": payload.risk_mode,
        },
    )
    return MessageResponse(
        ok=True,
        message="Capital allocation saved",
        data={"user": public_user(updated)},
    )

