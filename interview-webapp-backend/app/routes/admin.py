import asyncio
import os
from datetime import datetime, timezone
from fastapi import APIRouter, HTTPException, BackgroundTasks, Depends
from fastapi.responses import FileResponse
from app.models.company import Company
from app.models.user import User
from app.models.app_config import AppConfig
from app.models.build_job import BuildJob
from app.models.interview import Interview
from app.models.org_document import OrgDocument
from app.models.subscription_plan import SubscriptionPlan
from app.schemas.admin import CreateRecruiterRequest, UpdateAppConfigRequest
from app.schemas.company import CreateCompanyRequest, PatchCompanyRequest
from app.schemas.org import RejectOrgRequest, PatchSubscriptionRequest
from app.core.auth import get_current_user, hash_password
from app.core.permissions import require_super_admin
from app.core.subscription import get_subscription_usage
from bson.errors import InvalidId
from typing import Optional

router = APIRouter(prefix="/api/admin", tags=["admin"])


# --- App Config ---
@router.get("/app-config/public")
async def get_app_config_public():
    config = await AppConfig.find_one()
    if not config:
        return {"app_name": "CrudBeat Proctor"}
    return {"app_name": config.app_name, "logo_path": config.logo_path}


@router.get("/app-config")
async def get_app_config(current_user: User = Depends(get_current_user)):
    require_super_admin(current_user)
    config = await AppConfig.find_one()
    if not config:
        return {}
    return config.model_dump()


@router.put("/app-config")
async def update_app_config(
    body: UpdateAppConfigRequest, current_user: User = Depends(get_current_user)
):
    require_super_admin(current_user)
    config = await AppConfig.find_one()
    if not config:
        config = AppConfig()
        await config.insert()
    update_data = {k: v for k, v in body.model_dump().items() if v is not None}
    await config.set(update_data)
    return {"updated": True}


# --- Companies ---
@router.get("/companies")
async def list_companies(current_user: User = Depends(get_current_user)):
    # Returns companies of all statuses including pending_verification and rejected.
    require_super_admin(current_user)
    companies = await Company.find_all().to_list()
    return [{"id": str(c.id), "name": c.name, "status": c.status} for c in companies]


@router.post("/companies", status_code=201)
async def create_company(
    body: CreateCompanyRequest, current_user: User = Depends(get_current_user)
):
    require_super_admin(current_user)
    company = Company(name=body.name, status=body.status)
    await company.insert()
    return {"id": str(company.id), "name": company.name}


@router.patch("/companies/{company_id}")
async def patch_company(
    company_id: str,
    body: PatchCompanyRequest,
    current_user: User = Depends(get_current_user),
):
    require_super_admin(current_user)
    company = await Company.get(company_id)
    if not company:
        raise HTTPException(status_code=404, detail="Company not found")
    update_data = {k: v for k, v in body.model_dump().items() if v is not None}
    if update_data:
        await company.set(update_data)
    return {"updated": True}


# --- Recruiters ---
@router.get("/recruiters")
async def list_recruiters(current_user: User = Depends(get_current_user)):
    require_super_admin(current_user)
    recruiters = await User.find(
        {"role": {"$in": ["recruiter", "company_manager"]}}
    ).to_list()
    return [
        {"id": str(u.id), "email": u.email, "name": u.name, "role": u.role, "company_id": u.company_id}
        for u in recruiters
    ]


@router.post("/recruiters", status_code=201)
async def create_recruiter(
    body: CreateRecruiterRequest, current_user: User = Depends(get_current_user)
):
    require_super_admin(current_user)
    existing = await User.find_one(User.email == body.email)
    if existing:
        raise HTTPException(status_code=400, detail="Email already exists")
    user = User(
        email=body.email,
        password_hash=hash_password(body.password),
        name=body.name,
        role=body.role,
        company_id=body.company_id,
        title=body.title,
    )
    await user.insert()
    return {"id": str(user.id), "email": user.email}


@router.delete("/recruiters/{user_id}", status_code=204)
async def delete_recruiter(
    user_id: str, current_user: User = Depends(get_current_user)
):
    require_super_admin(current_user)
    user = await User.get(user_id)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    await user.delete()


@router.get("/recruiters/{user_id}/interviews")
async def recruiter_interviews(
    user_id: str, current_user: User = Depends(get_current_user)
):
    require_super_admin(current_user)
    interviews = await Interview.find(Interview.recruiter_id == user_id).to_list()
    return [{"id": str(i.id), "title": i.title, "status": i.status} for i in interviews]


# --- Deployment / Build ---
async def _fake_build(job_id: str):
    """Simulated background build process."""
    job = await BuildJob.get(job_id)
    if not job:
        return
    job.status = "building"
    await job.save()
    await asyncio.sleep(5)  # simulate build time
    job.status = "done"
    job.log_tail = "Build completed successfully (stub)"
    job.output_file = "installer-stub.exe"
    await job.save()


@router.get("/deployment-status")
async def deployment_status(current_user: User = Depends(get_current_user)):
    require_super_admin(current_user)
    return {"status": "ready", "version": "1.0.0-stub"}


@router.post("/build-app", status_code=202)
async def build_app(
    background_tasks: BackgroundTasks, current_user: User = Depends(get_current_user)
):
    require_super_admin(current_user)
    job = BuildJob()
    await job.insert()
    background_tasks.add_task(_fake_build, str(job.id))
    return {"job_id": str(job.id)}


@router.get("/build-status/{job_id}")
async def build_status(job_id: str, current_user: User = Depends(get_current_user)):
    require_super_admin(current_user)
    job = await BuildJob.get(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    return {
        "job_id": str(job.id),
        "status": job.status,
        "log_tail": job.log_tail,
        "output_file": job.output_file,
    }


@router.get("/download-installer")
async def download_installer(current_user: User = Depends(get_current_user)):
    require_super_admin(current_user)
    # Stub: return 404 until a real build produces the file
    raise HTTPException(status_code=404, detail="No installer available (stub)")


# ---------------------------------------------------------------------------
# Org-management helpers
# ---------------------------------------------------------------------------

async def get_company_or_404(company_id: str) -> Company:
    """Fetch company by ID; raises HTTP 404 for both not-found and malformed ObjectId."""
    try:
        company = await Company.get(company_id)
    except (InvalidId, Exception):
        raise HTTPException(status_code=404, detail="Company not found")
    if not company:
        raise HTTPException(status_code=404, detail="Company not found")
    return company


def _company_out(c: Company) -> dict:
    return {
        "id": str(c.id),
        "name": c.name,
        "status": c.status,
        "verification_status": c.verification_status,
        # Legacy subscription fields (kept for backward compat)
        "plan": c.plan,
        "interview_limit": c.interview_limit,
        "seat_limit": c.seat_limit,
        "subscription_expires_at": c.subscription_expires_at,
        # New subscription fields
        "subscription_plan_id": c.subscription_plan_id,
        "subscription_status": c.subscription_status,
        "subscription_started_at": c.subscription_started_at,
        # Verification
        "verified_at": c.verified_at,
        "verified_by": c.verified_by,
        "rejection_reason": c.rejection_reason,
        # New org identity fields
        "org_type": c.org_type,
        "registration_number": c.registration_number,
        "pan": c.pan,
        "gstin": c.gstin,
        "registered_address": c.registered_address,
        "website": c.website,
        "official_phone": c.official_phone,
        "authorized_person_name": c.authorized_person_name,
        "authorized_person_designation": c.authorized_person_designation,
        "authorized_person_email": c.authorized_person_email,
        "authorized_person_phone": c.authorized_person_phone,
    }


# ---------------------------------------------------------------------------
# Org-management routes
# ---------------------------------------------------------------------------

@router.get("/orgs/pending")
async def list_pending_orgs(current_user: User = Depends(get_current_user)):
    """List all organizations awaiting verification."""
    require_super_admin(current_user)
    companies = await Company.find(
        Company.status == "pending_verification"
    ).to_list()

    result = []
    for c in companies:
        # N+1 pattern acknowledged; acceptable at MVP scale per 20/hour rate limit on registration.
        manager = await User.find_one(
            {"company_id": str(c.id), "role": "company_manager"}
        )
        manager_out = (
            {"id": str(manager.id), "email": manager.email, "name": manager.name}
            if manager
            else None
        )
        result.append({
            "id": str(c.id),
            "name": c.name,
            "status": c.status,
            "verification_status": c.verification_status,
            "created_at": c.created_at,
            "manager": manager_out,
        })
    return result


@router.get("/orgs")
async def list_all_orgs(
    status: Optional[str] = None,
    current_user: User = Depends(get_current_user),
):
    """List ALL organizations with optional ?status= filter. Super admin only."""
    require_super_admin(current_user)
    if status:
        companies = await Company.find(Company.status == status).to_list()
    else:
        companies = await Company.find_all().to_list()

    result = []
    for c in companies:
        manager = await User.find_one({"company_id": str(c.id), "role": "company_manager"})
        manager_out = (
            {"id": str(manager.id), "email": manager.email, "name": manager.name}
            if manager
            else None
        )
        entry = _company_out(c)
        entry["manager"] = manager_out
        result.append(entry)
    return result


@router.get("/orgs/{company_id}/documents/{doc_id}/download")
async def download_org_document(
    company_id: str,
    doc_id: str,
    current_user: User = Depends(get_current_user),
):
    """Securely download an organization verification document. Super admin only."""
    require_super_admin(current_user)
    doc = await OrgDocument.get(doc_id)
    if not doc or doc.company_id != company_id:
        raise HTTPException(status_code=404, detail="Document not found")
    if not os.path.exists(doc.storage_path):
        raise HTTPException(status_code=404, detail="Document file not found on disk")
    return FileResponse(
        path=doc.storage_path,
        filename=doc.file_name,
        media_type="application/octet-stream",
    )


@router.get("/orgs/{company_id}/documents")
async def list_org_documents(
    company_id: str,
    current_user: User = Depends(get_current_user),
):
    """List document metadata for an organization. Super admin only."""
    require_super_admin(current_user)
    await get_company_or_404(company_id)  # 404 if company missing
    docs = await OrgDocument.find({"company_id": company_id}).to_list()
    return [
        {
            "id": str(d.id),
            "company_id": d.company_id,
            "document_type": d.document_type,
            "file_name": d.file_name,
            "uploaded_at": d.uploaded_at,
            "uploaded_by": d.uploaded_by,
            "verification_status": d.verification_status,
        }
        for d in docs
    ]


@router.get("/orgs/{company_id}/subscription")
async def get_org_subscription(
    company_id: str,
    current_user: User = Depends(get_current_user),
):
    """Return current subscription plan and usage for a company. Super admin only."""
    require_super_admin(current_user)
    company = await get_company_or_404(company_id)
    usage = await get_subscription_usage(company)
    return usage


@router.get("/orgs/{company_id}")
async def get_org_detail(
    company_id: str,
    current_user: User = Depends(get_current_user),
):
    """Return full company details. Super admin only."""
    require_super_admin(current_user)
    company = await get_company_or_404(company_id)
    manager = await User.find_one({"company_id": company_id, "role": "company_manager"})
    manager_out = (
        {"id": str(manager.id), "email": manager.email, "name": manager.name}
        if manager
        else None
    )
    out = _company_out(company)
    out["manager"] = manager_out
    return out


@router.post("/orgs/{company_id}/approve")
async def approve_org(
    company_id: str,
    current_user: User = Depends(get_current_user),
):
    """Approve a pending organization. Checks required documents first."""
    require_super_admin(current_user)
    company = await get_company_or_404(company_id)

    # Required documents that MUST be uploaded before approval
    REQUIRED_DOC_TYPES = {
        "certificate_of_incorporation",
        "pan_document",
        "address_proof",
        "authorized_person_id",
    }
    # gst_certificate and authorization_letter are conditional/optional

    uploaded_docs = await OrgDocument.find({"company_id": company_id}).to_list()
    uploaded_types = {d.document_type for d in uploaded_docs}
    missing = REQUIRED_DOC_TYPES - uploaded_types

    if missing:
        raise HTTPException(
            status_code=422,
            detail=f"Cannot approve: missing required documents: {', '.join(sorted(missing))}",
        )

    # Idempotent: only call set() if not already active
    if company.status != "active":
        await company.set({
            "status": "active",
            "verification_status": "approved",
            "verified_at": datetime.now(timezone.utc),
            "verified_by": str(current_user.id),
        })
        await company.sync()

    return _company_out(company)


@router.patch("/orgs/{company_id}/approve")
async def approve_org_patch(
    company_id: str,
    current_user: User = Depends(get_current_user),
):
    """PATCH alias for approve_org — same logic."""
    return await approve_org(company_id=company_id, current_user=current_user)


@router.post("/orgs/{company_id}/reject")
async def reject_org(
    company_id: str,
    body: RejectOrgRequest,
    current_user: User = Depends(get_current_user),
):
    """Reject a pending organization. Idempotent — safe to call on already-rejected orgs."""
    require_super_admin(current_user)
    company = await get_company_or_404(company_id)

    # Idempotent: only call set() if not already rejected
    if company.status != "rejected":
        await company.set({
            "status": "rejected",
            "verification_status": "rejected",
            "rejection_reason": body.reason,
        })
        # sync() re-fetches the document so _company_out reflects the stored state
        await company.sync()

    return _company_out(company)


@router.patch("/orgs/{company_id}/reject")
async def reject_org_patch(
    company_id: str,
    body: RejectOrgRequest,
    current_user: User = Depends(get_current_user),
):
    """PATCH alias for reject_org — same logic."""
    return await reject_org(company_id=company_id, body=body, current_user=current_user)


@router.patch("/orgs/{company_id}/subscription")
async def patch_subscription(
    company_id: str,
    body: PatchSubscriptionRequest,
    current_user: User = Depends(get_current_user),
):
    """Update subscription plan for a company. Only super_admin can call this."""
    require_super_admin(current_user)
    company = await get_company_or_404(company_id)

    if body.plan_id:
        # New plan-id based update
        plan = await SubscriptionPlan.get(body.plan_id)
        if not plan:
            raise HTTPException(status_code=404, detail="Subscription plan not found")
        update: dict = {
            "subscription_plan_id": body.plan_id,
            "subscription_status": "active",
            "subscription_started_at": datetime.now(timezone.utc),
        }
        if body.expires_at is not None:
            update["subscription_expires_at"] = body.expires_at
        await company.set(update)
        await company.sync()
    else:
        # Legacy field-based update (backward compat for tests)
        update = body.model_dump(exclude_unset=True)
        # Remove plan_id and expires_at from legacy update if they're None
        update.pop("plan_id", None)
        update.pop("expires_at", None)
        if update:
            await company.set(update)
            await company.sync()

    return _company_out(company)


@router.get("/subscription-plans")
async def list_subscription_plans(current_user: User = Depends(get_current_user)):
    """List all available subscription plans. Super admin only."""
    require_super_admin(current_user)
    plans = await SubscriptionPlan.find_all().to_list()
    return [
        {
            "id": str(p.id),
            "plan_name": p.plan_name,
            "max_admins": p.max_admins,
            "max_recruiters": p.max_recruiters,
            "max_interviews": p.max_interviews,
            "status": p.status,
        }
        for p in plans
    ]
