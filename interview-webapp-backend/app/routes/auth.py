from fastapi import APIRouter, HTTPException, status, Request
from app.models.user import User
from app.models.company import Company
from app.schemas.auth import RegisterRequest, LoginRequest, TokenResponse
from app.core.auth import hash_password, verify_password, create_access_token, get_current_user
from fastapi import Depends
from slowapi import Limiter
from slowapi.util import get_remote_address

limiter = Limiter(key_func=get_remote_address)
router = APIRouter(prefix="/api/auth", tags=["auth"])


@router.get("/companies")
async def list_companies():
    companies = await Company.find(Company.status == "active").to_list()
    return [{"id": str(c.id), "name": c.name} for c in companies]


@router.post("/register", status_code=status.HTTP_201_CREATED)
@limiter.limit("20/hour")
async def register(request: Request, body: RegisterRequest):
    existing = await User.find_one(User.email == body.email)
    if existing:
        raise HTTPException(status_code=400, detail="Email already registered")
    user = User(
        email=body.email,
        password_hash=hash_password(body.password),
        name=body.name,
        role="candidate",
    )
    await user.insert()
    return {"message": "Registered successfully", "user_id": str(user.id)}


@router.post("/login")
@limiter.limit("20/minute")
async def login(request: Request, body: LoginRequest):
    user = await User.find_one(User.email == body.email)
    if not user or not verify_password(body.password, user.password_hash):
        raise HTTPException(status_code=401, detail="Invalid credentials")

    # Role mismatch check
    if body.role and user.role != body.role:
        raise HTTPException(status_code=403, detail="Role mismatch")

    # company_id mismatch for recruiter-like
    if user.role in ("recruiter", "company_manager"):
        if body.company_id and str(user.company_id) != str(body.company_id):
            raise HTTPException(status_code=403, detail="Company mismatch")
        # Validate company status — only block rejected/inactive orgs (GAP 4).
        # Pending orgs (status=="pending_verification") are allowed to authenticate;
        # management actions are blocked separately by subscription enforcement.
        if user.company_id:
            company = await Company.get(user.company_id)
            if company:
                if company.status == "rejected":
                    raise HTTPException(status_code=403, detail="Company has been rejected")
                if company.status == "inactive":
                    raise HTTPException(status_code=403, detail="Company is inactive")

    token_data: dict = {"user_id": str(user.id), "role": user.role}
    if user.company_id:
        token_data["company_id"] = str(user.company_id)
    token = create_access_token(token_data)
    return TokenResponse(
        access_token=token,
        role=user.role,
        name=user.name,
        user_id=str(user.id),
    )


@router.get("/me")
async def me(current_user: User = Depends(get_current_user)):
    return {
        "user_id": str(current_user.id),
        "email": current_user.email,
        "name": current_user.name,
        "role": current_user.role,
        "company_id": current_user.company_id,
        "title": current_user.title,
    }
