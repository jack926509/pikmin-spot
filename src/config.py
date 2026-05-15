from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    SLACK_BOT_TOKEN: str = Field(..., min_length=1)
    SLACK_APP_TOKEN: str = Field(..., min_length=1)
    OPENAI_API_KEY: str = Field(..., min_length=1)
    CONTACT_EMAIL: str = Field(..., min_length=1)

    LOG_LEVEL: str = "INFO"
    LLM_MODEL: str = "gpt-4o-mini"

    @field_validator("SLACK_BOT_TOKEN")
    @classmethod
    def _check_bot_token(cls, v: str) -> str:
        v = v.strip()
        if not v.startswith("xoxb-"):
            raise ValueError(
                "SLACK_BOT_TOKEN 必須以 'xoxb-' 開頭 (Bot User OAuth Token)。"
                " 請到 Slack App → Settings → Install App → Bot User OAuth Token 複製。"
            )
        return v

    @field_validator("SLACK_APP_TOKEN")
    @classmethod
    def _check_app_token(cls, v: str) -> str:
        v = v.strip()
        if not v.startswith("xapp-"):
            raise ValueError(
                "SLACK_APP_TOKEN 必須以 'xapp-' 開頭 (App-Level Token)。"
                " 請到 Slack App → Settings → Basic Information → App-Level Tokens →"
                " Generate Token (scope: connections:write) 取得;不要使用 xoxb- token。"
            )
        return v


settings = Settings()
