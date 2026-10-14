"""
Bootstrap Script — Create Super Admin Account
=============================================
Run this ONCE to create the first super_admin account.
After running, use the credentials to log in at POST /api/auth/login

Usage:
    python bootstrap_admin.py

Make sure your .env file is configured before running this.
"""

import asyncio
import sys
import os

sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from motor.motor_asyncio import AsyncIOMotorClient
from beanie import init_beanie
from app.config import settings
from app.models.user import User
from app.models.company import Company
from app.models.interview import Interview
from app.models.activity_log import ActivityLog
from app.models.device_link import DeviceLink
from app.models.app_config import AppConfig
from app.models.build_job import BuildJob
from app.models.org_document import OrgDocument
from app.models.subscription_plan import SubscriptionPlan
import bcrypt


async def bootstrap():
    print("\n🔌 Connecting to MongoDB...")
    client = AsyncIOMotorClient(settings.MONGO_URI)

    try:
        await client.admin.command("ping")
        print(f"✅ Connected → database: '{settings.DB_NAME}'")
    except Exception as e:
        print(f"❌ MongoDB connection failed: {e}")
        return

    await init_beanie(
        database=client[settings.DB_NAME],
        document_models=[
            User, Company, Interview, ActivityLog,
            DeviceLink, AppConfig, BuildJob,
            OrgDocument, SubscriptionPlan,
        ],
    )

    # Check if super_admin already exists
    existing = await User.find_one(User.role == "super_admin")
    if existing:
        print(f"\n⚠️  Super admin already exists: {existing.email}")
        print("No changes made. Delete the existing super_admin first if you want to recreate it.")
        return

    print("\n👤 Creating Super Admin Account")
    print("-" * 35)
    name = input("Name: ").strip()
    email = input("Email: ").strip()
    password = input("Password: ").strip()

    if not name or not email or not password:
        print("❌ All fields are required.")
        return

    if len(password) < 8:
        print("❌ Password must be at least 8 characters.")
        return

    password_hash = bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")

    admin = User(
        email=email,
        password_hash=password_hash,
        name=name,
        role="super_admin",
    )
    await admin.insert()

    print(f"\n✅ Super admin created!")
    print(f"   Name  : {name}")
    print(f"   Email : {email}")
    print(f"   Role  : super_admin")
    print(f"\n🚀 Login at POST /api/auth/login")
    print(f'   Body: {{"email": "{email}", "password": "<your password>", "role": "super_admin"}}')


if __name__ == "__main__":
    asyncio.run(bootstrap())
