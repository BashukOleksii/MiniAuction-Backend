from datetime import datetime
from typing import Optional
from pydantic import BaseModel, Field


class AuctionStateResponse(BaseModel):
    """
    Легка відповідь для опитування (polling) кожні ~3 секунди (D2).
    """
    auction_id: str
    status: str = Field(..., description="Ефективний статус: draft, scheduled, active, finished, cancelled")
    current_price: int
    minimum_bid: Optional[int] = Field(None, description="Мінімальна наступна ставка або null для finished")
    bid_count: int
    leader_id: Optional[str] = None
    ends_at: datetime
    server_time: datetime
    remaining_seconds: int
    is_winning: bool = False

    model_config = {
        "populate_by_name": True,
    }