"""
Central configuration, loaded from environment variables.

On Railway (or any host), set these as encrypted environment variables /
"Variables" in the platform dashboard -- never commit real values to git.
See .env.example for the full list with comments.
"""
import os
from pathlib import Path


def _bool(name: str, default: str = "false") -> bool:
    return os.getenv(name, default).strip().lower() in ("1", "true", "yes", "on")


class Settings:
    # --- Database ---
    # Railway's managed Postgres injects DATABASE_URL automatically.
    # Falls back to a local SQLite file for development without any DB server.
    DATABASE_URL: str = os.getenv(
        "DATABASE_URL", "sqlite:///./triathlon.db"
    )

    # --- Garmin Connect credentials (used by garmin_sync.py) ---
    GARMIN_EMAIL: str = os.getenv("GARMIN_EMAIL", "")
    GARMIN_PASSWORD: str = os.getenv("GARMIN_PASSWORD", "")
    # Where the cached OAuth session token is stored between syncs, so we
    # don't have to log in with the password every night (safer + more
    # reliable). On Railway, mount a persistent volume at this path.
    GARMIN_TOKEN_STORE: str = os.getenv("GARMIN_TOKEN_STORE", str(Path.home() / ".garminconnect"))
    GARMIN_SYNC_DAYS_BACK: int = int(os.getenv("GARMIN_SYNC_DAYS_BACK", "14"))

    # --- TrainingPeaks ---
    # Automated pull is EXPERIMENTAL (see trainingpeaks_sync.py docstring).
    # Disabled by default -- manual entry/import is the reliable path.
    TP_AUTOMATED_SYNC_ENABLED: bool = _bool("TP_AUTOMATED_SYNC_ENABLED", "false")
    TP_COOKIE: str = os.getenv("TP_COOKIE", "")  # Production_tpAuth cookie value, if using automated pull

    # --- App / security ---
    APP_SECRET: str = os.getenv("APP_SECRET", "change-me-please")
    # Simple single-user login for the dashboard (this is a personal tool).
    APP_USERNAME: str = os.getenv("APP_USERNAME", "athlete")
    APP_PASSWORD: str = os.getenv("APP_PASSWORD", "change-me-please")

    # --- Strength plan generation ---
    STRENGTH_SESSIONS_PER_WEEK: int = int(os.getenv("STRENGTH_SESSIONS_PER_WEEK", "3"))
    # Optional: Anthropic API key, only needed if you want the backend itself
    # to call Claude for the weekly AI-review step. If left blank, the
    # /strength-plan/review endpoint just returns the rule-based draft and
    # you can paste it into a Claude conversation manually instead.
    ANTHROPIC_API_KEY: str = os.getenv("ANTHROPIC_API_KEY", "")


settings = Settings()
