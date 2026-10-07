import logging
from beanie import init_beanie
from motor.motor_asyncio import AsyncIOMotorClient
from app.config import settings
from app.models.candidate_session import CandidateSession

logger = logging.getLogger(__name__)


async def init_db():
    try:
        client = AsyncIOMotorClient(settings.MONGO_URI_DEVICE)

        # Ping the database to confirm connection
        await client.admin.command("ping")
        print(f"✅ MongoDB connected successfully → database: '{settings.DB_NAME_DEVICE}'")

        await init_beanie(
            database=client[settings.DB_NAME_DEVICE],
            document_models=[CandidateSession],
        )
        print("✅ Beanie ODM initialized — all models ready")

    except Exception as e:
        print(f"❌ MongoDB connection failed: {e}")
        raise
