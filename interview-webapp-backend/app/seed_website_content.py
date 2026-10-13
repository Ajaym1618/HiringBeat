import asyncio
import json
from datetime import datetime, timezone
from pathlib import Path

from beanie import init_beanie
from motor.motor_asyncio import AsyncIOMotorClient

from app.config import settings
from app.models.website_content import WebsiteContent


CONTENT_FILE = (
    Path(__file__).resolve().parent.parent
    / "content"
    / "website_content.json"
)
CONTENT_KEY = "homepage"


async def seed_website_content():
    if not CONTENT_FILE.is_file():
        raise FileNotFoundError(
            f"Website content JSON not found: {CONTENT_FILE}"
        )

    with CONTENT_FILE.open("r", encoding="utf-8") as file:
        content = json.load(file)

    if not isinstance(content, dict) or not content:
        raise ValueError(
            "Website content must be a non-empty JSON object."
        )

    client = AsyncIOMotorClient(settings.MONGO_URI)

    try:
        await client.admin.command("ping")

        database = client[settings.DB_NAME]

        await init_beanie(
            database=database,
            document_models=[WebsiteContent],
        )

        existing = await WebsiteContent.find_one(
            {"key": CONTENT_KEY}
        )

        now = datetime.now(timezone.utc)

        if existing:
            existing.content = content
            existing.updated_at = now
            await existing.save()
            action = "updated"
        else:
            await WebsiteContent(
                key=CONTENT_KEY,
                content=content,
                updated_at=now,
            ).insert()
            action = "created"

        print(
            f"Website content {action} successfully. "
            f"Database: {settings.DB_NAME}; "
            f"collection: website_content; "
            f"sections: {len(content)}"
        )

    finally:
        client.close()


if __name__ == "__main__":
    asyncio.run(seed_website_content())
