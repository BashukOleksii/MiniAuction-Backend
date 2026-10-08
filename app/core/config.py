from functools import lru_cache
from typing import Literal

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    app_name: str = "Mini Auction API"
    app_env: Literal["development", "test", "production"] = "development"

    mongodb_uri: SecretStr
    mongodb_db_name: str = "mini_auction"

    cloudinary_cloud_name: str
    cloudinary_api_key: str
    cloudinary_api_secret: SecretStr

    jwt_secret_key: SecretStr
    jwt_algorithm: str = "HS256"
    jwt_access_token_expire_minutes: int = Field(default=30, gt=0)


@lru_cache

def get_settings() -> Settings:
    return Settings()


settings = get_settings()
