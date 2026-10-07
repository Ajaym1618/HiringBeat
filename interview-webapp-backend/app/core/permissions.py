from fastapi import HTTPException, status
from app.models.user import User
from app.models.interview import Interview


def is_recruiter_like(user: User) -> bool:
    return user.role in ("recruiter", "company_manager")


def can_run_interviews(user: User) -> bool:
    return user.role == "recruiter"


def user_can_access_interview(user: User, interview: Interview) -> bool:
    if user.role == "super_admin":
        return True
    if not is_recruiter_like(user):
        return False
    return str(user.company_id) == str(interview.company_id)


def require_super_admin(user: User):
    if user.role != "super_admin":
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Super admin only")


def require_recruiter(user: User):
    if not can_run_interviews(user):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Recruiter only")


def require_recruiter_like(user: User):
    if not is_recruiter_like(user):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Recruiter or company manager only")


def require_company_manager(user: User):
    if user.role != "company_manager":
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Company manager only")
