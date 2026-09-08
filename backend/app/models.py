import uuid
from datetime import UTC, datetime
from typing import Literal

from pydantic import EmailStr, field_validator
from sqlalchemy import BigInteger, CheckConstraint, Column, DateTime
from sqlmodel import Field, SQLModel


class UserBase(SQLModel):
    email: EmailStr = Field(unique=True, index=True, max_length=255)
    is_active: bool = True
    is_superuser: bool = False
    email_verified: bool = False
    level: str = "小白程序员"


class User(UserBase, table=True):
    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    hashed_password: str


class UserPublic(UserBase):
    id: uuid.UUID


class UserRegister(SQLModel):
    email: EmailStr = Field(max_length=255)
    password: str = Field(min_length=12, max_length=128)
    invitation_code: str = Field(min_length=20, max_length=128)

    @field_validator("email")
    @classmethod
    def normalize_email(cls, value: str) -> str:
        return value.lower()


class Invitation(SQLModel, table=True):
    __table_args__ = (CheckConstraint("status IN ('unused', 'used', 'revoked')"),)
    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    code: str = Field(unique=True, index=True)
    status: str = "unused"
    created_at: datetime = Field(
        default_factory=lambda: datetime.now(UTC),
        sa_column=Column(DateTime(timezone=True), nullable=False),
    )


class InvitationPublic(SQLModel):
    id: uuid.UUID
    code: str
    status: Literal["unused", "used", "revoked"]
    created_at: datetime


class Token(SQLModel):
    access_token: str
    token_type: str = "bearer"


class TokenPayload(SQLModel):
    sub: uuid.UUID
    jti: uuid.UUID


class AuthRate(SQLModel, table=True):
    __tablename__ = "auth_rate"
    key: str = Field(primary_key=True, max_length=64)
    minute: int = Field(sa_type=BigInteger)
    count: int = Field(sa_type=BigInteger)


class LoginSession(SQLModel, table=True):
    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    user_id: uuid.UUID = Field(foreign_key="user.id", index=True)
    expires_at: datetime = Field(
        sa_column=Column(DateTime(timezone=True), nullable=False)
    )


class EmailVerification(SQLModel, table=True):
    user_id: uuid.UUID = Field(foreign_key="user.id", primary_key=True)
    email: str
    token_hash: str = Field(unique=True, index=True)
    expires_at: datetime = Field(
        sa_column=Column(DateTime(timezone=True), nullable=False)
    )
    sent_at: datetime = Field(sa_column=Column(DateTime(timezone=True), nullable=False))


class VerificationRequest(SQLModel):
    token: str = Field(min_length=43, max_length=43)


class RegistrationPublic(UserPublic):
    verification_sent: bool


class PasswordReset(SQLModel, table=True):
    user_id: uuid.UUID = Field(foreign_key="user.id", primary_key=True)
    email: str
    token_hash: str = Field(unique=True, index=True)
    expires_at: datetime = Field(sa_column=Column(DateTime(timezone=True), nullable=False))
    sent_at: datetime = Field(sa_column=Column(DateTime(timezone=True), nullable=False))


class PasswordResetEmail(SQLModel):
    model_config = {"extra": "forbid"}
    email: EmailStr = Field(max_length=255)


class PasswordResetRequest(VerificationRequest):
    model_config = {"extra": "forbid"}
    password: str = Field(min_length=12, max_length=128)
