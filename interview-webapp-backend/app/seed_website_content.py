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


async def seed_website_content():
    if not CONTENT_FILE.is_file():
        raise FileNotFoundError(
            f"Website content JSON not found: {CONTENT_FILE}"
        )

    with CONTENT_FILE.open("r", encoding="utf-8") as file:
        sections = json.load(file)

    if not isinstance(sections, list) or not sections:
        raise ValueError(
            "website_content.json must be a non-empty JSON array of section objects."
        )

    client = AsyncIOMotorClient(settings.MONGO_URI)

    try:
        await client.admin.command("ping")

        database = client[settings.DB_NAME]

        await init_beanie(
            database=database,
            document_models=[WebsiteContent],
        )

        now = datetime.now(timezone.utc)
        created_count = 0
        updated_count = 0

        for item in sections:
            section_name = item.get("section")
            section_content = item.get("content")

            if not section_name or section_content is None:
                print(f"  Skipping malformed entry (missing 'section' or 'content'): {item}")
                continue

            existing = await WebsiteContent.find_one(
                WebsiteContent.section == section_name
            )

            if existing:
                existing.content = section_content
                existing.updated_at = now
                await existing.save()
                updated_count += 1
                action = "updated"
            else:
                await WebsiteContent(
                    section=section_name,
                    content=section_content,
                    created_at=now,
                    updated_at=now,
                ).insert()
                created_count += 1
                action = "created"

            print(f"  [{action}] section: {section_name}")

        print(
            f"\nDone. {created_count} created, {updated_count} updated. "
            f"Database: {settings.DB_NAME}, collection: sections"
        )

    finally:
        client.close()


if __name__ == "__main__":
    asyncio.run(seed_website_content())
