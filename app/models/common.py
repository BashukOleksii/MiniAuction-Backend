from datetime import datetime, timezone
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class MongoModel(BaseModel):
    model_config = ConfigDict(populate_by_name=True, validate_assignment=True, use_enum_values=True)

    id: str = Field(default_factory=lambda: str(uuid4()), alias="_id")
