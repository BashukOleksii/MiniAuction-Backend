from pymongo import ReturnDocument
from pymongo.asynchronous.database import AsyncDatabase

from app.models.auction import Auction, AuctionImage
from app.models.common import utc_now


class AuctionImageRepository:
    def __init__(self, db: AsyncDatabase):
        self.collection = db["auctions"]

    async def get_by_id(self, auction_id: str) -> Auction | None:
        document = await self.collection.find_one({"_id": auction_id})
        return Auction.model_validate(document) if document is not None else None

    async def replace_draft_images(
        self,
        *,
        auction_id: str,
        seller_id: str,
        expected_images: list[AuctionImage],
        new_images: list[AuctionImage],
    ) -> Auction | None:
        expected = [image.model_dump(mode="python") for image in expected_images]
        replacement = [image.model_dump(mode="python") for image in new_images]
        query: dict = {
            "_id": auction_id,
            "seller_id": seller_id,
            "status": "draft",
        }
        if expected:
            query["images"] = expected
        else:
            query["$or"] = [{"images": []}, {"images": {"$exists": False}}]
        document = await self.collection.find_one_and_update(
            query,
            {"$set": {"images": replacement, "updated_at": utc_now()}},
            return_document=ReturnDocument.AFTER,
        )
        return Auction.model_validate(document) if document is not None else None
