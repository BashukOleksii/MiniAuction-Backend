from datetime import datetime
from typing import Any, Optional
from pymongo import ReturnDocument


class AuctionFinalizationRepository:
    """
    Репозиторій для атомарної матеріалізації завершення аукціону (E2).
    """

    def __init__(self, db: Any) -> None:
        self.auctions_collection = db["auctions"]

    async def finalize_auction_atomically(
        self,
        auction_id: str,
        winner_id: Optional[str],
        now: datetime,
    ) -> Optional[dict[str, Any]]:
        """
        Умовне атомарне оновлення лота:
        - status == 'active'
        - ends_at <= now
        Встановлює status='finished', winner_id, finalized_at.
        Повертає оновлений документ або None (якщо вже фіналізовано або час ще не настав).
        """
        filter_query = {
            "_id": auction_id,
            "status": "active",
            "ends_at": {"$lte": now},
        }

        update_query = {
            "$set": {
                "status": "finished",
                "winner_id": winner_id,
                "finalized_at": now,
                "updated_at": now,
            }
        }

        return await self.auctions_collection.find_one_and_update(
            filter_query,
            update_query,
            return_document=ReturnDocument.AFTER,
        )