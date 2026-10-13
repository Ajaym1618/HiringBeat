
from fastapi import APIRouter, HTTPException, Response

from app.models.website_content import WebsiteContent


router = APIRouter(
    prefix="/api/content",
    tags=["website content"],
)


@router.get("/public")
async def get_public_website_content(response: Response):
    """Return the current public website content from MongoDB."""

    response.headers["Cache-Control"] = (
        "no-store, no-cache, must-revalidate, max-age=0"
    )

    document = await WebsiteContent.find_one(
        {"key": "homepage"}
    )

    if document is None:
        raise HTTPException(
            status_code=404,
            detail=(
                "Website content has not been seeded. "
                "Run: python -m app.seed_website_content"
            ),
        )

    return {
        "success": True,
        "data": document.content,
        "updated_at": document.updated_at.isoformat(),
    }
