from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException

from ..auth import get_current_user
from ..database import public_user, update_user_fields
from ..schemas import MessageResponse, PaymentActivationRequest
from ..utils import expiry_for_plan, plan_to_days

router = APIRouter(tags=["payment"])


@router.post("/activate", response_model=MessageResponse)
def activate_payment(
    payload: PaymentActivationRequest,
    user: dict = Depends(get_current_user),
) -> MessageResponse:
    if payload.plan_name.strip().lower() not in {"demo", "monthly", "quarterly"}:
        raise HTTPException(status_code=400, detail="Invalid plan name")

    fields = {
        "plan_name": payload.plan_name,
        "subscription_days": plan_to_days(payload.plan_name),
        "subscription_expires_at": expiry_for_plan(payload.plan_name),
        "payment_status": payload.payment_status,
        "payment_id": payload.payment_id,
    }
    if payload.demo_used is not None:
        fields["demo_used"] = int(payload.demo_used)

    updated = update_user_fields(user["id"], fields)
    return MessageResponse(
        ok=True,
        message="Payment plan activated",
        data={"user": public_user(updated)},
    )

