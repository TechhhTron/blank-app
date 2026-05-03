from __future__ import annotations

from datetime import datetime, timedelta, timezone


PLAN_DAYS = {
    "demo": 7,
    "monthly": 30,
    "quarterly": 90,
}


def now_utc() -> datetime:
    return datetime.now(timezone.utc)


def iso_now() -> str:
    return now_utc().isoformat()


def plan_to_days(plan_name: str | None) -> int:
    if not plan_name:
        return PLAN_DAYS["monthly"]
    return PLAN_DAYS.get(plan_name.strip().lower(), PLAN_DAYS["monthly"])


def expiry_for_plan(plan_name: str | None) -> str:
    return (now_utc() + timedelta(days=plan_to_days(plan_name))).isoformat()


def display_datetime(value: str | None) -> str:
    if not value:
        return "Never"
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return value
    return parsed.astimezone().strftime("%d/%m/%Y %I:%M:%S %p")

