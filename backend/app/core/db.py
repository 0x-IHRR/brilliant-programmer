from sqlmodel import Session, create_engine, select

from app.core.config import settings
from app.core.security import get_password_hash
from app.models import User

engine = create_engine(str(settings.DATABASE_URL), pool_pre_ping=True)


def init_db(session: Session) -> None:
    email = settings.FIRST_SUPERUSER.lower()
    if not session.exec(select(User).where(User.email == email)).first():
        session.add(
            User(
                email=email,
                hashed_password=get_password_hash(settings.FIRST_SUPERUSER_PASSWORD),
                is_superuser=True,
            )
        )
        session.commit()
