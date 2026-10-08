import cloudinary

from app.core.config import settings


def configure_cloudinary() -> None:
    cloudinary.config(
        cloud_name=settings.cloudinary_cloud_name,
        api_key=settings.cloudinary_api_key,
        api_secret=settings.cloudinary_api_secret.get_secret_value(),
        secure=True,
    )
