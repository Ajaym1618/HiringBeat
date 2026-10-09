import os
import re as _re
import uuid
import aiofiles
from fastapi import APIRouter, HTTPException, status, Request, Depends, UploadFile, File, Form
from typing import List
from app.models.company import Company
from app.models.user import User
from app.models.org_document import OrgDocument
from app.core.auth import hash_password, get_current_user
from app.schemas.org import OrgRegisterRequest, OrgDocumentOut
from app.config import settings
from slowapi import Limiter
from slowapi.util import get_remote_address

limiter = Limiter(key_func=get_remote_address)
router = APIRouter(prefix="/api/org", tags=["org"])

ALLOWED_MIME_TYPES = {"application/pdf", "image/jpeg", "image/jpg", "image/png"}
ALLOWED_EXTENSIONS = {".pdf", ".jpg", ".jpeg", ".png"}
MAX_FILE_SIZE_BYTES = 10 * 1024 * 1024  # 10 MB
VALID_DOC_TYPES = {
    "certificate_of_incorporation",
    "pan_document",
    "address_proof",
    "authorized_person_id",
    "gst_certificate",
    "authorization_letter",
}

# Magic bytes signatures for allowed file types
FILE_SIGNATURES = {
    b"%PDF": "pdf",
    b"\xff\xd8\xff": "jpg",  # JPEG
    b"\x89PNG": "png",
}


def _validate_magic_bytes(content: bytes, filename: str) -> None:
    """Reject files whose content does not match any allowed file signature."""
    for sig in FILE_SIGNATURES:
        if content[:len(sig)] == sig:
            return
    raise HTTPException(
        status_code=422,
        detail=f"File content does not match an allowed type: {filename}",
    )


# Map each allowed extension to its expected magic bytes
EXTENSION_SIGNATURES = {
    ".pdf": [b"%PDF"],
    ".jpg": [b"\xff\xd8\xff"],
    ".jpeg": [b"\xff\xd8\xff"],
    ".png": [b"\x89PNG\r\n\x1a\n"],
}


def _validate_file_strict(content: bytes, filename: str) -> None:
    """Validate that file content matches the declared extension's expected signature.

    Rejects:
    - Empty files
    - Files whose content signature does not match the extension
    - Extensions not in the allowlist
    """
    if not content:
        raise HTTPException(status_code=422, detail=f"Empty file not allowed: {filename}")

    ext = os.path.splitext(filename or "")[1].lower()
    expected_sigs = EXTENSION_SIGNATURES.get(ext)
    if not expected_sigs:
        raise HTTPException(status_code=422, detail=f"Extension not allowed: {ext}")

    for sig in expected_sigs:
        if content[:len(sig)] == sig:
            return

    raise HTTPException(
        status_code=422,
        detail=f"File content does not match extension {ext}: {filename}",
    )


@router.post("/register", status_code=status.HTTP_201_CREATED)
@limiter.limit("20/hour")
async def register_org(request: Request, body: OrgRegisterRequest):
    # 1. Duplicate email check
    existing_user = await User.find_one(User.email == body.manager_email)
    if existing_user:
        raise HTTPException(status_code=400, detail="Email already registered")

    # 2. Duplicate org name check — case-insensitive at app layer (re.escape prevents regex injection)
    escaped = _re.escape(body.org_name.strip())
    existing_company = await Company.find_one(
        {"name": {"$regex": f"^{escaped}$", "$options": "i"}}
    )
    if existing_company:
        raise HTTPException(status_code=409, detail="Organization name already taken")

    # 3. Create company with pending status and all new registration fields
    company = Company(
        name=body.org_name.strip(),
        status="pending_verification",
        verification_status="pending",
        org_type=body.org_type,
        registration_number=body.registration_number,
        pan=body.pan,
        gstin=body.gstin,
        registered_address=body.registered_address,
        website=body.website,
        official_phone=body.official_phone,
        authorized_person_name=body.authorized_person_name,
        authorized_person_designation=body.authorized_person_designation,
        authorized_person_email=body.authorized_person_email,
        authorized_person_phone=body.authorized_person_phone,
    )

    # 4. Insert company — wrap in try/except to prevent orphan state
    try:
        await company.insert()
    except Exception:
        # company insert failed — no user created, no orphan risk.
        raise HTTPException(status_code=500, detail="Failed to create organization; please retry")

    # 5. Create manager account — roll back company if user insert fails
    try:
        user = User(
            email=body.manager_email,
            password_hash=hash_password(body.password),
            name=body.manager_name,
            role="company_manager",
            company_id=str(company.id),
        )
        await user.insert()
    except Exception:
        # user insert failed — deleting company to avoid orphan.
        await company.delete()
        raise HTTPException(
            status_code=500,
            detail="Failed to create manager account; registration rolled back",
        )

    return {
        "company_id": str(company.id),
        "user_id": str(user.id),
        "message": "Registration submitted; awaiting approval",
    }


@router.post("/{company_id}/documents", status_code=status.HTTP_201_CREATED)
@limiter.limit("20/hour")
async def upload_org_documents(
    request: Request,
    company_id: str,
    documents: List[UploadFile] = File(...),
    document_types: str = Form(...),
    current_user: User = Depends(get_current_user),
):
    """Upload verification documents for an organization.

    Auth: current_user must be company_manager for this company OR super_admin.
    Files are stored on disk only — never in MongoDB.
    No public URL is returned.
    """
    # Auth check
    if current_user.role != "super_admin":
        if current_user.role != "company_manager" or str(current_user.company_id) != company_id:
            raise HTTPException(
                status_code=403,
                detail="Not authorized to upload documents for this company",
            )

    # Parse and validate document_types CSV
    doc_types = [dt.strip() for dt in document_types.split(",")]
    if len(doc_types) != len(documents):
        raise HTTPException(
            status_code=422,
            detail="document_types count must match documents count",
        )
    for dt in doc_types:
        if dt not in VALID_DOC_TYPES:
            raise HTTPException(status_code=422, detail=f"Invalid document_type: {dt}")

    # Validate files (MIME type OR extension must be allowed, size limit, magic bytes)
    file_contents = []
    for f in documents:
        ext = os.path.splitext(f.filename or "")[1].lower()
        content_type = (f.content_type or "").lower()
        # Reject if EITHER content_type OR extension is not in allowlist
        if content_type not in ALLOWED_MIME_TYPES or ext not in ALLOWED_EXTENSIONS:
            raise HTTPException(status_code=422, detail=f"File type not allowed: {f.filename}. Allowed: pdf, jpg, jpeg, png")
        content = await f.read()
        if len(content) > MAX_FILE_SIZE_BYTES:
            raise HTTPException(status_code=413, detail=f"File too large: {f.filename} (max 10MB)")
        # Validate actual file content via magic bytes
        _validate_file_strict(content, f.filename or "")
        file_contents.append(content)

    # Save files and create OrgDocument records — clean up on any failure
    save_dir = os.path.join(settings.UPLOAD_FOLDER, "org_docs", company_id)
    os.makedirs(save_dir, exist_ok=True)

    created_files: list[str] = []
    created_docs: list[OrgDocument] = []
    try:
        for f, dt, content in zip(documents, doc_types, file_contents):
            # UUID-based filename to prevent path traversal via user-supplied filename
            ext = os.path.splitext(f.filename or "")[1].lower()
            safe_name = f"{uuid.uuid4().hex}{ext}"
            file_path = os.path.join(save_dir, safe_name)
            async with aiofiles.open(file_path, "wb") as out:
                await out.write(content)
            created_files.append(file_path)
            doc = OrgDocument(
                company_id=company_id,
                document_type=dt,
                file_name=os.path.basename(f.filename or safe_name),
                storage_path=file_path,
                uploaded_by=str(current_user.id),
            )
            await doc.insert()
            created_docs.append(doc)
    except Exception as exc:
        # Clean up any files written so far
        for fp in created_files:
            try:
                os.remove(fp)
            except OSError:
                pass
        # Clean up any DB records inserted so far
        for d in created_docs:
            try:
                await d.delete()
            except Exception:
                pass
        raise HTTPException(status_code=500, detail=f"Upload failed; all changes rolled back: {exc}")

    return [
        OrgDocumentOut(
            id=str(d.id),
            company_id=d.company_id,
            document_type=d.document_type,
            file_name=d.file_name,
            uploaded_at=d.uploaded_at,
            uploaded_by=d.uploaded_by,
            verification_status=d.verification_status,
        )
        for d in created_docs
    ]
