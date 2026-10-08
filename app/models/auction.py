from datetime import datetime, timezone
from enum import Enum

from pydantic import BaseModel, Field, field_validator, model_validator

from app.models.common import MongoModel, utc_now


class AuctionStatus(str, Enum):
    DRAFT = "draft"
    ACTIVE = "active"
    FINISHED = "finished"
    CANCELLED = "cancelled"


class AuctionImage(BaseModel):
    public_id: str = Field(min_length=1)
    url: str = Field(pattern=r"^https://", max_length=2048)
    is_cover: bool = False
    sort_order: int = Field(default=0, ge=0)


class Auction(MongoModel):
    seller_id: str
    title: str = Field(min_length=3, max_length=150)
    description: str = Field(default="", max_length=5000)
    category: str = Field(min_length=2, max_length=80)
    images: list[AuctionImage] = Field(default_factory=list, max_length=10)

    starting_price: int = Field(ge=0)
    current_price: int = Field(ge=0)
    min_bid_step: int = Field(default=1, gt=0)

    starts_at: datetime = Field(default_factory=utc_now)
    ends_at: datetime
    status: AuctionStatus = AuctionStatus.DRAFT
    leader_id: str | None = None
    winner_id: str | None = None

    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)

    @field_validator("starts_at", "ends_at")
    @classmethod
    def ensure_utc(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("The datetime must include timezone information")
        return value.astimezone(timezone.utc)

    @model_validator(mode="after")
    def validate_prices_and_times(self):
        if self.current_price < self.starting_price:
            raise ValueError("current_price cannot be below starting_price")
        if self.ends_at <= self.starts_at:
            raise ValueError("ends_at must be after starts_at")
        return self
