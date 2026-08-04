from datetime import date, datetime, timedelta

import secrets
from fastapi import FastAPI, Depends, HTTPException, status
from fastapi.staticfiles import StaticFiles
from fastapi.security import HTTPBasic, HTTPBasicCredentials
from sqlalchemy.orm import Session
from sqlalchemy import desc

from .config import settings
from .database import get_db, init_db
from . import models, schemas
from .garmin_sync import sync_garmin
from .trainingpeaks_sync import add_manual_workout, import_ics, sync_trainingpeaks_experimental
from . import strength_plan as sp

app = FastAPI(title="Triathlon Training Tool")
security = HTTPBasic()


def require_auth(credentials: HTTPBasicCredentials = Depends(security)):
    correct_user = secrets.compare_digest(credentials.username, settings.APP_USERNAME)
    correct_pass = secrets.compare_digest(credentials.password, settings.APP_PASSWORD)
    if not (correct_user and correct_pass):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid credentials",
                             headers={"WWW-Authenticate": "Basic"})
    return credentials.username


@app.on_event("startup")
def on_startup():
    init_db()


# ---------- Activities & wellness (Garmin) ----------

@app.get("/api/activities", response_model=list[schemas.ActivityOut])
def list_activities(days: int = 30, db: Session = Depends(get_db), _=Depends(require_auth)):
    since = date.today() - timedelta(days=days)
    return db.query(models.Activity).filter(models.Activity.date >= since).order_by(desc(models.Activity.date)).all()


@app.get("/api/wellness", response_model=list[schemas.WellnessOut])
def list_wellness(days: int = 30, db: Session = Depends(get_db), _=Depends(require_auth)):
    since = date.today() - timedelta(days=days)
    return db.query(models.DailyWellness).filter(models.DailyWellness.date >= since).order_by(models.DailyWellness.date).all()


@app.post("/api/sync/garmin", response_model=schemas.SyncLogOut)
def trigger_garmin_sync(days_back: int | None = None, db: Session = Depends(get_db), _=Depends(require_auth)):
    return sync_garmin(db, days_back)


# ---------- Planned workouts (TrainingPeaks / manual) ----------

@app.get("/api/planned-workouts", response_model=list[schemas.PlannedWorkoutOut])
def list_planned_workouts(days: int = 14, db: Session = Depends(get_db), _=Depends(require_auth)):
    today = date.today()
    return db.query(models.PlannedWorkout).filter(
        models.PlannedWorkout.date >= today - timedelta(days=2),
        models.PlannedWorkout.date <= today + timedelta(days=days),
    ).order_by(models.PlannedWorkout.date).all()


@app.post("/api/planned-workouts", response_model=schemas.PlannedWorkoutOut)
def create_manual_workout(body: schemas.ManualWorkoutIn, db: Session = Depends(get_db), _=Depends(require_auth)):
    return add_manual_workout(db, body.date, body.sport, body.title, body.description,
                               body.planned_duration_sec, body.planned_tss)


@app.post("/api/planned-workouts/import-ics")
def upload_ics(body: dict, db: Session = Depends(get_db), _=Depends(require_auth)):
    created = import_ics(db, body.get("ics_text", ""))
    return {"imported": len(created)}


@app.patch("/api/planned-workouts/{workout_id}/complete", response_model=schemas.PlannedWorkoutOut)
def complete_planned_workout(workout_id: int, body: schemas.CompleteIn, db: Session = Depends(get_db), _=Depends(require_auth)):
    pw = db.query(models.PlannedWorkout).get(workout_id)
    if not pw:
        raise HTTPException(404, "Not found")
    pw.completed = body.completed
    pw.completed_at = datetime.utcnow() if body.completed else None
    db.commit()
    db.refresh(pw)
    return pw


@app.post("/api/sync/trainingpeaks", response_model=schemas.SyncLogOut)
def trigger_trainingpeaks_sync(db: Session = Depends(get_db), _=Depends(require_auth)):
    return sync_trainingpeaks_experimental(db)


# ---------- Strength plan ----------

@app.get("/api/strength-sessions", response_model=list[schemas.StrengthSessionOut])
def list_strength_sessions(days: int = 14, db: Session = Depends(get_db), _=Depends(require_auth)):
    today = date.today()
    return db.query(models.StrengthSession).filter(
        models.StrengthSession.date >= today - timedelta(days=2),
        models.StrengthSession.date <= today + timedelta(days=days),
    ).order_by(models.StrengthSession.date).all()


@app.patch("/api/strength-sessions/{session_id}/complete", response_model=schemas.StrengthSessionOut)
def complete_strength_session(session_id: int, body: schemas.CompleteIn, db: Session = Depends(get_db), _=Depends(require_auth)):
    s = db.query(models.StrengthSession).get(session_id)
    if not s:
        raise HTTPException(404, "Not found")
    s.completed = body.completed
    s.completed_at = datetime.utcnow() if body.completed else None
    db.commit()
    db.refresh(s)
    return s


@app.post("/api/strength-plan/generate", response_model=list[schemas.StrengthSessionOut])
def generate_strength_plan(body: schemas.GenerateStrengthPlanIn, db: Session = Depends(get_db), _=Depends(require_auth)):
    draft = sp.generate_weekly_strength_plan(db, body.week_start, body.race_date, body.sessions_per_week)
    # Try automated AI review; if no API key configured this is a no-op and
    # the rule-based rationale stands (the ready-to-run prompt is available
    # via /api/strength-plan/review-prompt for manual use).
    sp.call_ai_review(db, body.week_start, draft)
    return draft


@app.get("/api/strength-plan/review-prompt")
def get_review_prompt(week_start: date, db: Session = Depends(get_db), _=Depends(require_auth)):
    today_week_sessions = db.query(models.StrengthSession).filter(
        models.StrengthSession.date >= week_start, models.StrengthSession.date <= week_start + timedelta(days=6)
    ).all()
    return {"prompt": sp.build_ai_review_prompt(db, week_start, today_week_sessions)}


# ---------- Sync status ----------

@app.get("/api/sync-logs", response_model=list[schemas.SyncLogOut])
def list_sync_logs(db: Session = Depends(get_db), _=Depends(require_auth)):
    return db.query(models.SyncLog).order_by(desc(models.SyncLog.started_at)).limit(20).all()


# ---------- Static frontend ----------
# Serves the dashboard SPA from ../../frontend. Mounted last so it doesn't
# shadow the /api routes above.
from pathlib import Path
   ...
   FRONTEND_DIR = Path(__file__).resolve().parent.parent / "frontend"
   app.mount("/", StaticFiles(directory=str(FRONTEND_DIR), html=True), name="frontend")
