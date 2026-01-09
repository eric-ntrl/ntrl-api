import os

from dotenv import load_dotenv
from sqlalchemy import create_engine
from sqlalchemy.orm import declarative_base, sessionmaker, Session
from sqlalchemy.exc import SQLAlchemyError

# Load .env file (DATABASE_URL lives there)
load_dotenv()

DATABASE_URL = os.getenv("DATABASE_URL")
if not DATABASE_URL:
    raise RuntimeError("DATABASE_URL environment variable is not set")

# Railway provides postgresql:// but SQLAlchemy needs postgresql+psycopg2://
if DATABASE_URL.startswith("postgresql://"):
    DATABASE_URL = DATABASE_URL.replace("postgresql://", "postgresql+psycopg2://", 1)

# SQLAlchemy engine & session factory
engine = create_engine(
    DATABASE_URL,
    future=True,
    echo=False,  # set True if you want to see SQL in terminal
)

SessionLocal = sessionmaker(
    autocommit=False,
    autoflush=False,
    bind=engine,
    future=True,
)

Base = declarative_base()


def init_db() -> None:
    """
    Import models and create tables if they don't exist.
    Alembic is the real migration tool, but this keeps local dev sane.
    """
    from app import models  # noqa: F401

    Base.metadata.create_all(bind=engine)


def get_db():
    """
    FastAPI dependency that gives you a DB session and cleans it up after.
    """
    db: Session = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def get_system_prompt_value(db: Session, name: str) -> str | None:
    """
    Fetch the latest active system_prompt by name and return its prompt_text.
    Used for things like ADMIN_API_KEY and PIPELINE_API_KEY.
    """
    from app.models import SystemPrompt  # imported here to avoid circular imports

    try:
        prompt = (
            db.query(SystemPrompt)
            .filter(SystemPrompt.name == name, SystemPrompt.is_active.is_(True))
            .order_by(SystemPrompt.created_at.desc())
            .first()
        )
        return prompt.prompt_text if prompt else None
    except SQLAlchemyError:
        # For now just fail quietly and let caller handle the None
        return None
