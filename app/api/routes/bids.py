from typing import Annotated

from fastapi import APIRouter, Depends, status

from app.api.dependencies import get_bid_service, get_current_user
from app.models.user import User
from app.schemas.bid import BidResponse, CreateBidRequest
from app.services.bid_service import BidService

router = APIRouter(prefix="/auctions", tags=["bids"])


@router.post(
    "/{auction_id}/bids",
    response_model=BidResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Зробити ставку на аукціон",
)
async def place_bid(
    auction_id: str,
    bid_in: CreateBidRequest,
    current_user: Annotated[User, Depends(get_current_user)],
    bid_service: Annotated[BidService, Depends(get_bid_service)],
) -> BidResponse:
    return await bid_service.place_bid(
        auction_id=auction_id,
        bid_in=bid_in,
        current_user=current_user,
    )