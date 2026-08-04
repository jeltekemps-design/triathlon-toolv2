"""
TrainingPeaks integration.

IMPORTANT — read before relying on this:
Unlike Garmin, TrainingPeaks has no mature, widely-used unofficial library
(nothing at the stability level of `garminconnect`). The community options
that exist (e.g. `tp-cli`, Playwright-based scrapers) are all young,
reverse-engineered against TrainingPeaks' private web endpoints, and can
break without notice. Because of that, this module is built around THREE
tiers, in order of reliability:

  1. Manual entry (`add_manual_workout`) -- you or your coach's plan is
     typed/pasted into the dashboard. Always works, zero fragility.
  2. CSV/ICS import (`import_ics`) -- if your TrainingPeaks account exposes
     a per-workout or calendar export, upload it and this parses it. Medium
     reliability -- depends on what TrainingPeaks includes in the export
     (title/date/duration for sure; structured intervals often missing).
  3. Experimental automated pull (`sync_trainingpeaks_experimental`) -- OFF
     by default (TP_AUTOMATED_SYNC_ENABLED=false). If you choose to enable
     it, you provide your own `Production_tpAuth` cookie value (grab it from
     your browser's dev tools after logging into app.trainingpeaks.com) via
     the TP_COOKIE setting, and this calls TrainingPeaks' internal workout
     API the same way tools like `tp-cli` do. Expect this cookie to expire
     periodically and need manual refreshing, and expect the endpoint shape
     to occasionally change.

Recommendation: start with tier 1/2 and only add tier 3 once the rest of the
tool is working the way you want -- it's the part most likely to need
maintenance over time.
"""
from datetime import datetime, date as date_type
import re

import requests
from sqlalchemy.orm import Session

from .config import settings
from .models import PlannedWorkout, SyncLog


def add_manual_workout(db: Session, workout_date: date_type, sport: str, title: str,
                        description: str = "", planned_duration_sec: float | None = None,
                        planned_tss: float | None = None) -> PlannedWorkout:
    pw = PlannedWorkout(
        date=workout_date,
        sport=sport,
        title=title,
        description=description,
        planned_duration_sec=planned_duration_sec,
        planned_tss=planned_tss,
        source="manual",
    )
    db.add(pw)
    db.commit()
    db.refresh(pw)
    return pw


def import_ics(db: Session, ics_text: str) -> list[PlannedWorkout]:
    """Very small ICS parser covering the VEVENT fields TrainingPeaks
    typically exports (SUMMARY, DTSTART, DESCRIPTION). Good enough for
    title/date/duration; won't recover structured interval data."""
    created = []
    events = ics_text.split("BEGIN:VEVENT")[1:]
    for block in events:
        summary = re.search(r"SUMMARY:(.*)", block)
        dtstart = re.search(r"DTSTART[^:]*:(\d{8})", block)
        description = re.search(r"DESCRIPTION:(.*)", block)
        if not dtstart:
            continue
        d = datetime.strptime(dtstart.group(1), "%Y%m%d").date()
        title = summary.group(1).strip() if summary else "Planned workout"
        desc = description.group(1).strip() if description else ""
        # Skip if we've already imported an event with this exact title+date
        existing = db.query(PlannedWorkout).filter_by(date=d, title=title).first()
        if existing:
            continue
        pw = PlannedWorkout(date=d, sport=_guess_sport(title), title=title,
                             description=desc, source="import")
        db.add(pw)
        created.append(pw)
    db.commit()
    return created


def _guess_sport(title: str) -> str:
    t = title.lower()
    if any(k in t for k in ("swim",)):
        return "swimming"
    if any(k in t for k in ("bike", "ride", "cycl")):
        return "cycling"
    if any(k in t for k in ("run", "brick")):
        return "running"
    if any(k in t for k in ("strength", "gym", "core")):
        return "strength_training"
    return "other"


def sync_trainingpeaks_experimental(db: Session, days_ahead: int = 14) -> SyncLog:
    """Experimental automated pull -- see module docstring. Disabled unless
    TP_AUTOMATED_SYNC_ENABLED=true and TP_COOKIE is set."""
    log = SyncLog(source="trainingpeaks")
    db.add(log)
    db.commit()
    db.refresh(log)

    if not settings.TP_AUTOMATED_SYNC_ENABLED or not settings.TP_COOKIE:
        log.status = "error"
        log.message = "Automated TrainingPeaks sync is disabled. Set TP_AUTOMATED_SYNC_ENABLED=true and TP_COOKIE, or use manual entry / ICS import instead."
        log.finished_at = datetime.utcnow()
        db.add(log)
        db.commit()
        return log

    try:
        # NOTE: this endpoint is TrainingPeaks' private web API and is not
        # officially documented or supported -- it mirrors the approach used
        # by community tools like `tp-cli`. It WILL need adjustment if
        # TrainingPeaks changes their frontend. Treat this function as a
        # starting point to adapt, not a guaranteed-working integration.
        headers = {"Cookie": f"Production_tpAuth={settings.TP_COOKIE}"}
        resp = requests.get(
            "https://tpapi.trainingpeaks.com/fitness/v6/athletes/me/workouts",
            headers=headers, timeout=20,
        )
        resp.raise_for_status()
        workouts = resp.json()

        count = 0
        for w in workouts:
            external_id = str(w.get("workoutId") or w.get("id"))
            existing = db.query(PlannedWorkout).filter_by(external_id=external_id).first()
            if existing:
                continue
            db.add(PlannedWorkout(
                external_id=external_id,
                date=datetime.fromisoformat(w["workoutDay"]).date(),
                sport=w.get("workoutTypeValueId"),
                title=w.get("title"),
                description=w.get("description"),
                structured_steps=w.get("structure"),
                planned_duration_sec=w.get("totalTimePlanned", 0) * 3600 if w.get("totalTimePlanned") else None,
                planned_tss=w.get("tssPlanned"),
                source="trainingpeaks",
            ))
            count += 1
        db.commit()
        log.status = "success"
        log.message = f"Imported {count} new planned workouts"
    except Exception as e:
        db.rollback()
        log.status = "error"
        log.message = f"Automated pull failed (expected occasionally -- this is an unofficial endpoint): {e}"
    finally:
        log.finished_at = datetime.utcnow()
        db.add(log)
        db.commit()

    return log
