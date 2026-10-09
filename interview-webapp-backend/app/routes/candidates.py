from typing import List
from datetime import datetime
from fastapi import APIRouter, HTTPException, Depends, status
from app.models.interview import Interview
from app.models.user import User
from app.core.auth import get_current_user
from app.schemas.org import CandidateInterviewHistoryItem

router = APIRouter(prefix="/api/candidates", tags=["candidates"])


@router.get("/history", response_model=List[CandidateInterviewHistoryItem])
async def candidate_history(current_user: User = Depends(get_current_user)):
    """Return the interview history for the authenticated candidate.

    Merges results by email (backward compat) and by candidate_id (GAP 10).
    Only accessible to users with role='candidate'.
    Returns an empty list when no interviews are found — never raises 404.
    """
    if current_user.role != "candidate":
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Candidates only")

    # GAP 10: merge by email (backward compat) and by candidate_id
    by_email = await Interview.find(
        Interview.candidate_email == current_user.email
    ).to_list()

    try:
        by_id = await Interview.find(
            Interview.candidate_id == str(current_user.id)
        ).to_list()
    except Exception:
        by_id = []

    # Deduplicate and filter to prevent cross-candidate leakage
    seen: set = set()
    all_interviews: List = []
    # Always include interviews explicitly assigned to this candidate by ID
    for iv in by_id:
        if str(iv.id) not in seen:
            seen.add(str(iv.id))
            all_interviews.append(iv)
    # Include email-matched only if no different candidate_id is set
    for iv in by_email:
        if str(iv.id) not in seen:
            iv_candidate_id = getattr(iv, "candidate_id", None)
            if iv_candidate_id is None or iv_candidate_id == str(current_user.id):
                seen.add(str(iv.id))
                all_interviews.append(iv)

    # Sort by created_at descending (most recent first)
    all_interviews.sort(
        key=lambda x: x.created_at or datetime.min,
        reverse=True,
    )

    return [
        {
            "id": str(i.id),
            "title": i.title,
            "description": i.description,
            "interview_code": i.interview_code,
            "status": i.status,
            "company_id": i.company_id,
            "started_at": i.started_at,
            "ended_at": i.ended_at,
            "scheduled_at": i.scheduled_at,
            "created_at": i.created_at,
        }
        for i in all_interviews
        # recruiter_id and face_reference_path are intentionally excluded (FR-9.5)
        # response_model=List[CandidateInterviewHistoryItem] enforces this at serializer level
    ]
