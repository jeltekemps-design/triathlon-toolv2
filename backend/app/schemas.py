from datetime import date, datetime
from typing import Optional, Any
from pydantic import BaseModel


class ActivityOut(BaseModel):
    id: int
    date: date
    sport: Optional[str] = None
    name: Optional[str] = None
    duration_sec: Optional[float] = None
    distance_m: Optional[float] = None
    avg_hr: Optional[int] = None
    max_hr: Optional[int] = None
    avg_pace_sec_per_km: Optional[float] = None
    avg_power_w: Optional[int] = None
    calories: Optional[int] = None
    training_effect_aerobic: Optional[float] = None
    perceived_load: Optional[float] = None

    class Config:
        from_attributes = True


class WellnessOut(BaseModel):
    date: date
    resting_hr: Optional[int] = None
    hrv_ms: Optional[float] = None
    sleep_score: Optional[int] = None
    sleep_duration_sec: Optional[float] = None
    body_battery_high: Optional[int] = None
    body_battery_low: Optional[int] = None
    stress_avg: Optional[int] = None
    vo2max_running: Optional[float] = None
    vo2max_cycling: Optional[float] = None
    training_status: Optional[str] = None

    class Config:
        from_attributes = True


class PlannedWorkoutOut(BaseModel):
    id: int
    date: date
    sport: Optional[str] = None
    title: Optional[str] = None
    description: Optional[str] = None
    structured_steps: Optional[Any] = None
    planned_duration_sec: Optional[float] = None
    planned_tss: Optional[float] = None
    source: Optional[str] = None
    completed: bool = False

    class Config:
        from_attributes = True


class ManualWorkoutIn(BaseModel):
    date: date
    sport: str
    title: str
    description: str = ""
    planned_duration_sec: Optional[float] = None
    planned_tss: Optional[float] = None


class StrengthSessionOut(BaseModel):
    id: int
    date: date
    focus: Optional[str] = None
    exercises: Optional[Any] = None
    duration_min: Optional[int] = None
    rationale: Optional[str] = None
    generation_method: Optional[str] = None
    completed: bool = False

    class Config:
        from_attributes = True


class CompleteIn(BaseModel):
    completed: bool = True


class SyncLogOut(BaseModel):
    id: int
    source: str
    started_at: datetime
    finished_at: Optional[datetime] = None
    status: str
    message: Optional[str] = None

    class Config:
        from_attributes = True


class GenerateStrengthPlanIn(BaseModel):
    week_start: date
    race_date: Optional[date] = None
    sessions_per_week: Optional[int] = None
