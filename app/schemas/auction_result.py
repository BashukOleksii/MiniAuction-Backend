from datetime import datetime
from typing import Optional
from pydantic import BaseModel, Field


class AuctionResultResponse(BaseModel):
    """
    Публічний підсумок завершеного лота (E4).
    """
    auction_id: str
    status: str = Field(default="finished")
    winner_id: Optional[str] = None
    winning_bid: Optional[int] = None
    total_bids: int
    ended_at: datetime

    model_config = {
        "populate_by_name": True,
    }