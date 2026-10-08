from datetime import datetime, timezone
from pymongo.client_session import ClientSession
from pymongo.errors import DuplicateKeyError



class BidRepository:
    def __init__(self, db):
        self.collection = db['bids']

    def create_bid(self, bid: dict, session: ClientSession) -> dict:
        doc = bid.copy()
        doc["created_at"] = datetime.now(timezone.utc)

        try:
            result = self.collection.insert_one(doc, session=session)
            doc["_id"] = result.inserted_id
            return doc
        except DuplicateKeyError as exc:
            raise exc

