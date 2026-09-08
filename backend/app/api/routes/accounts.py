import secrets
import uuid
from datetime import UTC, datetime, timedelta
from typing import Annotated

import jwt
from fastapi import APIRouter, Depends, HTTPException
from fastapi.security import OAuth2PasswordRequestForm
from sqlalchemy import delete
from sqlalchemy.exc import IntegrityError
from sqlmodel import col, select

from app.api.deps import (
    CurrentUser,
    SessionDep,
    TokenDep,
    get_current_active_superuser,
    get_training_user,
)
from app.api.rate_limit import protect_auth
from app.core.config import settings
from app.core.password_reset import request_password_reset
from app.core.security import (
    ALGORITHM,
    create_access_token,
    get_password_hash,
    verify_password,
)
from app.core.verification import send_verification, token_hash
from app.models import (
    EmailVerification,
    Invitation,
    InvitationPublic,
    LoginSession,
    PasswordReset,
    PasswordResetEmail,
    PasswordResetRequest,
    RegistrationPublic,
    Token,
    TokenPayload,
    User,
    UserPublic,
    UserRegister,
    VerificationRequest,
)

router = APIRouter(tags=["accounts"])
admin = [Depends(get_current_active_superuser)]
# Same password-hash work for unknown accounts; no credential is accepted by this hash.
DUMMY_HASH = get_password_hash(secrets.token_urlsafe(32))


@router.post("/login/access-token", dependencies=[Depends(protect_auth)])
def login(
    session: SessionDep, form: Annotated[OAuth2PasswordRequestForm, Depends()]
) -> Token:
    # Password verification and session creation serialize with password reset.
    user = session.exec(
        select(User).where(User.email == form.username.lower()).with_for_update()
        .execution_options(populate_existing=True)
    ).first()
    valid, _ = verify_password(
        form.password, user.hashed_password if user else DUMMY_HASH
    )
    if not user or not valid or not user.is_active:
        raise HTTPException(401, "邮箱或密码错误")
    expires = timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)
    login_session = LoginSession(
        user_id=user.id, expires_at=datetime.now(UTC) + expires
    )
    session.add(login_session)
    session.commit()
    return Token(access_token=create_access_token(user.id, expires, login_session.id))


@router.get("/users/me", response_model=UserPublic)
def me(user: CurrentUser) -> User:
    return user


@router.get("/training/access", dependencies=[Depends(get_training_user)])
def training_access() -> dict[str, bool]:
    return {"allowed": True}


@router.post(
    "/users/signup",
    response_model=RegistrationPublic,
    status_code=201,
    dependencies=[Depends(protect_auth)],
)
def register(session: SessionDep, body: UserRegister) -> RegistrationPublic:
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
    sent = send_verification(session, user.id)
    return RegistrationPublic(
        **UserPublic.model_validate(user).model_dump(), verification_sent=sent
    )


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


@router.post("/login/logout")
def logout(user: CurrentUser, token: TokenDep, session: SessionDep) -> dict[str, str]:
    payload = TokenPayload(
        **jwt.decode(token, settings.SECRET_KEY, algorithms=[ALGORITHM])
    )
    row = session.get(LoginSession, payload.jti)
    if row and row.user_id == user.id:
        session.delete(row)
        session.commit()
    return {"message": "已退出当前设备"}


@router.post("/users/me/verification-email", dependencies=[Depends(protect_auth)])
def resend_verification(user: CurrentUser, session: SessionDep) -> dict[str, str]:
    if not send_verification(session, user.id):
        raise HTTPException(503, "验证邮件发送失败，账号已保留，请稍后重发")
    return {
        "message": "邮箱已验证"
        if user.email_verified
        else "验证邮件已交给本地收件服务，请查看邮箱"
    }


@router.post(
    "/users/me/verify-email",
    response_model=UserPublic,
    dependencies=[Depends(protect_auth)],
)
def verify_email(
    body: VerificationRequest, user: CurrentUser, session: SessionDep
) -> User:
    # Lock in the same order as resend. A bearer link cannot verify another session's account.
    user = session.exec(
        select(User)
        .where(User.id == user.id)
        .with_for_update()
        .execution_options(populate_existing=True)
    ).one()
    row = session.get(EmailVerification, user.id)
    if (
        not row
        or row.email != user.email
        or row.expires_at <= datetime.now(UTC)
        or not secrets.compare_digest(row.token_hash, token_hash(body.token))
    ):
        raise HTTPException(400, "验证链接无效、过期或已使用，请登录对应邮箱账号并重发")
    user.email_verified = True
    session.add(user)
    session.delete(row)
    session.commit()
    session.refresh(user)
    return user


@router.post("/password-reset/request", status_code=202, dependencies=[Depends(protect_auth)])
def password_reset_email(body: PasswordResetEmail, session: SessionDep) -> dict[str, str]:
    request_password_reset(session, body.email.lower())
    return {"message": "请求已受理。如该邮箱对应已验证的有效账号，将尝试发送重置链接；未收到请一分钟后重试。此响应不确认账号存在或邮件送达。"}


@router.post("/password-reset/confirm", dependencies=[Depends(protect_auth)])
def reset_password(body: PasswordResetRequest, session: SessionDep) -> dict[str, str]:
    digest = token_hash(body.token)
    user_id = session.exec(select(PasswordReset.user_id).where(PasswordReset.token_hash == digest)).first()
    if not user_id:
        raise HTTPException(400, "重置链接无效、过期或已使用，请重新申请")
    # Same lock as login/resend; refresh after waiting to observe any winning reset.
    user = session.exec(select(User).where(User.id == user_id).with_for_update()
        .execution_options(populate_existing=True)).one()
    row = session.get(PasswordReset, user_id, populate_existing=True)
    if (not user.is_active or not user.email_verified or not row
        or row.email != user.email or row.expires_at <= datetime.now(UTC)
        or not secrets.compare_digest(row.token_hash, digest)):
        raise HTTPException(400, "重置链接无效、过期或已使用，请重新申请")
    user.hashed_password = get_password_hash(body.password)
    session.add(user)
    session.delete(row)
    session.exec(delete(LoginSession).where(col(LoginSession.user_id) == user.id))
    session.commit()
    return {"message": "密码已重置，所有设备均需使用新密码重新登录。"}
