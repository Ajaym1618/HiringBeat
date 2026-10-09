"""
Subscription and organisation approval enforcement helpers.

Async functions query the database; they must be awaited.
Import User and Interview inside function bodies to avoid circular imports.

Legacy pure-function exports (effective_interview_limit, effective_seat_limit,
FREE_INTERVIEW_LIMIT, FREE_SEAT_LIMIT) are kept for backward compatibility with
existing tests and routes that rely on them.
"""
from datetime import datetime, timezone
from typing import Optional
from fastapi import HTTPException
from app.models.subscription_plan import SubscriptionPlan

# ---------------------------------------------------------------------------
# Legacy constants + pure functions (backward compat)
# ---------------------------------------------------------------------------

FREE_INTERVIEW_LIMIT = 5
FREE_SEAT_LIMIT = 3


def _utc(dt: datetime) -> datetime:
    """Normalise a naive UTC datetime to timezone-aware."""
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt


def effective_interview_limit(
    interview_limit: int,
    subscription_expires_at: Optional[datetime],
) -> int:
    """Return the active interview limit for a company.

    Falls back to free-plan cap when subscription has expired.
    """
    if subscription_expires_at is not None:
        if _utc(subscription_expires_at) < datetime.now(timezone.utc):
            return FREE_INTERVIEW_LIMIT
    return interview_limit


def effective_seat_limit(
    seat_limit: int,
    subscription_expires_at: Optional[datetime],
) -> int:
    """Return the active seat limit for a company.

    Same expiry logic as effective_interview_limit.
    """
    if subscription_expires_at is not None:
        if _utc(subscription_expires_at) < datetime.now(timezone.utc):
            return FREE_SEAT_LIMIT
    return seat_limit


# ---------------------------------------------------------------------------
# New async enforcement functions (GAP 7)
# ---------------------------------------------------------------------------

async def get_active_plan(company) -> SubscriptionPlan:
    """Return the active SubscriptionPlan for a company, or raise 403."""
    if not company.subscription_plan_id or company.subscription_status != "active":
        raise HTTPException(
            status_code=403,
            detail="No active subscription. Contact admin.",
        )
    if company.subscription_expires_at:
        expires = company.subscription_expires_at
        if expires.tzinfo is None:
            expires = expires.replace(tzinfo=timezone.utc)
        if expires < datetime.now(timezone.utc):
            raise HTTPException(status_code=403, detail="Subscription has expired.")
    plan = await SubscriptionPlan.get(company.subscription_plan_id)
    if not plan:
        raise HTTPException(status_code=403, detail="Subscription plan not found.")
    return plan


async def check_org_approved(company) -> None:
    """Raise 403 if the organization is not approved/verified."""
    if company.verification_status not in ("approved", "verified"):
        if company.verification_status == "pending":
            raise HTTPException(
                status_code=403,
                detail="Organization verification is pending.",
            )
        raise HTTPException(
            status_code=403,
            detail="Organization verification was rejected.",
        )


async def enforce_recruiter_limit(company) -> None:
    """Raise 409 if the recruiter limit has been reached; raise 403 if not approved/subscribed."""
    from app.models.user import User

    await check_org_approved(company)
    plan = await get_active_plan(company)
    count = await User.find(
        {"company_id": str(company.id), "role": "recruiter"}
    ).count()
    if count >= plan.max_recruiters:
        raise HTTPException(
            status_code=409,
            detail="Recruiter limit reached for your subscription plan.",
        )


async def enforce_admin_limit(company) -> None:
    """Raise 409 if the admin limit has been reached; raise 403 if not approved/subscribed."""
    from app.models.user import User

    await check_org_approved(company)
    plan = await get_active_plan(company)
    count = await User.find(
        {"company_id": str(company.id), "role": "company_manager"}
    ).count()
    if count >= plan.max_admins:
        raise HTTPException(
            status_code=409,
            detail="Admin limit reached for your subscription plan.",
        )


async def enforce_interview_limit(company) -> None:
    """Raise 409 if the interview limit has been reached; raise 403 if not approved/subscribed."""
    from app.models.interview import Interview

    await check_org_approved(company)
    plan = await get_active_plan(company)
    count = await Interview.find(
        {"company_id": str(company.id)}
    ).count()
    if count >= plan.max_interviews:
        raise HTTPException(
            status_code=409,
            detail="Interview limit reached for your subscription plan.",
        )


async def get_subscription_usage(company) -> dict:
    """Return a dict with current usage vs plan limits. Safe to call on any company."""
    from app.models.user import User
    from app.models.interview import Interview

    try:
        plan = await get_active_plan(company)
    except HTTPException:
        return {
            "plan": None,
            "subscription_status": company.subscription_status,
            "admins_used": 0,
            "admins_limit": 0,
            "recruiters_used": 0,
            "recruiters_limit": 0,
            "interviews_used": 0,
            "interviews_limit": 0,
        }

    admins = await User.find(
        {"company_id": str(company.id), "role": "company_manager"}
    ).count()
    recruiters = await User.find(
        {"company_id": str(company.id), "role": "recruiter"}
    ).count()
    interviews = await Interview.find(
        {"company_id": str(company.id)}
    ).count()
    return {
        "plan": plan.plan_name,
        "subscription_status": company.subscription_status,
        "admins_used": admins,
        "admins_limit": plan.max_admins,
        "recruiters_used": recruiters,
        "recruiters_limit": plan.max_recruiters,
        "interviews_used": interviews,
        "interviews_limit": plan.max_interviews,
    }
