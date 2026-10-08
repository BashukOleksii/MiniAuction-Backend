from datetime import datetime
from uuid import UUID
from pydantic import BaseModel, Field, StrictInt


class CreateBidRequest(BaseModel):
    """
    Тіло запиту на створення ставки (B1, B2).
    Сума строго int > 0, request_id обов'язковий.
    """
    amount: StrictInt = Field(
        ...,
        gt=0,
        description="Сума ставки, строго ціле додатне число",
        examples=[100],
    )
    request_id: UUID = Field(
        ...,
        description="Клієнтський ключ ідемпотентності",
        examples=["f8bbf94f-1c4b-4eea-929a-5304d9675d87"],
    )


class BidResponse(BaseModel):
    """
    Безпечна відповідь з інформацією про прийняту ставку (B10).
    """
    id: str = Field(..., description="UUID ставки")
    auction_id: str
    bidder_id: str
    amount: int
    sequence: int
    created_at: datetime

    model_config = {
        "from_attributes": True,
        "populate_by_name": True,
    }