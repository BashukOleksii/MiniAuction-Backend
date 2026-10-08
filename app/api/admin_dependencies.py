from typing import Annotated

from fastapi import Depends, HTTPException, status

from app.api.dependencies import get_current_user
from app.models.user import User


def get_current_admin(
    current_user: Annotated[User, Depends(get_current_user)],
) -> User:
    if current_user.role != "admin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Administrator permissions required",
        )
    return current_user
