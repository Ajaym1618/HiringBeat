import asyncio
from fastapi import APIRouter, HTTPException, BackgroundTasks, Depends
from fastapi.responses import FileResponse
from app.models.company import Company
from app.models.user import User
from app.models.app_config import AppConfig
from app.models.build_job import BuildJob
from app.models.interview import Interview
from app.schemas.admin import CreateRecruiterRequest, UpdateAppConfigRequest
from app.schemas.company import CreateCompanyRequest, PatchCompanyRequest
from app.core.auth import get_current_user, hash_password
from app.core.permissions import require_super_admin
import os

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
