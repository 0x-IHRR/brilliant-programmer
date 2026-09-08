import secrets
from datetime import UTC, datetime, timedelta
from email.message import EmailMessage

from sqlmodel import Session, select

from app.core.config import settings
from app.core.verification import send_email, token_hash
from app.models import PasswordReset, User


def request_password_reset(session: Session, email: str) -> None:
    user = session.exec(
        select(User).where(User.email == email).with_for_update()
        .execution_options(populate_existing=True)
    ).first()
    if not user or not user.is_active or not user.email_verified:
        session.rollback()
        return
    previous = session.get(PasswordReset, user.id)
    now = datetime.now(UTC)
    if previous and now < previous.sent_at + timedelta(seconds=60):
        session.rollback()
        return
    token = secrets.token_urlsafe(32)
    message = EmailMessage()
    message["From"] = settings.SMTP_FROM
    message["To"] = user.email
    message["Subject"] = "重置登录密码"
    message.set_content(
        f"请自行设置新密码（{settings.PASSWORD_RESET_EXPIRE_MINUTES} 分钟有效，仅一次）：\n"
        f"{settings.FRONTEND_HOST}/#reset={token}\n"
        "成功后所有设备需重新登录；仅打开链接不会修改密码。未申请请忽略。"
    )
    if not send_email(message):
        session.rollback()
        return
    row = previous or PasswordReset(user_id=user.id)
    row.email = user.email
    row.token_hash = token_hash(token)
    row.sent_at = now
    row.expires_at = now + timedelta(minutes=settings.PASSWORD_RESET_EXPIRE_MINUTES)
    session.add(row)
    session.commit()
