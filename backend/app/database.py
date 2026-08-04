from sqlalchemy import create_engine, text
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
    _widen_garmin_numeric_columns()


# Columns that were originally declared as Integer but actually receive
# floats from Garmin's API (e.g. avg_hr: 127.0), which Postgres rejects
# outright ("invalid input syntax for type integer") even though SQLite
# silently tolerated it during local dev. create_all() only creates tables
# that don't exist yet -- it never alters an existing table's column type --
# so any database created before this fix still has the old (broken) INTEGER
# columns. This runs a one-time-per-startup, idempotent widening so existing
# deployments self-heal without anyone needing to touch the database by hand.
_GARMIN_FLOAT_COLUMNS = [
    ("activities", "avg_hr"),
    ("activities", "max_hr"),
    ("activities", "avg_power_w"),
    ("activities", "calories"),
    ("daily_wellness", "resting_hr"),
    ("daily_wellness", "sleep_score"),
    ("daily_wellness", "body_battery_high"),
    ("daily_wellness", "body_battery_low"),
    ("daily_wellness", "stress_avg"),
]


def _widen_garmin_numeric_columns():
    if engine.dialect.name != "postgresql":
        return  # SQLite has no strict column typing, so this doesn't apply.
    with engine.begin() as conn:
        for table, column in _GARMIN_FLOAT_COLUMNS:
            conn.execute(text(
                f'ALTER TABLE {table} ALTER COLUMN "{column}" TYPE DOUBLE PRECISION '
                f'USING "{column}"::double precision'
            ))
