from pydantic import EmailStr, Field, PostgresDsn, SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file="../.env", extra="ignore", hide_input_in_errors=True)
    MODEL_ENCRYPTION_KEYS: dict[str, SecretStr] = Field(default_factory=dict)
    MODEL_ACTIVE_KEY_VERSION: str = "v1"
    API_V1_STR: str = "/api/v1"
    PROJECT_NAME: str = "我是天才程序员"
    SECRET_KEY: str = Field(min_length=32)
    DATABASE_URL: PostgresDsn
    FRONTEND_HOST: str = "http://127.0.0.1:18080"
    FIRST_SUPERUSER: EmailStr
    FIRST_SUPERUSER_PASSWORD: str = Field(min_length=12, max_length=128)
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 60
    # Defaults target local capture; external SMTP requires separate authorization.
    SMTP_HOST: str = "127.0.0.1"
    SMTP_STARTTLS: bool = False
    SMTP_USER: str | None = None
    SMTP_PASSWORD: str | None = None
    SMTP_FROM: EmailStr = "verification@example.com"
    SMTP_PORT: int = Field(default=11025, ge=1, le=65535)
    PASSWORD_RESET_EXPIRE_MINUTES: int = Field(default=30, ge=1, le=1440)
    VERIFICATION_EXPIRE_MINUTES: int = Field(default=30, ge=1, le=1440)

    @field_validator("DATABASE_URL", mode="before")
    @classmethod
    def driver(cls, value: str) -> str:
        return str(value).replace("postgresql://", "postgresql+psycopg://", 1)


settings = Settings()  # type: ignore
