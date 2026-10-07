from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    GATEWAY_PORT: int = 8080
    INTERVIEW_API_URL: str = "http://localhost:5000"
    DEVICE_MONITOR_API_URL: str = "http://localhost:8081"
    PROXY_TIMEOUT: int = 30
    GATEWAY_CORS_ORIGINS: str = "*"

    model_config = SettingsConfigDict(
        env_file="../.env",
        extra="ignore",
    )


settings = Settings()
