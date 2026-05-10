from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    TELEGRAM_TOKEN: str = Field(..., min_length=1)
    GEMINI_API_KEY: str = Field(..., min_length=1)
    CONTACT_EMAIL: str = Field(..., min_length=1)

    LOG_LEVEL: str = "INFO"
    LLM_MODEL: str = "gemini-2.5-flash"


settings = Settings()
