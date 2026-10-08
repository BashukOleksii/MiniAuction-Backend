from datetime import datetime

from pydantic import Field

from app.models.common import MongoModel, utc_now


class Bid(MongoModel):
    auction_id: str
    bidder_id: str
    amount: int = Field(gt=0)
    created_at: datetime = Field(default_factory=utc_now)
