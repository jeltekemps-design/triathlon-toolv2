from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, declarative_base

from .config import settings


def _normalize_db_url(url: str) -> str:
    # Railway (and most hosts) hand back a plain postgresql:// URL, which
    # SQLAlchemy defaults to the psycopg2 driver for. psycopg2 needs the
    # native libpq shared library, which isn't reliably present in every
    # build image -- switch to the pure-Python pg8000 driver instead, which
    # needs no system library at all and so can't hit this class of error.
    if url.startswith("postgresql://"):
        return url.replace("postgresql://", "postgresql+pg8000://", 1)
    if url.startswith("postgres://"):
        return url.replace("postgres://", "postgresql+pg8000://", 1)
    return url


DB_URL = _normalize_db_url(settings.DATABASE_URL)
connect_args = {"check_same_thread": False} if DB_URL.startswith("sqlite") else {}
engine = create_engine(DB_URL, connect_args=connect_args)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def init_db():
    # Import models so they're registered on Base before create_all runs.
    from . import models  # noqa: F401
    Base.metadata.create_all(bind=engine)
