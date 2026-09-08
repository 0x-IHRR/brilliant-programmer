from pydantic import EmailStr, Field, PostgresDsn, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file="../.env", extra="ignore")
    API_V1_STR: str = "/api/v1"
    PROJECT_NAME: str = "我是天才程序员"
    SECRET_KEY: str = Field(min_length=32)
    DATABASE_URL: PostgresDsn
    FRONTEND_HOST: str = "http://127.0.0.1:18080"
    FIRST_SUPERUSER: EmailStr
    FIRST_SUPERUSER_PASSWORD: str = Field(min_length=12, max_length=128)
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 60

    @field_validator("DATABASE_URL", mode="before")
    @classmethod
    def driver(cls, value: str) -> str:
        return str(value).replace("postgresql://", "postgresql+psycopg://", 1)


settings = Settings()  # type: ignore
