from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator

from app.schemas.auction import AuctionResponse


class ModerationReason(BaseModel):
    model_config = ConfigDict(extra="forbid")

    reason: str = Field(min_length=10, max_length=500)

    @field_validator("reason", mode="before")
    @classmethod
    def strip_reason(cls, value: object) -> object:
        return value.strip() if isinstance(value, str) else value


class AdminUserResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    username: str
    email: EmailStr
    role: Literal["user", "admin"]
    is_active: bool
    created_at: datetime
    updated_at: datetime


class AdminUserPage(BaseModel):
    items: list[AdminUserResponse]
    page: int
    page_size: int
    total: int
    pages: int


class AdminAuctionPage(BaseModel):
    items: list[AuctionResponse]
    page: int
    page_size: int
    total: int
    pages: int


class AdminStatistics(BaseModel):
    users_total: int
    users_active: int
    users_blocked: int
    auctions_total: int
    auctions_draft: int
    auctions_scheduled: int
    auctions_active: int
    auctions_finished: int
    auctions_cancelled: int
    bids_total: int


class AdminAuditLogResponse(BaseModel):
    id: str
    actor_id: str
    action: Literal["user.block", "user.unblock", "auction.cancel"]
    target_id: str
    reason: str
    created_at: datetime


class AdminAuditPage(BaseModel):
    items: list[AdminAuditLogResponse]
    page: int
    page_size: int
    total: int
    pages: int
