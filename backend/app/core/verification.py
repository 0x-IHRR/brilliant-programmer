import hashlib
import secrets
import smtplib
import ssl
import uuid
from datetime import UTC, datetime, timedelta
from email.message import EmailMessage

from fastapi import HTTPException
from sqlmodel import Session, select

from app.core.config import settings
from app.models import EmailVerification, User


def token_hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def send_verification(session: Session, user_id: uuid.UUID) -> bool:
    # Serialize resend and verification on the account, including the first send.
    user = session.exec(
        select(User)
        .where(User.id == user_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    ).one()
    if user.email_verified:
        session.rollback()
        return True
    previous = session.get(EmailVerification, user.id)
    now = datetime.now(UTC)
    if previous and now < previous.sent_at + timedelta(seconds=60):
        session.rollback()
        raise HTTPException(
            429, "请在一分钟后重发验证邮件", headers={"Retry-After": "60"}
        )
    token = secrets.token_urlsafe(32)
    message = EmailMessage()
    message["From"] = settings.SMTP_FROM
    message["To"] = user.email
    message["Subject"] = "验证注册邮箱"
    # Fragment keeps the bearer secret out of ordinary HTTP/access logs.
    message.set_content(
        f"请登录该邮箱对应账号后验证（{settings.VERIFICATION_EXPIRE_MINUTES} 分钟有效，仅一次）：\n"
        f"{settings.FRONTEND_HOST}/#verify={token}\n"
        "没有发起注册请忽略；邮件不包含密码或邀请码。"
    )
    if not send_email(message):
        session.rollback()
        return False
    row = previous or EmailVerification(user_id=user.id)
    row.email = user.email
    row.token_hash = token_hash(token)
    row.expires_at = now + timedelta(minutes=settings.VERIFICATION_EXPIRE_MINUTES)
    row.sent_at = now
    session.add(row)
    session.commit()
    return True


def send_email(message: EmailMessage) -> bool:
    try:
        with smtplib.SMTP(settings.SMTP_HOST, settings.SMTP_PORT, timeout=5) as smtp:
            if settings.SMTP_STARTTLS:
                smtp.starttls(context=ssl.create_default_context())
            if settings.SMTP_USER and settings.SMTP_PASSWORD:
                if not settings.SMTP_STARTTLS:
                    raise smtplib.SMTPException("SMTP credentials require TLS")
                smtp.login(settings.SMTP_USER, settings.SMTP_PASSWORD)
            smtp.send_message(message)
    except OSError, smtplib.SMTPException:
        return False
    return True
