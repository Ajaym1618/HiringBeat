from fastapi import APIRouter, HTTPException, Depends, status
from app.models.user import User
from app.schemas.admin import CreateRecruiterRequest
from app.core.auth import get_current_user, hash_password
from app.core.permissions import require_company_manager

router = APIRouter(prefix="/api/company", tags=["company"])


@router.get("/team")
async def get_team(current_user: User = Depends(get_current_user)):
    require_company_manager(current_user)
    members = await User.find(
        {"company_id": current_user.company_id, "role": {"$in": ["recruiter", "company_manager"]}}
    ).to_list()
    return [
        {"id": str(u.id), "email": u.email, "name": u.name, "role": u.role}
        for u in members
    ]


@router.post("/team", status_code=status.HTTP_201_CREATED)
async def add_team_member(
    body: CreateRecruiterRequest,
    current_user: User = Depends(get_current_user),
):
    require_company_manager(current_user)
    existing = await User.find_one(User.email == body.email)
    if existing:
        raise HTTPException(status_code=400, detail="Email already exists")
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
    await user.delete()
