import uuid

from sqlmodel import Field, SQLModel


class RandomPreference(SQLModel, table=True):
    __tablename__ = "random_preference"
    user_id: uuid.UUID = Field(primary_key=True, foreign_key="user.id")
    version: uuid.UUID = Field(default_factory=uuid.uuid4)
    mode: str = "recommended"
