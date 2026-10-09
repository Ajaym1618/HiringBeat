"""
Tests for org onboarding, verification, subscription enforcement, user-role
management, and candidate history.

All tests use AsyncMock/patch — no real MongoDB connection required.
"""
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from datetime import datetime, timedelta, timezone
from pydantic import ValidationError

import os
os.environ.setdefault("SECRET_KEY", "test-secret-key")
os.environ.setdefault("MONGO_URI", "mongodb://localhost:27017")
os.environ.setdefault("DEVICE_BRIDGE_KEY", "test-bridge-key")

from app.models.user import User as UserModel
from app.models.company import Company as CompanyModel
from app.models.interview import Interview as InterviewModel


# ---------------------------------------------------------------------------
# Helpers / fixtures
# ---------------------------------------------------------------------------

def _utc_now():
    return datetime.now(timezone.utc)


class FakeCompany:
    def __init__(
        self,
        company_id="comp1",
        name="Acme Corp",
        status="active",
        verification_status="approved",
        plan="free",
        interview_limit=5,
        seat_limit=3,
        subscription_expires_at=None,
        rejection_reason=None,
        verified_at=None,
        verified_by=None,
        # New fields (GAP 5)
        subscription_plan_id=None,
        subscription_status="inactive",
        subscription_started_at=None,
        # New org identity fields (GAP 1)
        org_type=None,
        registration_number=None,
        pan=None,
        gstin=None,
        registered_address=None,
        website=None,
        official_phone=None,
        authorized_person_name=None,
        authorized_person_designation=None,
        authorized_person_email=None,
        authorized_person_phone=None,
    ):
        self.id = company_id
        self.name = name
        self.status = status
        self.verification_status = verification_status
        self.plan = plan
        self.interview_limit = interview_limit
        self.seat_limit = seat_limit
        self.subscription_expires_at = subscription_expires_at
        self.rejection_reason = rejection_reason
        self.verified_at = verified_at
        self.verified_by = verified_by
        self.created_at = _utc_now()
        self.subscription_plan_id = subscription_plan_id
        self.subscription_status = subscription_status
        self.subscription_started_at = subscription_started_at
        self.org_type = org_type
        self.registration_number = registration_number
        self.pan = pan
        self.gstin = gstin
        self.registered_address = registered_address
        self.website = website
        self.official_phone = official_phone
        self.authorized_person_name = authorized_person_name
        self.authorized_person_designation = authorized_person_designation
        self.authorized_person_email = authorized_person_email
        self.authorized_person_phone = authorized_person_phone

    async def insert(self):
        return self

    async def delete(self):
        pass

    async def set(self, data: dict):
        for k, v in data.items():
            setattr(self, k, v)

    async def sync(self):
        pass


class FakeUser:
    def __init__(
        self,
        user_id="user1",
        email="mgr@acme.com",
        name="Manager",
        role="company_manager",
        company_id="comp1",
    ):
        self.id = user_id
        self.email = email
        self.name = name
        self.role = role
        self.company_id = company_id

    async def insert(self):
        return self

    async def set(self, data: dict):
        for k, v in data.items():
            setattr(self, k, v)


class FakeInterview:
    def __init__(
        self,
        interview_id="iv1",
        title="Test Interview",
        description="desc",
        interview_code="ABCD1234",
        status="scheduled",
        company_id="comp1",
        candidate_email="candidate@test.com",
        candidate_id=None,
        recruiter_id="rec1",
        face_reference_path=None,
        started_at=None,
        ended_at=None,
        scheduled_at=None,
        created_at=None,
    ):
        self.id = interview_id
        self.title = title
        self.description = description
        self.interview_code = interview_code
        self.status = status
        self.company_id = company_id
        self.candidate_email = candidate_email
        self.candidate_id = candidate_id
        self.recruiter_id = recruiter_id
        self.face_reference_path = face_reference_path
        self.started_at = started_at
        self.ended_at = ended_at
        self.scheduled_at = scheduled_at
        self.created_at = created_at or _utc_now()


def _make_query_mock(results=None, count=0):
    """Return a mock that chains .find().count() or .find().to_list()."""
    qm = MagicMock()
    qm.count = AsyncMock(return_value=count)
    qm.to_list = AsyncMock(return_value=results or [])
    qm.sort = MagicMock(return_value=qm)
    return qm


# ---------------------------------------------------------------------------
# POST /api/org/register — success
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_register_success():
    from app.routes.org import register_org
    from app.schemas.org import OrgRegisterRequest

    body = OrgRegisterRequest(
        org_name="Acme Corp",
        manager_name="Alice",
        manager_email="alice@acme.com",
        password="Secret123",
        org_type="Private Limited",
        registered_address="123 Main St, Mumbai",
        official_phone="+919876543210",
        authorized_person_name="Alice Smith",
        authorized_person_designation="Director",
        authorized_person_email="alice.auth@acme.com",
        authorized_person_phone="+919876543211",
    )

    fake_company = FakeCompany(company_id="comp_new", status="pending_verification")
    fake_user = FakeUser(user_id="user_new")

    # Build a mock class that has find_one as AsyncMock AND acts as a constructor
    mock_user_cls = MagicMock()
    mock_user_cls.find_one = AsyncMock(return_value=None)
    mock_user_cls.return_value = fake_user

    mock_company_cls = MagicMock()
    mock_company_cls.find_one = AsyncMock(return_value=None)
    mock_company_cls.return_value = fake_company

    fake_company.insert = AsyncMock(return_value=fake_company)
    fake_user.insert = AsyncMock(return_value=fake_user)

    from fastapi import Request
    mock_request = MagicMock(spec=Request)
    mock_request.app = MagicMock()
    mock_request.app.state = MagicMock()

    with patch("app.routes.org.User", mock_user_cls), \
         patch("app.routes.org.Company", mock_company_cls):

        result = await register_org.__wrapped__(mock_request, body)

    assert result["company_id"] == "comp_new"
    assert result["user_id"] == "user_new"
    assert "awaiting approval" in result["message"]


@pytest.mark.asyncio
async def test_register_creates_pending_status():
    """Registered org must have status=pending_verification and verification_status=pending."""
    from app.routes.org import register_org
    from app.schemas.org import OrgRegisterRequest
    from fastapi import Request

    body = OrgRegisterRequest(
        org_name="Pending Corp",
        manager_name="Bob",
        manager_email="bob@pending.com",
        password="Secret123",
        org_type="Private Limited",
        registered_address="456 Elm St, Delhi",
        official_phone="+919876543212",
        authorized_person_name="Bob Brown",
        authorized_person_designation="CEO",
        authorized_person_email="bob.auth@pending.com",
        authorized_person_phone="+919876543213",
    )

    created_companies = []

    class CapturingCompany:
        def __init__(self, **kwargs):
            self.id = "comp_pending"
            for k, v in kwargs.items():
                setattr(self, k, v)
            created_companies.append(self)

        async def insert(self):
            return self

        async def delete(self):
            pass

    fake_user = FakeUser(user_id="user_p")
    fake_user.insert = AsyncMock(return_value=fake_user)

    mock_request = MagicMock(spec=Request)
    mock_request.app = MagicMock()
    mock_request.app.state = MagicMock()

    mock_user_cls = MagicMock()
    mock_user_cls.find_one = AsyncMock(return_value=None)
    mock_user_cls.return_value = fake_user

    mock_company_cls = MagicMock()
    mock_company_cls.find_one = AsyncMock(return_value=None)
    mock_company_cls.side_effect = CapturingCompany

    with patch("app.routes.org.User", mock_user_cls), \
         patch("app.routes.org.Company", mock_company_cls):

        await register_org.__wrapped__(mock_request, body)

    assert len(created_companies) == 1
    assert created_companies[0].status == "pending_verification"
    assert created_companies[0].verification_status == "pending"


@pytest.mark.asyncio
async def test_register_creates_company_manager_account():
    """The manager account must be created with role=company_manager."""
    from app.routes.org import register_org
    from app.schemas.org import OrgRegisterRequest
    from fastapi import Request

    body = OrgRegisterRequest(
        org_name="Manager Corp",
        manager_name="Carol",
        manager_email="carol@mgrcorp.com",
        password="Secret123",
        org_type="LLP",
        registered_address="789 Oak Ave, Bangalore",
        official_phone="+919876543214",
        authorized_person_name="Carol White",
        authorized_person_designation="Managing Partner",
        authorized_person_email="carol.auth@mgrcorp.com",
        authorized_person_phone="+919876543215",
    )

    fake_company = FakeCompany(company_id="comp_mgr", status="pending_verification")
    fake_company.insert = AsyncMock(return_value=fake_company)
    fake_company.delete = AsyncMock()

    created_users = []

    class CapturingUser:
        def __init__(self, **kwargs):
            self.id = "user_mgr"
            for k, v in kwargs.items():
                setattr(self, k, v)
            created_users.append(self)

        async def insert(self):
            return self

    mock_request = MagicMock(spec=Request)
    mock_request.app = MagicMock()
    mock_request.app.state = MagicMock()

    mock_user_cls = MagicMock()
    mock_user_cls.find_one = AsyncMock(return_value=None)
    mock_user_cls.side_effect = CapturingUser

    mock_company_cls = MagicMock()
    mock_company_cls.find_one = AsyncMock(return_value=None)
    mock_company_cls.return_value = fake_company

    with patch("app.routes.org.User", mock_user_cls), \
         patch("app.routes.org.Company", mock_company_cls):

        await register_org.__wrapped__(mock_request, body)

    assert len(created_users) == 1
    assert created_users[0].role == "company_manager"


# ---------------------------------------------------------------------------
# POST /api/org/register — duplicate checks
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_register_duplicate_email_returns_400():
    from app.routes.org import register_org
    from app.schemas.org import OrgRegisterRequest
    from fastapi import HTTPException, Request

    body = OrgRegisterRequest(
        org_name="New Corp",
        manager_name="Dave",
        manager_email="dave@existing.com",
        password="Secret123",
        org_type="Private Limited",
        registered_address="101 Pine Rd, Chennai",
        official_phone="+919876543216",
        authorized_person_name="Dave Johnson",
        authorized_person_designation="Director",
        authorized_person_email="dave.auth@existing.com",
        authorized_person_phone="+919876543217",
    )
    existing = FakeUser(email="dave@existing.com")

    mock_request = MagicMock(spec=Request)
    mock_request.app = MagicMock()
    mock_request.app.state = MagicMock()

    with patch.object(UserModel, "find_one", new_callable=AsyncMock, return_value=existing, create=True), \
         patch.object(UserModel, "email", new=MagicMock(), create=True):
        with pytest.raises(HTTPException) as exc_info:
            await register_org.__wrapped__(mock_request, body)

    assert exc_info.value.status_code == 400


@pytest.mark.asyncio
async def test_register_duplicate_org_name_returns_409():
    from app.routes.org import register_org
    from app.schemas.org import OrgRegisterRequest
    from fastapi import HTTPException, Request

    body = OrgRegisterRequest(
        org_name="Existing Corp",
        manager_name="Eve",
        manager_email="eve@newcorp.com",
        password="Secret123",
        org_type="Public Limited",
        registered_address="202 Maple St, Hyderabad",
        official_phone="+919876543218",
        authorized_person_name="Eve Davis",
        authorized_person_designation="CFO",
        authorized_person_email="eve.auth@newcorp.com",
        authorized_person_phone="+919876543219",
    )
    existing_company = FakeCompany(name="Existing Corp")

    mock_request = MagicMock(spec=Request)
    mock_request.app = MagicMock()
    mock_request.app.state = MagicMock()

    with patch.object(UserModel, "find_one", new_callable=AsyncMock, return_value=None, create=True), \
         patch.object(UserModel, "email", new=MagicMock(), create=True), \
         patch.object(CompanyModel, "find_one", new_callable=AsyncMock, return_value=existing_company, create=True):
        with pytest.raises(HTTPException) as exc_info:
            await register_org.__wrapped__(mock_request, body)

    assert exc_info.value.status_code == 409


@pytest.mark.asyncio
async def test_register_missing_required_field_returns_422():
    """Missing required field must raise Pydantic ValidationError (maps to HTTP 422)."""
    from app.schemas.org import OrgRegisterRequest

    with pytest.raises(ValidationError):
        OrgRegisterRequest(
            # org_name missing
            manager_name="Frank",
            manager_email="frank@corp.com",
            password="Secret123",
            org_type="Private Limited",
            registered_address="505 Ash St, Ahmedabad",
            official_phone="+919876543224",
            authorized_person_name="Frank Lee",
            authorized_person_designation="Director",
            authorized_person_email="frank.auth@corp.com",
            authorized_person_phone="+919876543225",
        )


# ---------------------------------------------------------------------------
# POST /api/org/register — atomic rollback (FIX 5)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_register_company_insert_failure_returns_500():
    """FIX5a: if company.insert() raises, no user is created and HTTP 500 is returned."""
    from app.routes.org import register_org
    from app.schemas.org import OrgRegisterRequest
    from fastapi import HTTPException, Request

    body = OrgRegisterRequest(
        org_name="FailCorp",
        manager_name="Greta",
        manager_email="greta@fail.com",
        password="Secret123",
        org_type="Partnership",
        registered_address="303 Cedar Ln, Pune",
        official_phone="+919876543220",
        authorized_person_name="Greta Miller",
        authorized_person_designation="Partner",
        authorized_person_email="greta.auth@fail.com",
        authorized_person_phone="+919876543221",
    )

    fake_company = MagicMock()
    fake_company.id = "comp_fail"
    fake_company.insert = AsyncMock(side_effect=Exception("DB error"))
    fake_company.delete = AsyncMock()

    mock_request = MagicMock(spec=Request)
    mock_request.app = MagicMock()
    mock_request.app.state = MagicMock()

    mock_company_cls = MagicMock()
    mock_company_cls.find_one = AsyncMock(return_value=None)
    mock_company_cls.return_value = fake_company

    with patch.object(UserModel, "find_one", new_callable=AsyncMock, return_value=None, create=True), \
         patch.object(UserModel, "email", new=MagicMock(), create=True), \
         patch("app.routes.org.Company", mock_company_cls):
        with pytest.raises(HTTPException) as exc_info:
            await register_org.__wrapped__(mock_request, body)

    assert exc_info.value.status_code == 500
    # No user should have been attempted
    fake_company.delete.assert_not_called()


@pytest.mark.asyncio
async def test_register_user_insert_failure_rolls_back_company():
    """FIX5b: if user.insert() raises after company inserted, company is deleted (rollback)."""
    from app.routes.org import register_org
    from app.schemas.org import OrgRegisterRequest
    from fastapi import HTTPException, Request

    body = OrgRegisterRequest(
        org_name="RollbackCorp",
        manager_name="Hank",
        manager_email="hank@rollback.com",
        password="Secret123",
        org_type="Private Limited",
        registered_address="404 Birch Blvd, Kolkata",
        official_phone="+919876543222",
        authorized_person_name="Hank Wilson",
        authorized_person_designation="Director",
        authorized_person_email="hank.auth@rollback.com",
        authorized_person_phone="+919876543223",
    )

    fake_company = MagicMock()
    fake_company.id = "comp_rollback"
    fake_company.insert = AsyncMock(return_value=None)
    fake_company.delete = AsyncMock()

    fake_user = MagicMock()
    fake_user.id = "user_rollback"
    fake_user.insert = AsyncMock(side_effect=Exception("DB error"))

    mock_request = MagicMock(spec=Request)
    mock_request.app = MagicMock()
    mock_request.app.state = MagicMock()

    mock_user_cls = MagicMock()
    mock_user_cls.find_one = AsyncMock(return_value=None)
    mock_user_cls.return_value = fake_user

    mock_company_cls = MagicMock()
    mock_company_cls.find_one = AsyncMock(return_value=None)
    mock_company_cls.return_value = fake_company

    with patch("app.routes.org.User", mock_user_cls), \
         patch("app.routes.org.Company", mock_company_cls):
        with pytest.raises(HTTPException) as exc_info:
            await register_org.__wrapped__(mock_request, body)

    assert exc_info.value.status_code == 500
    # Company must have been deleted (rolled back)
    fake_company.delete.assert_called_once()


# ---------------------------------------------------------------------------
# GET /api/admin/orgs/pending + approve + reject
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_super_admin_can_list_pending_orgs():
    from app.routes.admin import list_pending_orgs

    admin_user = FakeUser(user_id="admin1", role="super_admin", company_id=None)
    pending = FakeCompany(company_id="comp_p", status="pending_verification", verification_status="pending")
    manager = FakeUser(user_id="mgr1", email="mgr@p.com", name="Mgr", role="company_manager", company_id="comp_p")

    qm = _make_query_mock(results=[pending])

    with patch.object(CompanyModel, "find", return_value=qm, create=True), \
         patch.object(CompanyModel, "status", new=MagicMock(), create=True), \
         patch.object(UserModel, "find_one", new_callable=AsyncMock, return_value=manager, create=True):
        result = await list_pending_orgs(current_user=admin_user)

    assert len(result) == 1
    assert result[0]["status"] == "pending_verification"
    assert result[0]["manager"]["email"] == "mgr@p.com"


@pytest.mark.asyncio
async def test_super_admin_can_verify_org():
    from app.routes.admin import approve_org
    from app.models.org_document import OrgDocument as OrgDocModel

    admin_user = FakeUser(user_id="admin1", role="super_admin", company_id=None)
    pending = FakeCompany(company_id="comp_v", status="pending_verification", verification_status="pending")

    # Create fake docs covering all required types
    required_types = ["certificate_of_incorporation", "pan_document", "address_proof", "authorized_person_id"]
    fake_docs = [MagicMock(document_type=dt) for dt in required_types]
    doc_qm = _make_query_mock(results=fake_docs)

    with patch("app.routes.admin.get_company_or_404", new_callable=AsyncMock, return_value=pending), \
         patch.object(OrgDocModel, "find", return_value=doc_qm, create=True):
        result = await approve_org(company_id="comp_v", current_user=admin_user)

    assert result["status"] == "active"
    assert result["verification_status"] == "approved"


@pytest.mark.asyncio
async def test_super_admin_can_reject_org_with_reason():
    from app.routes.admin import reject_org
    from app.schemas.org import RejectOrgRequest

    admin_user = FakeUser(user_id="admin1", role="super_admin", company_id=None)
    pending = FakeCompany(company_id="comp_r", status="pending_verification", verification_status="pending")
    body = RejectOrgRequest(reason="Incomplete documentation")

    with patch("app.routes.admin.get_company_or_404", new_callable=AsyncMock, return_value=pending):
        result = await reject_org(company_id="comp_r", body=body, current_user=admin_user)

    assert result["status"] == "rejected"
    assert result["verification_status"] == "rejected"
    assert result["rejection_reason"] == "Incomplete documentation"


@pytest.mark.asyncio
async def test_non_super_admin_cannot_verify_returns_403():
    from app.routes.admin import approve_org
    from fastapi import HTTPException

    mgr_user = FakeUser(user_id="mgr1", role="company_manager")

    with pytest.raises(HTTPException) as exc_info:
        await approve_org(company_id="comp_x", current_user=mgr_user)

    assert exc_info.value.status_code == 403


# ---------------------------------------------------------------------------
# Company status gate — pending/rejected orgs blocked from team/interview actions
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_pending_org_cannot_create_recruiter_returns_403():
    """A pending org must not be allowed to add team members."""
    from app.routes.company import add_team_member
    from app.schemas.admin import CreateRecruiterRequest
    from fastapi import HTTPException

    mgr_user = FakeUser(role="company_manager", company_id="comp_pending")
    pending_company = FakeCompany(company_id="comp_pending", status="pending_verification")

    body = CreateRecruiterRequest(
        email="rec@pend.com",
        password="Secret123",
        name="Recruiter",
        role="recruiter",
        company_id="comp_pending",
    )

    with patch("app.routes.company.Company.get", new_callable=AsyncMock, return_value=pending_company):
        with pytest.raises(HTTPException) as exc_info:
            await add_team_member(body=body, current_user=mgr_user)

    assert exc_info.value.status_code == 403


@pytest.mark.asyncio
async def test_rejected_org_cannot_create_recruiter_returns_403():
    """A rejected org must not be allowed to add team members."""
    from app.routes.company import add_team_member
    from app.schemas.admin import CreateRecruiterRequest
    from fastapi import HTTPException

    mgr_user = FakeUser(role="company_manager", company_id="comp_rejected")
    rejected_company = FakeCompany(company_id="comp_rejected", status="rejected")

    body = CreateRecruiterRequest(
        email="rec@rej.com",
        password="Secret123",
        name="Recruiter",
        role="recruiter",
        company_id="comp_rejected",
    )

    with patch("app.routes.company.Company.get", new_callable=AsyncMock, return_value=rejected_company):
        with pytest.raises(HTTPException) as exc_info:
            await add_team_member(body=body, current_user=mgr_user)

    assert exc_info.value.status_code == 403


@pytest.mark.asyncio
async def test_pending_org_cannot_create_interview_returns_403():
    """A pending org must not be allowed to create interviews — check_org_approved raises 403."""
    from app.routes.interviews import create_interview
    from app.schemas.interview import CreateInterviewRequest
    from fastapi import HTTPException

    recruiter = FakeUser(user_id="rec1", role="recruiter", company_id="comp_pend")
    # pending_verification status — check_org_approved will raise 403
    pending_company = FakeCompany(
        company_id="comp_pend",
        status="pending_verification",
        verification_status="pending",
        interview_limit=100,
    )

    body = CreateInterviewRequest(title="Interview A")

    with patch("app.routes.interviews.Company.get", new_callable=AsyncMock, return_value=pending_company):
        with pytest.raises(HTTPException) as exc_info:
            await create_interview(body=body, current_user=recruiter)

    assert exc_info.value.status_code == 403
    assert "pending" in exc_info.value.detail.lower()


@pytest.mark.asyncio
async def test_rejected_org_login_blocked_returns_403():
    """Login must be blocked for users belonging to a rejected company."""
    from app.routes.auth import login
    from app.schemas.auth import LoginRequest
    from fastapi import HTTPException, Request

    rejected_company = FakeCompany(status="rejected")
    user = FakeUser(role="company_manager", company_id="comp_rej")
    user.password_hash = __import__("bcrypt").hashpw(b"Secret123", __import__("bcrypt").gensalt()).decode()

    body = LoginRequest(email="mgr@rej.com", password="Secret123")

    mock_request = MagicMock(spec=Request)
    mock_request.app = MagicMock()
    mock_request.app.state = MagicMock()

    with patch.object(UserModel, "find_one", new_callable=AsyncMock, return_value=user, create=True), \
         patch.object(UserModel, "email", new=MagicMock(), create=True), \
         patch("app.routes.auth.Company.get", new_callable=AsyncMock, return_value=rejected_company), \
         patch("app.routes.auth.verify_password", return_value=True):
        with pytest.raises(HTTPException) as exc_info:
            await login.__wrapped__(mock_request, body)

    assert exc_info.value.status_code == 403


@pytest.mark.asyncio
async def test_verified_org_login_allowed():
    """Login must succeed for users of an active/approved company."""
    from app.routes.auth import login
    from app.schemas.auth import LoginRequest
    from fastapi import Request

    active_company = FakeCompany(status="active", verification_status="approved")
    user = FakeUser(role="company_manager", company_id="comp_active")
    user.password_hash = __import__("bcrypt").hashpw(b"Secret123", __import__("bcrypt").gensalt()).decode()

    body = LoginRequest(email="mgr@active.com", password="Secret123")

    mock_request = MagicMock(spec=Request)
    mock_request.app = MagicMock()
    mock_request.app.state = MagicMock()

    with patch.object(UserModel, "find_one", new_callable=AsyncMock, return_value=user, create=True), \
         patch.object(UserModel, "email", new=MagicMock(), create=True), \
         patch("app.routes.auth.Company.get", new_callable=AsyncMock, return_value=active_company), \
         patch("app.routes.auth.verify_password", return_value=True), \
         patch("app.routes.auth.create_access_token", return_value="fake.jwt.token"):
        from app.schemas.auth import TokenResponse
        result = await login.__wrapped__(mock_request, body)

    assert result.access_token == "fake.jwt.token"


# ---------------------------------------------------------------------------
# Seat limit enforcement
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_recruiter_limit_enforced_returns_403():
    """Adding a team member when the recruiter limit is reached must return HTTP 409."""
    from app.routes.company import add_team_member
    from app.schemas.admin import CreateRecruiterRequest
    from app.models.subscription_plan import SubscriptionPlan as SPModel
    from fastapi import HTTPException

    mgr_user = FakeUser(role="company_manager", company_id="comp1")
    # Company with subscription plan set and approved
    company = FakeCompany(company_id="comp1", verification_status="approved")
    company.subscription_plan_id = "plan1"
    company.subscription_status = "active"
    company.subscription_expires_at = None

    fake_plan = MagicMock()
    fake_plan.max_recruiters = 2
    fake_plan.max_admins = 3

    body = CreateRecruiterRequest(
        email="extra@corp.com",
        password="Secret123",
        name="Extra",
        role="recruiter",
        company_id="comp1",
    )

    qm = _make_query_mock(count=2)

    with patch("app.routes.company.Company.get", new_callable=AsyncMock, return_value=company), \
         patch.object(UserModel, "find", return_value=qm, create=True), \
         patch.object(SPModel, "get", new_callable=AsyncMock, return_value=fake_plan):
        with pytest.raises(HTTPException) as exc_info:
            await add_team_member(body=body, current_user=mgr_user)

    assert exc_info.value.status_code == 409
    assert "Recruiter limit" in exc_info.value.detail


@pytest.mark.asyncio
async def test_admin_limit_enforced_returns_403():
    """Admin limit enforced — returns HTTP 409 when at max_admins."""
    from app.routes.company import add_team_member
    from app.schemas.admin import CreateRecruiterRequest
    from app.models.subscription_plan import SubscriptionPlan as SPModel
    from fastapi import HTTPException

    mgr_user = FakeUser(role="company_manager", company_id="comp1")
    company = FakeCompany(company_id="comp1", verification_status="approved")
    company.subscription_plan_id = "plan1"
    company.subscription_status = "active"
    company.subscription_expires_at = None

    fake_plan = MagicMock()
    fake_plan.max_admins = 1
    fake_plan.max_recruiters = 5

    body = CreateRecruiterRequest(
        email="mgr2@corp.com",
        password="Secret123",
        name="Manager 2",
        role="company_manager",
        company_id="comp1",
    )

    qm = _make_query_mock(count=1)

    with patch("app.routes.company.Company.get", new_callable=AsyncMock, return_value=company), \
         patch.object(UserModel, "find", return_value=qm, create=True), \
         patch.object(SPModel, "get", new_callable=AsyncMock, return_value=fake_plan):
        with pytest.raises(HTTPException) as exc_info:
            await add_team_member(body=body, current_user=mgr_user)

    assert exc_info.value.status_code == 409
    assert "Admin limit" in exc_info.value.detail


# ---------------------------------------------------------------------------
# Interview limit enforcement
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_interview_limit_enforced_returns_403():
    """Creating an interview when the limit is reached must return HTTP 409."""
    from app.routes.interviews import create_interview
    from app.schemas.interview import CreateInterviewRequest
    from app.models.subscription_plan import SubscriptionPlan as SPModel
    from fastapi import HTTPException

    recruiter = FakeUser(user_id="rec1", role="recruiter", company_id="comp1")
    company = FakeCompany(company_id="comp1", verification_status="approved")
    company.subscription_plan_id = "plan1"
    company.subscription_status = "active"
    company.subscription_expires_at = None

    fake_plan = MagicMock()
    fake_plan.max_interviews = 5

    body = CreateInterviewRequest(title="Interview Overflow")

    qm = _make_query_mock(count=5)

    with patch("app.routes.interviews.Company.get", new_callable=AsyncMock, return_value=company), \
         patch.object(InterviewModel, "find", return_value=qm, create=True), \
         patch.object(SPModel, "get", new_callable=AsyncMock, return_value=fake_plan):
        with pytest.raises(HTTPException) as exc_info:
            await create_interview(body=body, current_user=recruiter)

    assert exc_info.value.status_code == 409
    assert "Interview limit" in exc_info.value.detail


# ---------------------------------------------------------------------------
# Candidate interview history
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_candidate_can_see_own_interviews():
    from app.routes.candidates import candidate_history

    candidate = FakeUser(user_id="cand1", role="candidate", email="c@test.com", company_id=None)
    interviews = [
        FakeInterview(interview_id="iv1", candidate_email="c@test.com"),
        FakeInterview(interview_id="iv2", candidate_email="c@test.com"),
    ]

    qm = _make_query_mock(results=interviews)

    with patch.object(InterviewModel, "find", return_value=qm, create=True), \
         patch.object(InterviewModel, "candidate_email", new=MagicMock(), create=True), \
         patch.object(InterviewModel, "created_at", new=MagicMock(), create=True):
        result = await candidate_history(current_user=candidate)

    assert len(result) == 2
    # recruiter_id and face_reference_path must NOT be in the response
    for item in result:
        assert "recruiter_id" not in item
        assert "face_reference_path" not in item


@pytest.mark.asyncio
async def test_candidate_cannot_see_other_candidate_interviews():
    """Different email → empty list, never another candidate's interviews."""
    from app.routes.candidates import candidate_history

    candidate = FakeUser(user_id="cand2", role="candidate", email="other@test.com", company_id=None)

    qm = _make_query_mock(results=[])

    with patch.object(InterviewModel, "find", return_value=qm, create=True), \
         patch.object(InterviewModel, "candidate_email", new=MagicMock(), create=True), \
         patch.object(InterviewModel, "created_at", new=MagicMock(), create=True):
        result = await candidate_history(current_user=candidate)

    assert result == []


@pytest.mark.asyncio
async def test_candidate_history_empty():
    """No interviews for this candidate returns empty list, not 404."""
    from app.routes.candidates import candidate_history

    candidate = FakeUser(user_id="cand3", role="candidate", email="new@test.com", company_id=None)

    qm = _make_query_mock(results=[])

    with patch.object(InterviewModel, "find", return_value=qm, create=True), \
         patch.object(InterviewModel, "candidate_email", new=MagicMock(), create=True), \
         patch.object(InterviewModel, "created_at", new=MagicMock(), create=True):
        result = await candidate_history(current_user=candidate)

    assert result == []


@pytest.mark.asyncio
async def test_candidate_history_forbidden_recruiter():
    """Non-candidate role must get HTTP 403."""
    from app.routes.candidates import candidate_history
    from fastapi import HTTPException

    recruiter = FakeUser(user_id="rec1", role="recruiter", email="r@test.com")

    with pytest.raises(HTTPException) as exc_info:
        await candidate_history(current_user=recruiter)

    assert exc_info.value.status_code == 403


# ---------------------------------------------------------------------------
# Company A cannot access company B subscription endpoint
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_company_a_cannot_access_company_b_subscription():
    """Only super_admin can call the subscription endpoint; company_manager gets 403."""
    from app.routes.admin import patch_subscription
    from app.schemas.org import PatchSubscriptionRequest
    from fastapi import HTTPException

    mgr_user = FakeUser(user_id="mgr1", role="company_manager", company_id="compA")
    body = PatchSubscriptionRequest(interview_limit=10)

    with pytest.raises(HTTPException) as exc_info:
        await patch_subscription(company_id="compB", body=body, current_user=mgr_user)

    assert exc_info.value.status_code == 403


# ---------------------------------------------------------------------------
# effective_interview_limit / effective_seat_limit — pure function tests
# ---------------------------------------------------------------------------

def test_effective_limit_not_expired():
    from app.core.subscription import effective_interview_limit
    future = _utc_now() + timedelta(days=30)
    assert effective_interview_limit(10, future) == 10


def test_effective_limit_expired():
    from app.core.subscription import effective_interview_limit, FREE_INTERVIEW_LIMIT
    past = _utc_now() - timedelta(days=1)
    assert effective_interview_limit(10, past) == FREE_INTERVIEW_LIMIT


def test_effective_limit_no_expiry():
    from app.core.subscription import effective_seat_limit
    assert effective_seat_limit(10, None) == 10


# ---------------------------------------------------------------------------
# GET /api/company/team with include_usage
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_get_team_seat_usage():
    """?include_usage=true must return seat_usage in the response."""
    from app.routes.company import get_team

    mgr_user = FakeUser(role="company_manager", company_id="comp1")
    members = [
        FakeUser(user_id="r1", role="recruiter", company_id="comp1"),
        FakeUser(user_id="r2", role="recruiter", company_id="comp1"),
    ]
    company = FakeCompany(company_id="comp1", seat_limit=5)

    qm = _make_query_mock(results=members)

    with patch.object(UserModel, "find", return_value=qm, create=True), \
         patch("app.routes.company.Company.get", new_callable=AsyncMock, return_value=company):
        result = await get_team(current_user=mgr_user, include_usage=True)

    assert "members" in result
    assert "seat_usage" in result
    assert result["seat_usage"]["used"] == 2


@pytest.mark.asyncio
async def test_get_team_without_usage_returns_list():
    """Default (include_usage=False) must return bare list for backward compatibility."""
    from app.routes.company import get_team

    mgr_user = FakeUser(role="company_manager", company_id="comp1")
    members = [FakeUser(user_id="r1", role="recruiter", company_id="comp1")]

    qm = _make_query_mock(results=members)

    with patch.object(UserModel, "find", return_value=qm, create=True):
        result = await get_team(current_user=mgr_user, include_usage=False)

    assert isinstance(result, list)


# ---------------------------------------------------------------------------
# PATCH /api/company/team/{user_id} — role update
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_update_role_success():
    from app.routes.company import update_team_member_role
    from app.schemas.org import UpdateRoleRequest

    mgr_user = FakeUser(user_id="mgr1", role="company_manager", company_id="comp1")
    target = FakeUser(user_id="rec1", role="recruiter", company_id="comp1")
    body = UpdateRoleRequest(role="company_manager")

    with patch("app.routes.company.get_user_or_404", new_callable=AsyncMock, return_value=target):
        result = await update_team_member_role(user_id="rec1", body=body, current_user=mgr_user)

    assert result["role"] == "company_manager"


@pytest.mark.asyncio
async def test_update_role_self_demotion():
    """User cannot change their own role."""
    from app.routes.company import update_team_member_role
    from app.schemas.org import UpdateRoleRequest
    from fastapi import HTTPException

    mgr_user = FakeUser(user_id="mgr1", role="company_manager", company_id="comp1")
    body = UpdateRoleRequest(role="recruiter")

    with pytest.raises(HTTPException) as exc_info:
        await update_team_member_role(user_id="mgr1", body=body, current_user=mgr_user)

    assert exc_info.value.status_code == 403


@pytest.mark.asyncio
async def test_update_role_last_manager():
    """Demoting the last manager must return HTTP 409 LAST_MANAGER_GUARD."""
    from app.routes.company import update_team_member_role
    from app.schemas.org import UpdateRoleRequest
    from fastapi import HTTPException

    mgr_user = FakeUser(user_id="mgr1", role="company_manager", company_id="comp1")
    target = FakeUser(user_id="mgr2", role="company_manager", company_id="comp1")
    body = UpdateRoleRequest(role="recruiter")

    qm = _make_query_mock(count=1)

    with patch("app.routes.company.get_user_or_404", new_callable=AsyncMock, return_value=target), \
         patch.object(UserModel, "find", return_value=qm, create=True):
        with pytest.raises(HTTPException) as exc_info:
            await update_team_member_role(user_id="mgr2", body=body, current_user=mgr_user)

    assert exc_info.value.status_code == 409
    assert "LAST_MANAGER_GUARD" in exc_info.value.detail


@pytest.mark.asyncio
async def test_update_role_cross_company():
    """Cannot update role of a user from a different company."""
    from app.routes.company import update_team_member_role
    from app.schemas.org import UpdateRoleRequest
    from fastapi import HTTPException

    mgr_user = FakeUser(user_id="mgr1", role="company_manager", company_id="compA")
    target = FakeUser(user_id="other1", role="recruiter", company_id="compB")
    body = UpdateRoleRequest(role="company_manager")

    with patch("app.routes.company.get_user_or_404", new_callable=AsyncMock, return_value=target):
        with pytest.raises(HTTPException) as exc_info:
            await update_team_member_role(user_id="other1", body=body, current_user=mgr_user)

    assert exc_info.value.status_code == 403


# ---------------------------------------------------------------------------
# GET /api/admin/companies — all statuses returned (CRITICAL FIX 3)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_admin_companies_returns_all_statuses():
    """GET /api/admin/companies must return companies of ALL statuses including
    pending_verification and rejected — intentional behaviour, not a bug (FIX 3)."""
    from app.routes.admin import list_companies

    admin_user = FakeUser(user_id="admin1", role="super_admin", company_id=None)
    companies = [
        FakeCompany(company_id="c1", status="active"),
        FakeCompany(company_id="c2", status="inactive"),
        FakeCompany(company_id="c3", status="pending_verification"),
        FakeCompany(company_id="c4", status="rejected"),
    ]

    qm = _make_query_mock(results=companies)

    with patch.object(CompanyModel, "find_all", return_value=qm, create=True):
        result = await list_companies(current_user=admin_user)

    statuses = {r["status"] for r in result}
    assert "pending_verification" in statuses, "pending_verification orgs must appear in admin list"
    assert "rejected" in statuses, "rejected orgs must appear in admin list"
    assert len(result) == 4


# ---------------------------------------------------------------------------
# NEW TESTS — GAP 1: OrgRegisterRequest with full fields
# ---------------------------------------------------------------------------

def test_register_with_full_fields():
    """OrgRegisterRequest must accept all new required and optional fields without error."""
    from app.schemas.org import OrgRegisterRequest

    body = OrgRegisterRequest(
        org_name="Full Corp",
        manager_name="Alice",
        manager_email="alice@full.com",
        password="Secret123",
        org_type="Private Limited",
        registration_number="U12345MH2020PTC123456",
        pan="ABCDE1234F",
        gstin="27ABCDE1234F1Z5",
        registered_address="123 Main St, Mumbai",
        website="https://fullcorp.com",
        official_phone="+919876543210",
        authorized_person_name="Bob Smith",
        authorized_person_designation="Director",
        authorized_person_email="bob@full.com",
        authorized_person_phone="+919876543211",
    )
    # Should not raise ValidationError
    assert body.org_name == "Full Corp"
    assert body.org_type == "Private Limited"
    assert body.pan == "ABCDE1234F"
    assert body.authorized_person_name == "Bob Smith"


def test_register_missing_org_type_raises_validation_error():
    """org_type is required — omitting it must raise ValidationError."""
    from app.schemas.org import OrgRegisterRequest
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        OrgRegisterRequest(
            org_name="TypelessCorp",
            manager_name="Alice",
            manager_email="alice@typeless.com",
            password="Secret123",
            # org_type missing
            registered_address="123 Main St",
            official_phone="+919876543210",
            authorized_person_name="Alice",
            authorized_person_designation="Director",
            authorized_person_email="alice.auth@typeless.com",
            authorized_person_phone="+919876543211",
        )


def test_register_required_verification_docs_validate():
    """OrgDocumentOut schema must serialize correctly."""
    from app.schemas.org import OrgDocumentOut
    from datetime import datetime, timezone

    doc = OrgDocumentOut(
        id="doc1",
        company_id="comp1",
        document_type="pan_document",
        file_name="pan.pdf",
        uploaded_at=datetime.now(timezone.utc),
        uploaded_by="user1",
        verification_status="pending",
    )
    assert doc.document_type == "pan_document"
    assert doc.verification_status == "pending"


# ---------------------------------------------------------------------------
# NEW TESTS — GAP 4: Pending org can login
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_pending_org_can_login():
    """A user from a pending organization MUST be allowed to log in (GAP 4)."""
    from app.routes.auth import login
    from app.schemas.auth import LoginRequest
    from fastapi import Request

    pending_company = FakeCompany(status="pending_verification", verification_status="pending")
    user = FakeUser(role="company_manager", company_id="comp_pending")
    user.password_hash = __import__("bcrypt").hashpw(b"Secret123", __import__("bcrypt").gensalt()).decode()

    body = LoginRequest(email="mgr@pending.com", password="Secret123")

    mock_request = MagicMock(spec=Request)
    mock_request.app = MagicMock()
    mock_request.app.state = MagicMock()

    with patch.object(UserModel, "find_one", new_callable=AsyncMock, return_value=user, create=True), \
         patch.object(UserModel, "email", new=MagicMock(), create=True), \
         patch("app.routes.auth.Company.get", new_callable=AsyncMock, return_value=pending_company), \
         patch("app.routes.auth.verify_password", return_value=True), \
         patch("app.routes.auth.create_access_token", return_value="pending.jwt.token"):
        result = await login.__wrapped__(mock_request, body)

    # Must succeed — pending org is NOT blocked from login
    assert result.access_token == "pending.jwt.token"


@pytest.mark.asyncio
async def test_inactive_org_login_blocked_returns_403():
    """Login must be blocked for users of an inactive (not just rejected) company."""
    from app.routes.auth import login
    from app.schemas.auth import LoginRequest
    from fastapi import HTTPException, Request

    inactive_company = FakeCompany(status="inactive")
    user = FakeUser(role="company_manager", company_id="comp_inactive")
    user.password_hash = __import__("bcrypt").hashpw(b"Secret123", __import__("bcrypt").gensalt()).decode()

    body = LoginRequest(email="mgr@inactive.com", password="Secret123")

    mock_request = MagicMock(spec=Request)
    mock_request.app = MagicMock()
    mock_request.app.state = MagicMock()

    with patch.object(UserModel, "find_one", new_callable=AsyncMock, return_value=user, create=True), \
         patch.object(UserModel, "email", new=MagicMock(), create=True), \
         patch("app.routes.auth.Company.get", new_callable=AsyncMock, return_value=inactive_company), \
         patch("app.routes.auth.verify_password", return_value=True):
        with pytest.raises(HTTPException) as exc_info:
            await login.__wrapped__(mock_request, body)

    assert exc_info.value.status_code == 403


# ---------------------------------------------------------------------------
# NEW TESTS — GAP 7: Subscription enforcement with new plan-based limits
# ---------------------------------------------------------------------------

class FakeSubscriptionPlan:
    """Fake SubscriptionPlan for unit tests — mirrors SubscriptionPlan model fields."""
    def __init__(
        self,
        plan_id="plan1",
        plan_name="Basic",
        max_admins=1,
        max_recruiters=5,
        max_interviews=25,
        status="active",
    ):
        self.id = plan_id
        self.plan_name = plan_name
        self.max_admins = max_admins
        self.max_recruiters = max_recruiters
        self.max_interviews = max_interviews
        self.status = status


@pytest.mark.asyncio
async def test_subscription_inactive_blocks_recruiter_creation():
    """enforce_recruiter_limit must raise 403 when subscription_status != active."""
    from app.core.subscription import enforce_recruiter_limit
    from fastapi import HTTPException

    company = FakeCompany(
        company_id="comp1",
        verification_status="approved",
        subscription_plan_id="plan1",
        subscription_status="inactive",
    )

    with pytest.raises(HTTPException) as exc_info:
        await enforce_recruiter_limit(company)

    assert exc_info.value.status_code == 403


@pytest.mark.asyncio
async def test_subscription_inactive_blocks_admin_creation():
    """enforce_admin_limit must raise 403 when subscription_status != active."""
    from app.core.subscription import enforce_admin_limit
    from fastapi import HTTPException

    company = FakeCompany(
        company_id="comp1",
        verification_status="approved",
        subscription_plan_id="plan1",
        subscription_status="inactive",
    )

    with pytest.raises(HTTPException) as exc_info:
        await enforce_admin_limit(company)

    assert exc_info.value.status_code == 403


@pytest.mark.asyncio
async def test_subscription_inactive_blocks_interview_creation():
    """enforce_interview_limit must raise 403 when subscription_status != active."""
    from app.core.subscription import enforce_interview_limit
    from fastapi import HTTPException

    company = FakeCompany(
        company_id="comp1",
        verification_status="approved",
        subscription_plan_id="plan1",
        subscription_status="inactive",
    )

    with pytest.raises(HTTPException) as exc_info:
        await enforce_interview_limit(company)

    assert exc_info.value.status_code == 403


@pytest.mark.asyncio
async def test_basic_plan_recruiter_limit_5():
    """Basic plan allows max 5 recruiters — 6th attempt must raise 409."""
    from app.core.subscription import enforce_recruiter_limit
    from fastapi import HTTPException

    company = FakeCompany(
        company_id="comp1",
        verification_status="approved",
        subscription_plan_id="plan_basic",
        subscription_status="active",
    )
    basic_plan = FakeSubscriptionPlan(plan_name="Basic", max_recruiters=5, max_admins=1, max_interviews=25)

    qm = _make_query_mock(count=5)

    with patch("app.core.subscription.SubscriptionPlan.get", new_callable=AsyncMock, return_value=basic_plan), \
         patch.object(UserModel, "find", return_value=qm, create=True):
        with pytest.raises(HTTPException) as exc_info:
            await enforce_recruiter_limit(company)

    assert exc_info.value.status_code == 409
    assert "Recruiter limit" in exc_info.value.detail


@pytest.mark.asyncio
async def test_basic_plan_admin_limit_1():
    """Basic plan allows max 1 admin — 2nd attempt must raise 409."""
    from app.core.subscription import enforce_admin_limit
    from fastapi import HTTPException

    company = FakeCompany(
        company_id="comp1",
        verification_status="approved",
        subscription_plan_id="plan_basic",
        subscription_status="active",
    )
    basic_plan = FakeSubscriptionPlan(plan_name="Basic", max_recruiters=5, max_admins=1, max_interviews=25)

    qm = _make_query_mock(count=1)

    with patch("app.core.subscription.SubscriptionPlan.get", new_callable=AsyncMock, return_value=basic_plan), \
         patch.object(UserModel, "find", return_value=qm, create=True):
        with pytest.raises(HTTPException) as exc_info:
            await enforce_admin_limit(company)

    assert exc_info.value.status_code == 409
    assert "Admin limit" in exc_info.value.detail


@pytest.mark.asyncio
async def test_professional_plan_limits():
    """Professional plan allows max 3 admins, 15 recruiters, 100 interviews."""
    professional_plan = FakeSubscriptionPlan(
        plan_name="Professional",
        max_admins=3,
        max_recruiters=15,
        max_interviews=100,
    )
    assert professional_plan.max_admins == 3
    assert professional_plan.max_recruiters == 15
    assert professional_plan.max_interviews == 100


@pytest.mark.asyncio
async def test_enterprise_plan_limits():
    """Enterprise plan allows max 10 admins, 50 recruiters, 500 interviews."""
    enterprise_plan = FakeSubscriptionPlan(
        plan_name="Enterprise",
        max_admins=10,
        max_recruiters=50,
        max_interviews=500,
    )
    assert enterprise_plan.max_admins == 10
    assert enterprise_plan.max_recruiters == 50
    assert enterprise_plan.max_interviews == 500


@pytest.mark.asyncio
async def test_expired_subscription_blocks_recruiter_creation():
    """An expired subscription must raise 403, not silently downgrade."""
    from app.core.subscription import enforce_recruiter_limit
    from fastapi import HTTPException
    from datetime import timedelta

    expired_at = _utc_now() - timedelta(days=1)
    company = FakeCompany(
        company_id="comp1",
        verification_status="approved",
        subscription_plan_id="plan1",
        subscription_status="active",
        subscription_expires_at=expired_at,
    )

    with pytest.raises(HTTPException) as exc_info:
        await enforce_recruiter_limit(company)

    assert exc_info.value.status_code == 403
    assert "expired" in exc_info.value.detail.lower()


@pytest.mark.asyncio
async def test_expired_subscription_blocks_interview_creation():
    """An expired subscription must block interview creation with 403."""
    from app.core.subscription import enforce_interview_limit
    from fastapi import HTTPException
    from datetime import timedelta

    expired_at = _utc_now() - timedelta(days=1)
    company = FakeCompany(
        company_id="comp1",
        verification_status="approved",
        subscription_plan_id="plan1",
        subscription_status="active",
        subscription_expires_at=expired_at,
    )

    with pytest.raises(HTTPException) as exc_info:
        await enforce_interview_limit(company)

    assert exc_info.value.status_code == 403


@pytest.mark.asyncio
async def test_pending_org_blocks_recruiter_enforce():
    """check_org_approved must raise 403 when verification_status == pending."""
    from app.core.subscription import check_org_approved
    from fastapi import HTTPException

    company = FakeCompany(
        company_id="comp1",
        verification_status="pending",
    )

    with pytest.raises(HTTPException) as exc_info:
        await check_org_approved(company)

    assert exc_info.value.status_code == 403
    assert "pending" in exc_info.value.detail.lower()


# ---------------------------------------------------------------------------
# NEW TESTS — GAP 10: Candidate history by candidate_id
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_candidate_history_by_candidate_id():
    """Interviews linked only by candidate_id (no email match) must appear in history."""
    from app.routes.candidates import candidate_history

    candidate = FakeUser(user_id="cand1", role="candidate", email="cand1@test.com", company_id=None)
    interview_by_id = FakeInterview(
        interview_id="iv_cid",
        candidate_email="other@test.com",  # email doesn't match
        candidate_id="cand1",              # but candidate_id does
    )

    # by_email returns nothing; by_id returns one interview
    qm_empty = _make_query_mock(results=[])
    qm_by_id = _make_query_mock(results=[interview_by_id])

    call_count = {"n": 0}

    def side_effect_find(*args, **kwargs):
        call_count["n"] += 1
        # First call: by email → empty; second call: by candidate_id → one result
        if call_count["n"] == 1:
            return qm_empty
        return qm_by_id

    with patch.object(InterviewModel, "find", side_effect=side_effect_find, create=True), \
         patch.object(InterviewModel, "candidate_email", new=MagicMock(), create=True), \
         patch.object(InterviewModel, "candidate_id", new=MagicMock(), create=True):
        result = await candidate_history(current_user=candidate)

    assert len(result) == 1
    assert result[0]["id"] == "iv_cid"


@pytest.mark.asyncio
async def test_candidate_cannot_access_another_candidates_history():
    """candidate_id is scoped to current_user.id — another candidate's history is not returned."""
    from app.routes.candidates import candidate_history

    candidate_a = FakeUser(user_id="candA", role="candidate", email="a@test.com", company_id=None)
    # Only interviews belonging to candidate_a's email/id are returned by the mock
    # Interview with candidate_id="candB" will NOT be in the results
    qm_empty = _make_query_mock(results=[])

    with patch.object(InterviewModel, "find", return_value=qm_empty, create=True), \
         patch.object(InterviewModel, "candidate_email", new=MagicMock(), create=True), \
         patch.object(InterviewModel, "candidate_id", new=MagicMock(), create=True):
        result = await candidate_history(current_user=candidate_a)

    assert result == []


@pytest.mark.asyncio
async def test_candidate_history_deduplicates_by_id():
    """An interview matched by both email and candidate_id must appear only once."""
    from app.routes.candidates import candidate_history

    candidate = FakeUser(user_id="cand1", role="candidate", email="cand1@test.com", company_id=None)
    shared_interview = FakeInterview(
        interview_id="iv_shared",
        candidate_email="cand1@test.com",
        candidate_id="cand1",
    )

    # Both queries return the same interview
    qm = _make_query_mock(results=[shared_interview])

    with patch.object(InterviewModel, "find", return_value=qm, create=True), \
         patch.object(InterviewModel, "candidate_email", new=MagicMock(), create=True), \
         patch.object(InterviewModel, "candidate_id", new=MagicMock(), create=True):
        result = await candidate_history(current_user=candidate)

    # Must be deduplicated — only 1 result, not 2
    assert len(result) == 1
    assert result[0]["id"] == "iv_shared"


# ---------------------------------------------------------------------------
# NEW TESTS — GAP 6: Seed idempotency
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_seed_is_idempotent():
    """seed_subscription_plans must not insert a plan that already exists."""
    from app.seed_plans import seed_subscription_plans
    from app.models.subscription_plan import SubscriptionPlan

    existing_plan = FakeSubscriptionPlan(plan_name="Basic")
    existing_plan.insert = AsyncMock()

    # find_one returns an existing plan — insert must NOT be called
    with patch.object(SubscriptionPlan, "find_one", new_callable=AsyncMock, return_value=existing_plan, create=True):
        await seed_subscription_plans()

    # insert() is on the instance returned by find_one, not on a new object —
    # no new SubscriptionPlan(...).insert() call should happen
    existing_plan.insert.assert_not_called()


@pytest.mark.asyncio
async def test_seed_inserts_when_no_plans_exist():
    """seed_subscription_plans must insert all 3 plans when none exist."""
    from app.seed_plans import seed_subscription_plans, PLANS
    from app.models.subscription_plan import SubscriptionPlan

    inserted_plans = []

    class CapturingPlan:
        def __init__(self, **kwargs):
            self.plan_name = kwargs.get("plan_name")
            inserted_plans.append(self)

        async def insert(self):
            return self

        @classmethod
        async def find_one(cls, query=None):
            return None

    with patch("app.seed_plans.SubscriptionPlan", CapturingPlan):
        await seed_subscription_plans()

    assert len(inserted_plans) == len(PLANS)


# ---------------------------------------------------------------------------
# NEW TESTS — GAP 3: Super Admin document endpoints
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_super_admin_can_list_all_orgs():
    """GET /api/admin/orgs must return all organizations for super_admin."""
    from app.routes.admin import list_all_orgs

    admin_user = FakeUser(user_id="admin1", role="super_admin", company_id=None)
    companies = [
        FakeCompany(company_id="c1", status="active"),
        FakeCompany(company_id="c2", status="pending_verification"),
    ]

    qm = _make_query_mock(results=companies)

    with patch.object(CompanyModel, "find_all", return_value=qm, create=True), \
         patch.object(UserModel, "find_one", new_callable=AsyncMock, return_value=None, create=True):
        result = await list_all_orgs(status=None, current_user=admin_user)

    assert len(result) == 2


@pytest.mark.asyncio
async def test_super_admin_can_list_org_documents():
    """GET /api/admin/orgs/{company_id}/documents must return document list."""
    from app.routes.admin import list_org_documents
    from app.models.org_document import OrgDocument as OrgDocumentModel

    admin_user = FakeUser(user_id="admin1", role="super_admin", company_id=None)
    company = FakeCompany(company_id="comp_doc")

    class FakeOrgDocument:
        def __init__(self):
            self.id = "doc1"
            self.company_id = "comp_doc"
            self.document_type = "pan_document"
            self.file_name = "pan.pdf"
            self.uploaded_at = _utc_now()
            self.uploaded_by = "user1"
            self.verification_status = "pending"

    fake_doc = FakeOrgDocument()
    qm = _make_query_mock(results=[fake_doc])

    with patch("app.routes.admin.get_company_or_404", new_callable=AsyncMock, return_value=company), \
         patch.object(OrgDocumentModel, "find", return_value=qm, create=True):
        result = await list_org_documents(company_id="comp_doc", current_user=admin_user)

    assert len(result) == 1
    assert result[0]["document_type"] == "pan_document"


@pytest.mark.asyncio
async def test_non_super_admin_cannot_list_org_documents():
    """Non-super_admin must get 403 when accessing org documents."""
    from app.routes.admin import list_org_documents
    from fastapi import HTTPException

    mgr_user = FakeUser(user_id="mgr1", role="company_manager", company_id="comp1")

    with pytest.raises(HTTPException) as exc_info:
        await list_org_documents(company_id="comp1", current_user=mgr_user)

    assert exc_info.value.status_code == 403


# ---------------------------------------------------------------------------
# NEW TESTS — GAP 8: Subscription plan management
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_super_admin_can_list_subscription_plans():
    """GET /api/admin/subscription-plans must return plans list."""
    from app.routes.admin import list_subscription_plans
    from app.models.subscription_plan import SubscriptionPlan as SPModel

    admin_user = FakeUser(user_id="admin1", role="super_admin", company_id=None)
    plans = [
        FakeSubscriptionPlan(plan_id="p1", plan_name="Basic", max_admins=1, max_recruiters=5, max_interviews=25),
        FakeSubscriptionPlan(plan_id="p2", plan_name="Professional", max_admins=3, max_recruiters=15, max_interviews=100),
    ]

    qm = _make_query_mock(results=plans)

    with patch.object(SPModel, "find_all", return_value=qm, create=True):
        result = await list_subscription_plans(current_user=admin_user)

    assert len(result) == 2
    plan_names = {p["plan_name"] for p in result}
    assert "Basic" in plan_names
    assert "Professional" in plan_names


@pytest.mark.asyncio
async def test_patch_subscription_with_plan_id():
    """PATCH /api/admin/orgs/{id}/subscription must assign plan and set active status."""
    from app.routes.admin import patch_subscription
    from app.schemas.org import PatchSubscriptionRequest
    from app.models.subscription_plan import SubscriptionPlan as SPModel

    admin_user = FakeUser(user_id="admin1", role="super_admin", company_id=None)
    company = FakeCompany(company_id="comp1", subscription_status="inactive")
    plan = FakeSubscriptionPlan(plan_id="plan_basic", plan_name="Basic")
    body = PatchSubscriptionRequest(plan_id="plan_basic")

    with patch("app.routes.admin.get_company_or_404", new_callable=AsyncMock, return_value=company), \
         patch.object(SPModel, "get", new_callable=AsyncMock, return_value=plan, create=True):
        result = await patch_subscription(company_id="comp1", body=body, current_user=admin_user)

    assert result["subscription_plan_id"] == "plan_basic"
    assert result["subscription_status"] == "active"


# ---------------------------------------------------------------------------
# FIX 2: Secure candidate-to-interview association
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_candidate_cannot_claim_another_candidates_interview():
    """A candidate must not be able to claim an interview already assigned to someone else."""
    from app.routes.interviews import get_by_code
    from fastapi import HTTPException

    candidate = FakeUser(user_id="cand_new", role="candidate", email="new@test.com")
    interview = FakeInterview(
        interview_id="iv_taken",
        interview_code="TAKEN001",
        candidate_id="cand_existing",  # already claimed
    )

    with patch.object(InterviewModel, "find_one", new_callable=AsyncMock, return_value=interview, create=True), \
         patch.object(InterviewModel, "interview_code", new=MagicMock(), create=True):
        with pytest.raises(HTTPException) as exc_info:
            await get_by_code(code="TAKEN001", current_user=candidate)

    assert exc_info.value.status_code == 403
    assert "different candidate" in exc_info.value.detail.lower()


@pytest.mark.asyncio
async def test_candidate_cannot_claim_interview_assigned_to_different_email():
    """A candidate must not claim an interview pre-assigned to a different email."""
    from app.routes.interviews import get_by_code
    from fastapi import HTTPException

    candidate = FakeUser(user_id="cand_wrong", role="candidate", email="wrong@test.com")
    interview = FakeInterview(
        interview_id="iv_email",
        interview_code="EMAIL001",
        candidate_email="correct@test.com",  # different email
        candidate_id=None,
    )

    with patch.object(InterviewModel, "find_one", new_callable=AsyncMock, return_value=interview, create=True), \
         patch.object(InterviewModel, "interview_code", new=MagicMock(), create=True):
        with pytest.raises(HTTPException) as exc_info:
            await get_by_code(code="EMAIL001", current_user=candidate)

    assert exc_info.value.status_code == 403
    assert "not assigned to your account" in exc_info.value.detail.lower()


@pytest.mark.asyncio
async def test_candidate_can_claim_unassigned_interview():
    """A candidate can claim an interview with no pre-assigned email or candidate_id."""
    from app.routes.interviews import get_by_code

    candidate = FakeUser(user_id="cand_free", role="candidate", email="free@test.com")
    interview = FakeInterview(
        interview_id="iv_free",
        interview_code="FREE001",
        candidate_email=None,
        candidate_id=None,
    )
    interview.save = AsyncMock()

    with patch.object(InterviewModel, "find_one", new_callable=AsyncMock, return_value=interview, create=True), \
         patch.object(InterviewModel, "interview_code", new=MagicMock(), create=True):
        result = await get_by_code(code="FREE001", current_user=candidate)

    assert result["interview_code"] == "FREE001"
    interview.save.assert_called_once()
    assert interview.candidate_id == "cand_free"


# ---------------------------------------------------------------------------
# FIX 3: Required documents before approval
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_super_admin_cannot_approve_without_required_documents():
    """Approval must fail with 422 when required documents are missing."""
    from app.routes.admin import approve_org
    from app.models.org_document import OrgDocument as OrgDocModel
    from fastapi import HTTPException

    admin_user = FakeUser(user_id="admin1", role="super_admin", company_id=None)
    pending = FakeCompany(company_id="comp_nodoc", status="pending_verification", verification_status="pending")

    # Only one doc uploaded — missing the other required types
    fake_docs = [MagicMock(document_type="pan_document")]
    doc_qm = _make_query_mock(results=fake_docs)

    with patch("app.routes.admin.get_company_or_404", new_callable=AsyncMock, return_value=pending), \
         patch.object(OrgDocModel, "find", return_value=doc_qm, create=True):
        with pytest.raises(HTTPException) as exc_info:
            await approve_org(company_id="comp_nodoc", current_user=admin_user)

    assert exc_info.value.status_code == 422
    assert "missing required documents" in exc_info.value.detail.lower()


@pytest.mark.asyncio
async def test_super_admin_cannot_approve_with_zero_documents():
    """Approval must fail when no documents have been uploaded at all."""
    from app.routes.admin import approve_org
    from app.models.org_document import OrgDocument as OrgDocModel
    from fastapi import HTTPException

    admin_user = FakeUser(user_id="admin1", role="super_admin", company_id=None)
    pending = FakeCompany(company_id="comp_empty", status="pending_verification", verification_status="pending")

    doc_qm = _make_query_mock(results=[])

    with patch("app.routes.admin.get_company_or_404", new_callable=AsyncMock, return_value=pending), \
         patch.object(OrgDocModel, "find", return_value=doc_qm, create=True):
        with pytest.raises(HTTPException) as exc_info:
            await approve_org(company_id="comp_empty", current_user=admin_user)

    assert exc_info.value.status_code == 422


# ---------------------------------------------------------------------------
# FIX 1: Verified org without subscription cannot create interviews
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_verified_org_without_subscription_cannot_create_interview():
    """Approved org with no subscription_plan_id must be blocked from creating interviews."""
    from app.routes.interviews import create_interview
    from app.schemas.interview import CreateInterviewRequest
    from fastapi import HTTPException

    recruiter = FakeUser(user_id="rec1", role="recruiter", company_id="comp_nosub")
    # Approved but no subscription
    company = FakeCompany(company_id="comp_nosub", verification_status="approved")
    company.subscription_plan_id = None
    company.subscription_status = "inactive"

    body = CreateInterviewRequest(title="Test Interview")

    with patch("app.routes.interviews.Company.get", new_callable=AsyncMock, return_value=company):
        with pytest.raises(HTTPException) as exc_info:
            await create_interview(body=body, current_user=recruiter)

    assert exc_info.value.status_code == 403
    assert "subscription" in exc_info.value.detail.lower()


@pytest.mark.asyncio
async def test_expired_subscription_blocks_interview_creation():
    """Expired subscription must block interview creation."""
    from app.routes.interviews import create_interview
    from app.schemas.interview import CreateInterviewRequest
    from app.models.subscription_plan import SubscriptionPlan as SPModel
    from fastapi import HTTPException
    from datetime import timedelta

    recruiter = FakeUser(user_id="rec1", role="recruiter", company_id="comp_exp")
    company = FakeCompany(company_id="comp_exp", verification_status="approved")
    company.subscription_plan_id = "plan1"
    company.subscription_status = "active"
    company.subscription_expires_at = datetime.now(timezone.utc) - timedelta(days=1)  # expired

    fake_plan = MagicMock()
    fake_plan.max_interviews = 100

    body = CreateInterviewRequest(title="Blocked Interview")

    with patch("app.routes.interviews.Company.get", new_callable=AsyncMock, return_value=company), \
         patch.object(SPModel, "get", new_callable=AsyncMock, return_value=fake_plan):
        with pytest.raises(HTTPException) as exc_info:
            await create_interview(body=body, current_user=recruiter)

    assert exc_info.value.status_code == 403
    assert "expired" in exc_info.value.detail.lower()


# ---------------------------------------------------------------------------
# FIX 4: Upload cleanup on failure — magic bytes rejection
# ---------------------------------------------------------------------------

def test_validate_magic_bytes_rejects_non_pdf():
    """A file with wrong magic bytes must be rejected even if extension is .pdf."""
    from app.routes.org import _validate_magic_bytes
    from fastapi import HTTPException

    fake_content = b"This is not a PDF file at all"
    with pytest.raises(HTTPException) as exc_info:
        _validate_magic_bytes(fake_content, "fake.pdf")

    assert exc_info.value.status_code == 422
    assert "content does not match" in exc_info.value.detail.lower()


def test_validate_magic_bytes_accepts_valid_pdf():
    """A file starting with %PDF must pass magic bytes check."""
    from app.routes.org import _validate_magic_bytes

    pdf_content = b"%PDF-1.4 fake pdf content"
    _validate_magic_bytes(pdf_content, "real.pdf")  # should not raise


def test_validate_magic_bytes_accepts_jpeg():
    """A JPEG file must pass magic bytes check."""
    from app.routes.org import _validate_magic_bytes

    jpeg_content = b"\xff\xd8\xff\xe0 fake jpeg content"
    _validate_magic_bytes(jpeg_content, "image.jpg")  # should not raise
