from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.api.routes import auctions, health
from app.core.cloudinary import configure_cloudinary
from app.core.config import settings
from app.db.mongodb import initialize_mongodb


@asynccontextmanager
async def lifespan(app: FastAPI):
    # One MongoDB client per application lifecycle.
    client = await initialize_mongodb(app)
    try:
        configure_cloudinary()
        yield
    finally:
        await client.close()


app = FastAPI(title=settings.app_name, lifespan=lifespan)
app.include_router(health.router, prefix="/api/v1", tags=["Health"])
app.include_router(auctions.router, prefix="/api/v1/auctions", tags=["Auctions"])
