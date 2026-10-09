import os
import logging
import os
import re
import uuid
import aiofiles

logger = logging.getLogger(__name__)

from typing import List

from fastapi import (
    APIRouter,
    HTTPException,
    status,
    Request,
    Depends,
    UploadFile,
    File,
    Form,
)

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


EXTENSION_MIME_TYPES = {
    ".pdf": {"application/pdf"},
    ".jpg": {"image/jpeg"},
    ".jpeg": {"image/jpeg"},
    ".png": {"image/png"},
}

EXTENSION_SIGNATURES = {
    ".pdf": (b"%PDF-",),
    ".jpg": (b"\xff\xd8\xff",),
    ".jpeg": (b"\xff\xd8\xff",),
    ".png": (b"\x89PNG\r\n\x1a\n",),
}

MAX_FILE_SIZE_BYTES = 10 * 1024 * 1024

VALID_DOC_TYPES = {
    "certificate_of_incorporation",
    "pan_document",
    "address_proof",
    "authorized_person_id",
    "gst_certificate",
    "authorization_letter",
}


def _validate_file_strict(
    content: bytes,
    filename: str,
    content_type: str | None = None,
) -> None:
    """Validate file extension, declared MIME type and signature."""

    if not content:
        raise HTTPException(
            status_code=422,
            detail="Empty files are not allowed.",
        )

    extension = os.path.splitext(filename or "")[1].lower()

    expected_mimes = EXTENSION_MIME_TYPES.get(extension)
    expected_signatures = EXTENSION_SIGNATURES.get(extension)

    if not expected_mimes or not expected_signatures:
        raise HTTPException(
            status_code=422,
            detail="File extension is not allowed.",
        )

    declared_mime = (
        (content_type or "")
        .split(";", 1)[0]
        .strip()
        .lower()
    )

    if declared_mime not in expected_mimes:
        raise HTTPException(
            status_code=422,
            detail="Declared MIME type does not match the file extension.",
        )

    if not any(
        content.startswith(signature)
        for signature in expected_signatures
    ):
        raise HTTPException(
            status_code=422,
            detail="File content does not match the declared file type.",
        )


def _validate_magic_bytes(content: bytes, filename: str) -> None:
    """Compatibility wrapper for existing tests."""
    extension = os.path.splitext(filename or "")[1].lower()
    mime = next(iter(EXTENSION_MIME_TYPES.get(extension, {""})))
    _validate_file_strict(content, filename, mime)


@router.post("/register", status_code=status.HTTP_201_CREATED)
@limiter.limit("20/hour")
async def register_org(request: Request, body: OrgRegisterRequest):
    """Register an organization awaiting Super Admin verification."""

    existing_user = await User.find_one(
        User.email == body.manager_email
    )

    if existing_user:
        raise HTTPException(
            status_code=400,
            detail="Email already registered.",
        )

    escaped_name = re.escape(body.org_name.strip())

    existing_company = await Company.find_one(
        {
            "name": {
                "$regex": f"^{escaped_name}$",
                "$options": "i",
            }
        }
    )

    if existing_company:
        raise HTTPException(
            status_code=409,
            detail="Organization name already taken.",
        )

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

    try:
        await company.insert()
    except Exception:
        raise HTTPException(
            status_code=500,
            detail="Failed to create organization. Please retry.",
        )

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
        await company.delete()

        raise HTTPException(
            status_code=500,
            detail="Failed to create manager account. Registration rolled back.",
        )

    return {
        "company_id": str(company.id),
        "user_id": str(user.id),
        "message": "Registration submitted; awaiting approval.",
    }


@router.post(
    "/{company_id}/documents",
    status_code=status.HTTP_201_CREATED,
)
@limiter.limit("20/hour")
async def upload_org_documents(
    request: Request,
    company_id: str,
    documents: List[UploadFile] = File(...),
    document_types: str = Form(...),
    current_user: User = Depends(get_current_user),
):
    """Upload private organization verification documents."""

    if current_user.role != "super_admin":
        if (
            current_user.role != "company_manager"
            or str(current_user.company_id) != company_id
        ):
            raise HTTPException(
                status_code=403,
                detail="Not authorized to upload documents for this company.",
            )

    company = await Company.get(company_id)

    if not company:
        raise HTTPException(
            status_code=404,
            detail="Organization not found.",
        )

    doc_types = [
        item.strip()
        for item in document_types.split(",")
    ]

    if len(doc_types) != len(documents):
        raise HTTPException(
            status_code=422,
            detail="document_types count must match documents count.",
        )

    for document_type in doc_types:
        if document_type not in VALID_DOC_TYPES:
            raise HTTPException(
                status_code=422,
                detail=f"Invalid document type: {document_type}",
            )

    file_contents = []

    for upload in documents:
        content = await upload.read(MAX_FILE_SIZE_BYTES + 1)

        if len(content) > MAX_FILE_SIZE_BYTES:
            raise HTTPException(
                status_code=413,
                detail="File exceeds the 10 MB limit.",
            )

        _validate_file_strict(
            content,
            upload.filename or "",
            upload.content_type or "",
        )

        file_contents.append(content)

    save_dir = os.path.join(
        settings.UPLOAD_FOLDER,
        "org_docs",
        company_id,
    )

    os.makedirs(save_dir, exist_ok=True)

    created_files = []
    created_docs = []

    try:
        for upload, document_type, content in zip(
            documents,
            doc_types,
            file_contents,
        ):
            extension = os.path.splitext(
                upload.filename or ""
            )[1].lower()

            safe_filename = f"{uuid.uuid4().hex}{extension}"
            file_path = os.path.join(save_dir, safe_filename)

            async with aiofiles.open(file_path, "xb") as output:
                await output.write(content)

            created_files.append(file_path)

            document = OrgDocument(
                company_id=company_id,
                document_type=document_type,
                file_name=os.path.basename(
                    upload.filename or safe_filename
                ),
                storage_path=file_path,
                uploaded_by=str(current_user.id),
            )

            await document.insert()
            created_docs.append(document)

    except Exception:
        for file_path in created_files:
            try:
                os.remove(file_path)
            except OSError as e:
                logger.warning("Cleanup: could not remove file during upload rollback (%s)", type(e).__name__)

        for document in created_docs:
            try:
                await document.delete()
            except Exception as e:
                logger.warning("Cleanup: could not delete document record during upload rollback (%s)", type(e).__name__)

        raise HTTPException(
            status_code=500,
            detail="Upload failed; partial files and records were cleaned up.",
        )

    return [
        OrgDocumentOut(
            id=str(document.id),
            company_id=document.company_id,
            document_type=document.document_type,
            file_name=document.file_name,
            uploaded_at=document.uploaded_at,
            uploaded_by=document.uploaded_by,
            verification_status=document.verification_status,
        )
        for document in created_docs
    ]