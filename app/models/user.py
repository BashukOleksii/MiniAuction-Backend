from datetime import datetime
from typing import Literal

from pydantic import EmailStr, Field, field_validator

from app.models.common import MongoModel, utc_now


class User(MongoModel):
    username: str = Field(min_length=3, max_length=50)
    email: EmailStr
    password_hash: str = Field(min_length=1)
    role: Literal["user", "admin"] = "user"
    is_active: bool = True
    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)

    @field_validator("email")
    @classmethod
    def normalize_email(cls, value: str) -> str:
        return value.lower()
