from collections.abc import Generator
from typing import Annotated

import jwt
from fastapi import Depends, HTTPException
from fastapi.security import OAuth2PasswordBearer
from pydantic import ValidationError
from sqlmodel import Session

from app.core.config import settings
from app.core.db import engine
from app.core.security import ALGORITHM
from app.models import TokenPayload, User


def get_db() -> Generator[Session]:
    with Session(engine) as session:
        yield session


SessionDep = Annotated[Session, Depends(get_db)]
TokenDep = Annotated[
    str, Depends(OAuth2PasswordBearer(tokenUrl="/api/v1/login/access-token"))
]


def get_current_user(session: SessionDep, token: TokenDep) -> User:
    try:
        payload = TokenPayload(
            **jwt.decode(token, settings.SECRET_KEY, algorithms=[ALGORITHM])
        )
    except jwt.InvalidTokenError, ValidationError:
        raise HTTPException(401, "请重新登录")
    user = session.get(User, payload.sub)
    if not user or not user.is_active:
        raise HTTPException(401, "请重新登录")
    return user


CurrentUser = Annotated[User, Depends(get_current_user)]


def get_current_active_superuser(user: CurrentUser) -> User:
    if not user.is_superuser:
        raise HTTPException(403, "仅管理员可以管理邀请")
    return user


def get_training_user(user: CurrentUser) -> User:
    if not user.email_verified:
        raise HTTPException(403, "请先验证邮箱")
    return user
