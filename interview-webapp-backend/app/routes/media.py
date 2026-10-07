from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from typing import Optional, Dict, List

router = APIRouter(prefix="/api/media", tags=["media"])

# In-memory WebRTC signaling store
# TODO: replace with Redis in production
_offers: Dict[str, dict] = {}
_answers: Dict[str, dict] = {}
_ice: Dict[str, List[dict]] = {}


class SDPBody(BaseModel):
    sdp: str
    type: Optional[str] = None


class ICEBody(BaseModel):
    candidate: str
    sdpMid: Optional[str] = None
    sdpMLineIndex: Optional[int] = None


@router.post("/offer/{code}")
async def post_offer(code: str, body: SDPBody):
    _offers[code] = body.model_dump()
    return {"stored": True}


@router.get("/offer/{code}")
async def get_offer(code: str):
    offer = _offers.get(code)
    if not offer:
        raise HTTPException(status_code=404, detail="No offer found")
    return offer


@router.post("/answer/{code}")
async def post_answer(code: str, body: SDPBody):
    _answers[code] = body.model_dump()
    return {"stored": True}


@router.get("/answer/{code}")
async def get_answer(code: str):
    answer = _answers.get(code)
    if not answer:
        raise HTTPException(status_code=404, detail="No answer found")
    return answer


@router.post("/ice/{code}")
async def post_ice(code: str, body: ICEBody):
    _ice.setdefault(code, []).append(body.model_dump())
    return {"stored": True}


@router.get("/ice/{code}")
async def get_ice(code: str):
    return _ice.get(code, [])
