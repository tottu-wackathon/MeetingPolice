from functools import lru_cache
from pathlib import Path
from typing import List

from pydantic import AnyHttpUrl, field_validator
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    api_host: str = "0.0.0.0"
    api_port: int = 8000
    api_debug: bool = True
    cors_origins: List[AnyHttpUrl] | List[str] = ["http://localhost:5173", "http://localhost:5174"]

    aws_region: str = "ap-northeast-1"
    aws_access_key_id: str | None = None
    aws_secret_access_key: str | None = None
    s3_bucket_name: str = "meeting-police-dev"
    bedrock_model_id: str = "anthropic.claude-v2"
    comprehend_language: str = "en"

    vonage_application_id: str = ""
    vonage_api_key: str = ""
    vonage_api_secret: str = ""
    vonage_private_key_path: str = "secrets/vonage_private.key"

    # Frontend static Vonage session (optional)
    vite_vonage_app_id: str | None = None
    vite_vonage_session_id: str | None = None
    vite_vonage_token: str | None = None

    @field_validator("cors_origins", mode="before")
    @classmethod
    def split_cors(cls, value: str | list[str]) -> list[str] | list[AnyHttpUrl]:
        if isinstance(value, str):
            items = [item.strip() for item in value.split(",") if item.strip()]
            default_value = cls.model_fields["cors_origins"].default  # type: ignore[index]
            return items or default_value
        return value

    class Config:
        env_file = str(Path(__file__).resolve().parents[1] / ".env")
        env_file_encoding = "utf-8"
        extra = "ignore"


@lru_cache
def get_settings() -> Settings:
    return Settings()
