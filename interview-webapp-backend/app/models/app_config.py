from beanie import Document
from typing import Optional


class AppConfig(Document):
    app_name: str = "CrudBeat Proctor"
    logo_path: Optional[str] = None
    candidate_about_text: Optional[str] = None
    recruiter_about_text: Optional[str] = None
    candidate_about_image_path: Optional[str] = None
    recruiter_about_image_path: Optional[str] = None

    class Settings:
        name = "app_config"
