import logging
from beanie import init_beanie
from motor.motor_asyncio import AsyncIOMotorClient
from app.config import settings
from app.models.user import User
from app.models.company import Company
from app.models.interview import Interview
from app.models.activity_log import ActivityLog
from app.models.device_link import DeviceLink
from app.models.app_config import AppConfig
from app.models.build_job import BuildJob

logger = logging.getLogger(__name__)


async def init_db():
    try:
        client = AsyncIOMotorClient(settings.MONGO_URI)

        # Ping the database to confirm connection
        await client.admin.command("ping")
        print(f"✅ MongoDB connected successfully → database: '{settings.DB_NAME}'")

        await init_beanie(
            database=client[settings.DB_NAME],
            document_models=[User, Company, Interview, ActivityLog, DeviceLink, AppConfig, BuildJob],
        )
        print("✅ Beanie ODM initialized — all models ready")

    except Exception as e:
        print(f"❌ MongoDB connection failed: {e}")
        raise
