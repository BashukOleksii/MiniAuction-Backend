from typing import Annotated

from fastapi import APIRouter, Depends, Query, status

from app.api.dependencies import (
    get_auction_finalization_service,
    get_auction_state_service,
    get_optional_current_user,
)
from app.models.user import User
from app.schemas.auction_result import AuctionResultResponse
from app.schemas.auction_state import AuctionStateResponse
from app.schemas.bid import BidResponse
from app.services.auction_finalization_service import AuctionFinalizationService
from app.services.auction_state_service import AuctionStateService

router = APIRouter(prefix="/auctions", tags=["auction-state"])


@router.get(
    "/{auction_id}/state",
    response_model=AuctionStateResponse,
    status_code=status.HTTP_200_OK,
    summary="Отримати актуальний стан лота для polling (D2)",
)
async def get_auction_state(
    auction_id: str,
    optional_user: Annotated[User | None, Depends(get_optional_current_user)] = None,
    state_service: Annotated[AuctionStateService, Depends(get_auction_state_service)] = None,
) -> AuctionStateResponse:
    """
    Легкий статус лота для polling раз на ~3 секунди.
    """
    return await state_service.get_auction_state(
        auction_id=auction_id,
        optional_user=optional_user,
    )


@router.get(
    "/{auction_id}/bids/recent",
    response_model=list[BidResponse],
    status_code=status.HTTP_200_OK,
    summary="Коротка свіжа історія ставок (F1)",
)
async def get_recent_bids(
    auction_id: str,
    state_service: Annotated[AuctionStateService, Depends(get_auction_state_service)],
    limit: Annotated[int, Query(ge=1, le=20)] = 10,
    after_sequence: Annotated[int | None, Query(ge=1)] = None,
) -> list[BidResponse]:
    """
    Повертає останні ставки за sequence DESC.
    """
    bids = await state_service.get_recent_bids(
        auction_id=auction_id,
        limit=limit,
        after_sequence=after_sequence,
    )
    return [
        BidResponse(
            id=str(getattr(b, "id", None) or getattr(b, "_id", "")),
            auction_id=b.auction_id,
            bidder_id=b.bidder_id,
            amount=b.amount,
            sequence=getattr(b, "sequence", None),
            created_at=b.created_at,
        )
        for b in bids
    ]


@router.get(
    "/{auction_id}/result",
    response_model=AuctionResultResponse,
    status_code=status.HTTP_200_OK,
    summary="Підсумковий результат завершеного лота (E4)",
)
async def get_auction_result(
    auction_id: str,
    finalization_service: Annotated[
        AuctionFinalizationService, Depends(get_auction_finalization_service)
    ],
) -> AuctionResultResponse:
    """
    Публічний результат після закінчення часу лота.
    """
    return await finalization_service.get_auction_result(auction_id=auction_id)