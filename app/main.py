from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.routes import auctions, auth, health, users
from app.core.cloudinary import configure_cloudinary
from app.core.config import settings
from app.db.mongodb import initialize_mongodb


@asynccontextmanager
async def lifespan(app: FastAPI):
    client = await initialize_mongodb(app)
    try:
        configure_cloudinary()
        yield
    finally:
        await client.close()


app = FastAPI(title=settings.app_name, lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=False,
    allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type"],
)

app.include_router(health.router, prefix="/api/v1", tags=["Health"])
app.include_router(auctions.router, prefix="/api/v1/auctions", tags=["Auctions"])
app.include_router(auth.router, prefix="/api/v1/auth", tags=["Authentication"])
app.include_router(users.router, prefix="/api/v1/users", tags=["Users"])
app.include_router(
    auctions.my_router,
    prefix="/api/v1/users/me",
    tags=["Auctions"],
)
