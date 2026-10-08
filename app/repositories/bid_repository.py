import uuid
from datetime import datetime, timezone
from pymongo.client_session import ClientSession
from pymongo.errors import DuplicateKeyError
from typing import Optional
from pymongo.asynchronous.client_session import AsyncClientSession

from app.models.bid import Bid

class BidRepository:
    def __init__(self, db):
        self.collection = db['bids']

    async def create_bid(
        self,
        bid: Bid,
        session: AsyncClientSession,
    ) -> Bid:

        doc = bid.model_dump(by_alias=True)

        if not doc.get("_id"):
            doc["_id"] = str(uuid.uuid4())
        doc["created_at"] = datetime.now(timezone.utc)

        try:
            await self.collection.insert_one(doc, session=session)

        except DuplicateKeyError:
            raise

        return Bid.model_validate(doc)



    async def get_bid_by_id(
            self,
            bid_id: str,
            session: Optional[AsyncClientSession] = None
    ) -> Optional[Bid]:

        doc = await self.collection.find_one({"_id": bid_id}, session=session)
        if not doc:
            return None

        return Bid.model_validate(doc)