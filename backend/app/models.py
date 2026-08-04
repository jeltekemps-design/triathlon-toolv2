from datetime import datetime, date as date_type

from sqlalchemy import (
    Column, Integer, String, Float, Boolean, Date, DateTime, Text, JSON, ForeignKey
)
from sqlalchemy.orm import relationship

from .database import Base


class Activity(Base):
    """A completed workout as recorded by the Garmin watch."""
    __tablename__ = "activities"

    id = Column(Integer, primary_key=True)
    external_id = Column(String, unique=True, index=True)  # Garmin activity ID
    date = Column(Date, index=True, nullable=False)
    start_time = Column(DateTime)
    sport = Column(String)  # running, cycling, swimming, strength_training, ...
    name = Column(String)
    duration_sec = Column(Float)
    distance_m = Column(Float)
    # Garmin's API returns these as floats (e.g. avg_hr: 127.0), not whole
    # integers -- these were originally declared as Integer, which SQLite
    # (used for local dev) silently tolerates but Postgres correctly
    # rejects ("invalid input syntax for type integer"). Float matches what
    # Garmin actually sends.
    avg_hr = Column(Float)
    max_hr = Column(Float)
    avg_pace_sec_per_km = Column(Float)
    avg_power_w = Column(Float)
    calories = Column(Float)
    training_effect_aerobic = Column(Float)
    training_effect_anaerobic = Column(Float)
    perceived_load = Column(Float)  # Garmin's "training load" for this activity
    raw_json = Column(JSON)  # full payload kept for anything not modeled above

    matched_planned_workout_id = Column(Integer, ForeignKey("planned_workouts.id"), nullable=True)


class DailyWellness(Base):
    """Daily recovery/health snapshot from Garmin (one row per calendar day)."""
    __tablename__ = "daily_wellness"

    id = Column(Integer, primary_key=True)
    date = Column(Date, unique=True, index=True, nullable=False)
    # Same reasoning as Activity above: Garmin's wellness endpoints can also
    # return floats for these fields, so these are Float rather than
    # Integer to avoid the same class of Postgres insert failure.
    resting_hr = Column(Float)
    hrv_ms = Column(Float)
    sleep_score = Column(Float)
    sleep_duration_sec = Column(Float)
    body_battery_high = Column(Float)
    body_battery_low = Column(Float)
    stress_avg = Column(Float)
    vo2max_running = Column(Float)
    vo2max_cycling = Column(Float)
    training_status = Column(String)  # e.g. "PRODUCTIVE", "OVERREACHING", "RECOVERY"
    acute_load = Column(Float)   # 7-day training load
    chronic_load = Column(Float)  # 28-day training load
    raw_json = Column(JSON)


class PlannedWorkout(Base):
    """A prescribed endurance session from TrainingPeaks (or entered manually)."""
    __tablename__ = "planned_workouts"

    id = Column(Integer, primary_key=True)
    external_id = Column(String, unique=True, index=True, nullable=True)  # null for manually entered
    date = Column(Date, index=True, nullable=False)
    sport = Column(String)
    title = Column(String)
    description = Column(Text)
    structured_steps = Column(JSON)  # list of {name, duration, target, ...} if available
    planned_duration_sec = Column(Float)
    planned_tss = Column(Float)
    source = Column(String, default="manual")  # "trainingpeaks" | "manual" | "import"
    completed = Column(Boolean, default=False)
    completed_at = Column(DateTime, nullable=True)
    activity_id = Column(Integer, ForeignKey("activities.id"), nullable=True)


class StrengthSession(Base):
    """An AI/rule-generated complementary strength session."""
    __tablename__ = "strength_sessions"

    id = Column(Integer, primary_key=True)
    date = Column(Date, index=True, nullable=False)
    focus = Column(String)  # "upper" | "lower" | "core" | "full_body" | "mobility"
    exercises = Column(JSON)  # list of {name, sets, reps, load_guidance, notes}
    duration_min = Column(Integer)
    rationale = Column(Text)  # why this session/load was chosen this week
    generation_method = Column(String, default="rule_based")  # "rule_based" | "ai_reviewed"
    completed = Column(Boolean, default=False)
    completed_at = Column(DateTime, nullable=True)
    skipped_reason = Column(String, nullable=True)


class SyncLog(Base):
    __tablename__ = "sync_logs"

    id = Column(Integer, primary_key=True)
    source = Column(String)  # "garmin" | "trainingpeaks" | "strength_plan"
    started_at = Column(DateTime, default=datetime.utcnow)
    finished_at = Column(DateTime, nullable=True)
    status = Column(String, default="running")  # "running" | "success" | "error"
    message = Column(Text, nullable=True)
