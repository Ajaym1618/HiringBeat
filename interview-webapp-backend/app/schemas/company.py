from pydantic import BaseModel
from typing import Literal


class CreateCompanyRequest(BaseModel):
    name: str
    status: Literal["active", "inactive"] = "active"


class PatchCompanyRequest(BaseModel):
    name: str = None
    status: Literal["active", "inactive"] = None


class CompanyOut(BaseModel):
    id: str
    name: str
    status: str
