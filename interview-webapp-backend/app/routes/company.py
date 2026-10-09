from fastapi import APIRouter, HTTPException, Depends, status
from app.models.user import User
from app.models.company import Company
from app.schemas.admin import CreateRecruiterRequest
from app.schemas.org import UpdateRoleRequest
from app.core.auth import get_current_user, hash_password
from app.core.permissions import require_company_manager
from app.core.subscription import (
    enforce_recruiter_limit, enforce_admin_limit,
)
from bson.errors import InvalidId

router = APIRouter(prefix="/api/company", tags=["company"])


async def get_user_or_404(user_id: str) -> User:
    """Fetch user by ID; raises HTTP 404 for both not-found and malformed ObjectId."""
    try:
        user = await User.get(user_id)
    except (InvalidId, Exception):
        raise HTTPException(status_code=404, detail="User not found")
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    return user


@router.get("/team")
async def get_team(
    current_user: User = Depends(get_current_user),
    include_usage: bool = False,  # ?include_usage=true for seat_usage (FIX 4)
):
    require_company_manager(current_user)
    members = await User.find(
        {"company_id": current_user.company_id, "role": {"$in": ["recruiter", "company_manager"]}}
    ).to_list()
    member_list = [
        {"id": str(u.id), "email": u.email, "name": u.name, "role": u.role}
        for u in members
    ]

    if not include_usage:
        # Backward-compatible: return bare list
        return member_list

    # include_usage=true: return wrapped response with subscription usage
    try:
        company = await Company.get(current_user.company_id)
    except Exception:
        company = None
    from app.core.subscription import get_subscription_usage
    usage = await get_subscription_usage(company) if company else {}
    return {
        "members": member_list,
        "seat_usage": {
            "used": len(members),
            "admins_limit": usage.get("admins_limit", 0),
            "recruiters_limit": usage.get("recruiters_limit", 0),
        },
    }


@router.post("/team", status_code=status.HTTP_201_CREATED)
async def add_team_member(
    body: CreateRecruiterRequest,
    current_user: User = Depends(get_current_user),
):
    require_company_manager(current_user)

    # --- seat-limit check (FR-6) — before email check to avoid leaking email existence ---
    try:
        company = await Company.get(current_user.company_id)
    except (InvalidId, Exception):
        raise HTTPException(status_code=403, detail="Company not found")
    if not company:
        raise HTTPException(status_code=403, detail="Company not found")

    # Block pending/rejected orgs from adding team members
    if company.status not in ("active",):
        raise HTTPException(status_code=403, detail="Company is not active")

    # Use new per-role enforcement — no legacy fallback
    if body.role == "recruiter":
        await enforce_recruiter_limit(company)
    else:
        await enforce_admin_limit(company)

    existing = await User.find_one(User.email == body.email)
    if existing:
        raise HTTPException(status_code=400, detail="Email already exists")

    # Always use current_user.company_id — body.company_id is intentionally ignored
    user = User(
        email=body.email,
        password_hash=hash_password(body.password),
        name=body.name,
        role=body.role,
        company_id=str(current_user.company_id),
        title=body.title,
    )
    await user.insert()
    return {"id": str(user.id), "email": user.email}


@router.delete("/team/{user_id}", status_code=status.HTTP_204_NO_CONTENT)
async def remove_team_member(
    user_id: str,
    current_user: User = Depends(get_current_user),
):
    require_company_manager(current_user)
    user = await User.get(user_id)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    if user.company_id != current_user.company_id:
        raise HTTPException(status_code=403, detail="Cannot remove user from another company")
    # Removal is permitted regardless of subscription/verification status.
    # Cleanup operations must not be blocked during pending or suspended states.
    await user.delete()


@router.patch("/team/{user_id}")
async def update_team_member_role(
    user_id: str,
    body: UpdateRoleRequest,
    current_user: User = Depends(get_current_user),
):
    require_company_manager(current_user)

    # Self-demotion guard (FR-8.3)
    if user_id == str(current_user.id):
        raise HTTPException(status_code=403, detail="Cannot change your own role")

    target = await get_user_or_404(user_id)

    # Cross-company guard (FR-8.2)
    if target.company_id != current_user.company_id:
        raise HTTPException(status_code=403, detail="User belongs to a different company")

    # Subscription limit check for role promotion
    try:
        company = await Company.get(current_user.company_id)
    except Exception:
        company = None
    if company:
        if body.role == "company_manager" and target.role != "company_manager":
            await enforce_admin_limit(company)
        elif body.role == "recruiter" and target.role != "recruiter":
            await enforce_recruiter_limit(company)

    # Last-manager guard (FR-8.4): only applies when demoting a company_manager
    if target.role == "company_manager" and body.role == "recruiter":
        manager_count = await User.find(
            {"company_id": current_user.company_id, "role": "company_manager"}
        ).count()
        if manager_count <= 1:
            raise HTTPException(status_code=409, detail="LAST_MANAGER_GUARD")

    await target.set({"role": body.role})
    # No sync() needed — response uses body.role directly, not re-read from document.
    # UpdateRoleRequest.role is Literal["recruiter", "company_manager"];
    # any other value (e.g. "candidate") produces HTTP 422 via Pydantic (FR-8.5).
    return {"id": str(target.id), "role": body.role}
