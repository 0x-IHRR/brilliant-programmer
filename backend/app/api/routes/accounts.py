import secrets
import uuid
from datetime import timedelta
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from fastapi.security import OAuth2PasswordRequestForm
from sqlalchemy.exc import IntegrityError
from sqlmodel import col, select

from app.api.deps import (
    CurrentUser,
    SessionDep,
    get_current_active_superuser,
    get_training_user,
)
from app.api.rate_limit import protect_auth
from app.core.config import settings
from app.core.security import create_access_token, get_password_hash, verify_password
from app.models import (
    Invitation,
    InvitationPublic,
    Token,
    User,
    UserPublic,
    UserRegister,
)

router = APIRouter(tags=["accounts"])
admin = [Depends(get_current_active_superuser)]
# Same password-hash work for unknown accounts; no credential is accepted by this hash.
DUMMY_HASH = get_password_hash(secrets.token_urlsafe(32))


@router.post("/login/access-token", dependencies=[Depends(protect_auth)])
def login(
    session: SessionDep, form: Annotated[OAuth2PasswordRequestForm, Depends()]
) -> Token:
    user = session.exec(select(User).where(User.email == form.username.lower())).first()
    valid, _ = verify_password(
        form.password, user.hashed_password if user else DUMMY_HASH
    )
    if not user or not valid or not user.is_active:
        raise HTTPException(401, "邮箱或密码错误")
    return Token(
        access_token=create_access_token(
            user.id, timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)
        )
    )


@router.get("/users/me", response_model=UserPublic)
def me(user: CurrentUser) -> User:
    return user


@router.get("/training/access", dependencies=[Depends(get_training_user)])
def training_access() -> dict[str, bool]:
    return {"allowed": True}


@router.post(
    "/users/signup",
    response_model=UserPublic,
    status_code=201,
    dependencies=[Depends(protect_auth)],
)
def register(session: SessionDep, body: UserRegister) -> User:
    # Hash before locking; account insert and one-use transition share one transaction.
    hashed = get_password_hash(body.password)
    invitation = session.exec(
        select(Invitation)
        .where(Invitation.code == body.invitation_code)
        .with_for_update()
    ).first()
    if not invitation or invitation.status != "unused":
        raise HTTPException(409, "邀请码无效、已使用或已作废")
    user = User(email=body.email, hashed_password=hashed)
    invitation.status = "used"
    session.add(user)
    session.add(invitation)
    try:
        session.commit()
    except IntegrityError:
        session.rollback()
        raise HTTPException(
            409, "注册未完成：请使用其他邮箱或登录已有账号；邀请码未因本次失败消耗"
        )
    session.refresh(user)
    return user


@router.post(
    "/invitations", dependencies=admin, response_model=InvitationPublic, status_code=201
)
def generate_invitation(session: SessionDep) -> Invitation:
    invitation = Invitation(code=secrets.token_urlsafe(32))
    session.add(invitation)
    session.commit()
    session.refresh(invitation)
    return invitation


@router.get("/invitations", dependencies=admin, response_model=list[InvitationPublic])
def invitations(session: SessionDep, offset: int = 0) -> list[Invitation]:
    return list(
        session.exec(
            select(Invitation)
            .order_by(col(Invitation.created_at).desc())
            .offset(max(0, offset))
            .limit(100)
        ).all()
    )


@router.post(
    "/invitations/{invitation_id}/revoke",
    dependencies=admin,
    response_model=InvitationPublic,
)
def revoke(invitation_id: uuid.UUID, session: SessionDep) -> Invitation:
    invitation = session.exec(
        select(Invitation).where(Invitation.id == invitation_id).with_for_update()
    ).first()
    if not invitation:
        raise HTTPException(404, "邀请不存在")
    if invitation.status == "used":
        raise HTTPException(409, "邀请码已使用，不能作废；注册账号保持不变")
    invitation.status = "revoked"
    session.add(invitation)
    session.commit()
    session.refresh(invitation)
    return invitation
