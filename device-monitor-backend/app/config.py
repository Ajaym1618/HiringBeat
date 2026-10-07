from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    SECRET_KEY: str = "change-me"
    DASHBOARD_API_KEY: str = "change-me"
    DEVICE_BRIDGE_KEY: str = "change-me"
    MONGO_URI_DEVICE: str = "mongodb://localhost:27017"
    DB_NAME_DEVICE: str = "interbeat_monitoring"
    BRIDGE_URL: str = "http://localhost:5000"
    PORT_DEVICE: int = 8081

    class Config:
        env_file = "../.env"  # root .env shared by both services
        extra = "ignore"      # ignore keys belonging to other services


settings = Settings()
