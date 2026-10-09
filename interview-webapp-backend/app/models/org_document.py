from beanie import Document
from typing import Literal, Optional
from datetime import datetime, timezone


class OrgDocument(Document):
    company_id: str
    document_type: Literal[
        "certificate_of_incorporation",
        "pan_document",
        "address_proof",
        "authorized_person_id",
        "gst_certificate",
        "authorization_letter",
    ]
    file_name: str
    storage_path: str
    uploaded_at: Optional[datetime] = None
    uploaded_by: str
    verification_status: str = "pending"

    def __init__(self, **data):
        if "uploaded_at" not in data or data["uploaded_at"] is None:
            data["uploaded_at"] = datetime.now(timezone.utc)
        super().__init__(**data)

    class Settings:
        name = "org_documents"
