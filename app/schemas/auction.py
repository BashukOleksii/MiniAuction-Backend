"""Public REST contracts for auction management (no bidding mutations)."""

from datetime import datetime
from typing import Literal

from pydantic import (
    AwareDatetime,
    BaseModel,
    ConfigDict,
    Field,
    field_validator,
    model_validator,
)

from app.models.auction import AuctionImage

AuctionViewStatus = Literal["draft", "scheduled", "active", "finished", "cancelled"]
AuctionSortField = Literal["created_at", "current_price", "ends_at", "title"]
PublicAuctionFilter = Literal["active", "scheduled", "finished"]

AUCTION_CATEGORIES = ("electronics", "clothing", "books", "collectibles", "other")


def _normalize_category(value: str) -> str:
    result = value.strip().lower()
    if result not in AUCTION_CATEGORIES:
        raise ValueError(f"Category must be one of: {', '.join(AUCTION_CATEGORIES)}")
    return result


class AuctionCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: str = Field(min_length=3, max_length=150)
    description: str = Field(default="", max_length=5000)
    category: str
    starting_price: int = Field(ge=0, strict=True)
    min_bid_step: int = Field(default=1, gt=0, strict=True)
    starts_at: AwareDatetime | None = None
    ends_at: AwareDatetime

    @field_validator("title", "description", mode="before")
    @classmethod
    def strip_text(cls, value: object) -> object:
        return value.strip() if isinstance(value, str) else value

    @field_validator("category")
    @classmethod
    def validate_category(cls, value: str) -> str:
        return _normalize_category(value)

    @model_validator(mode="after")
    def check_date_order(self):
        if self.starts_at is not None and self.ends_at <= self.starts_at:
            raise ValueError("ends_at must be after starts_at")
        return self


class AuctionUpdateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: str | None = Field(default=None, min_length=3, max_length=150)
    description: str | None = Field(default=None, max_length=5000)
    category: str | None = None
    starting_price: int | None = Field(default=None, ge=0, strict=True)
    min_bid_step: int | None = Field(default=None, gt=0, strict=True)
    starts_at: AwareDatetime | None = None
    ends_at: AwareDatetime | None = None

    @field_validator("title", "description", mode="before")
    @classmethod
    def strip_text(cls, value: object) -> object:
        return value.strip() if isinstance(value, str) else value

    @field_validator("category")
    @classmethod
    def validate_category(cls, value: str | None) -> str | None:
        return _normalize_category(value) if value is not None else None

    @model_validator(mode="after")
    def require_non_null_update(self):
        if not self.model_fields_set:
            raise ValueError("At least one field is required")
        if any(getattr(self, field) is None for field in self.model_fields_set):
            raise ValueError("Explicit null values are not allowed")
        return self


class AuctionResponse(BaseModel):
    id: str
    seller_id: str
    title: str
    description: str
    category: str
    images: list[AuctionImage]
    starting_price: int
    current_price: int
    min_bid_step: int
    starts_at: datetime
    ends_at: datetime
    status: Literal["draft", "active", "finished", "cancelled"]
    effective_status: AuctionViewStatus
    leader_id: str | None
    winner_id: str | None
    created_at: datetime
    updated_at: datetime


class AuctionPage(BaseModel):
    items: list[AuctionResponse]
    page: int
    page_size: int
    total: int
    pages: int
