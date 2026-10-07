from pydantic_settings import BaseSettings
from typing import List


class Settings(BaseSettings):
    SECRET_KEY: str = "change-me"
    DEVICE_BRIDGE_KEY: str = "change-me"
    MONGO_URI: str = "mongodb://localhost:27017"
    DB_NAME: str = "interbeat_interview"
    JWT_EXPIRY_HOURS: int = 24
    DEVICE_MONITOR_URL: str = "http://localhost:8081"
    CORS_ORIGINS: str = "*"
    UPLOAD_FOLDER: str = "uploads"
    PORT: int = 5000

    class Config:
        env_file = "../.env"  # root .env shared by both services
        extra = "ignore"      # ignore keys belonging to other services


settings = Settings()
