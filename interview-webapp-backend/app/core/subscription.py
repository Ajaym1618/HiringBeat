"""Subscription and organization approval enforcement helpers."""

from datetime import datetime, timezone
from fastapi import HTTPException
from app.models.subscription_plan import SubscriptionPlan


def _utc(dt: datetime) -> datetime:
    """Normalize a naive datetime to UTC."""
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


async def get_active_plan(company) -> SubscriptionPlan:
    """Require an assigned, active, unexpired subscription plan."""
    if (
        not getattr(company, "subscription_plan_id", None)
        or getattr(company, "subscription_status", None) != "active"
    ):
        raise HTTPException(
            status_code=403,
            detail="No active subscription. Contact admin.",
        )

    expires_at = getattr(company, "subscription_expires_at", None)

    if expires_at and _utc(expires_at) <= datetime.now(timezone.utc):
        raise HTTPException(
            status_code=403,
            detail="Subscription has expired.",
        )

    plan = await SubscriptionPlan.get(company.subscription_plan_id)

    if not plan:
        raise HTTPException(
            status_code=403,
            detail="Subscription plan not found.",
        )

    if plan.status != "active":
        raise HTTPException(
            status_code=403,
            detail="Subscription plan is inactive.",
        )

    return plan


async def check_org_approved(company) -> None:
    """Require an active organization with approved verification."""
    company_status = getattr(company, "status", None)

    if company_status not in (None, "active"):
        raise HTTPException(
            status_code=403,
            detail="Organization is inactive or restricted.",
        )

    verification_status = getattr(
        company, "verification_status", None
    )

    if verification_status not in ("approved", "verified"):
        if verification_status == "pending":
            raise HTTPException(
                status_code=403,
                detail="Organization verification is pending.",
            )

        raise HTTPException(
            status_code=403,
            detail="Organization verification was rejected.",
        )


async def enforce_recruiter_limit(company) -> None:
    """Require approval and subscription, then enforce recruiter limits."""
    from app.models.user import User

    await check_org_approved(company)
    plan = await get_active_plan(company)

    count = await User.find(
        {
            "company_id": str(company.id),
            "role": "recruiter",
        }
    ).count()

    if count >= plan.max_recruiters:
        raise HTTPException(
            status_code=409,
            detail="Recruiter limit reached for your subscription plan.",
        )


async def enforce_admin_limit(company) -> None:
    """Require approval and subscription, then enforce admin limits."""
    from app.models.user import User

    await check_org_approved(company)
    plan = await get_active_plan(company)

    count = await User.find(
        {
            "company_id": str(company.id),
            "role": "company_manager",
        }
    ).count()

    if count >= plan.max_admins:
        raise HTTPException(
            status_code=409,
            detail="Admin limit reached for your subscription plan.",
        )


async def enforce_interview_limit(company) -> None:
    """Require approval and subscription, then enforce interview limits."""
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
    """Return current organization usage and plan limits."""
    from app.models.user import User
    from app.models.interview import Interview

    admins = await User.find(
        {
            "company_id": str(company.id),
            "role": "company_manager",
        }
    ).count()

    recruiters = await User.find(
        {
            "company_id": str(company.id),
            "role": "recruiter",
        }
    ).count()

    interviews = await Interview.find(
        {"company_id": str(company.id)}
    ).count()

    try:
        plan = await get_active_plan(company)
    except HTTPException:
        return {
            "plan": None,
            "subscription_status": getattr(
                company, "subscription_status", None
            ),
            "admins_used": admins,
            "admins_limit": 0,
            "recruiters_used": recruiters,
            "recruiters_limit": 0,
            "interviews_used": interviews,
            "interviews_limit": 0,
        }

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