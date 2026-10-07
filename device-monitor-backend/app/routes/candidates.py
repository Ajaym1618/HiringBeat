from fastapi import APIRouter, HTTPException, Header
from typing import Optional
from app.models.candidate_session import CandidateSession
from app.config import settings

router = APIRouter(prefix="/api", tags=["candidates"])


def _require_dashboard_key(x_dashboard_key: Optional[str]):
    if not x_dashboard_key or x_dashboard_key != settings.DASHBOARD_API_KEY:
        raise HTTPException(status_code=401, detail="Invalid dashboard key")


@router.get("/candidates")
async def list_candidates(x_dashboard_key: Optional[str] = Header(None)):
    _require_dashboard_key(x_dashboard_key)
    sessions = await CandidateSession.find_all().to_list()
    return [
        {
            "id": str(s.id),
            "candidate_name": s.candidate_name,
            "hostname": s.hostname,
            "status": s.status,
            "last_seen": s.last_seen,
            "created_at": s.created_at,
        }
        for s in sessions
    ]


@router.get("/candidates/{session_id}")
async def get_candidate(session_id: str, x_dashboard_key: Optional[str] = Header(None)):
    _require_dashboard_key(x_dashboard_key)
    session = await CandidateSession.get(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")
    return {
        "id": str(session.id),
        "candidate_name": session.candidate_name,
        "hostname": session.hostname,
        "device": session.device,
        "usb_events": session.usb_events,
        "wifi_events": session.wifi_events,
        "close_events": session.close_events,
        "status": session.status,
        "last_seen": session.last_seen,
        "created_at": session.created_at,
    }


@router.get("/candidates/{session_id}/pdf")
async def get_candidate_pdf(session_id: str, x_dashboard_key: Optional[str] = Header(None)):
    _require_dashboard_key(x_dashboard_key)
    session = await CandidateSession.get(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")
    # Stub: generate a minimal PDF report
    # TODO: replace with a real PDF library (e.g., reportlab or weasyprint)
    pdf_content = (
        f"%PDF-1.4\n1 0 obj\n<< /Type /Catalog >>\nendobj\n"
        f"% Candidate: {session.candidate_name}\n"
        f"% Hostname: {session.hostname}\n"
        f"% Status: {session.status}\n"
    ).encode()
    from fastapi.responses import Response
    return Response(
        content=pdf_content,
        media_type="application/pdf",
        headers={"Content-Disposition": f"attachment; filename=report_{session_id}.pdf"},
    )
