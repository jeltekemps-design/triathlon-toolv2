"""
Entry point for the nightly scheduled job (Railway "Cron Schedule" points at
this: `python run_sync.py`). Also fine to run manually any time you want an
immediate refresh instead of waiting for the schedule / clicking "Sync now"
in the dashboard.

Order: Garmin sync -> TrainingPeaks sync (if enabled) -> regenerate this
week's + next week's strength plan from the freshest data.
"""
from datetime import date, timedelta

from app.database import SessionLocal, init_db
from app.garmin_sync import sync_garmin
from app.trainingpeaks_sync import sync_trainingpeaks_experimental
from app.strength_plan import generate_weekly_strength_plan, call_ai_review
from app.config import settings


def _this_monday(d: date) -> date:
    return d - timedelta(days=d.weekday())


def main():
    init_db()
    db = SessionLocal()
    try:
        garmin_log = sync_garmin(db)
        print(f"[garmin] {garmin_log.status}: {garmin_log.message}")

        if settings.TP_AUTOMATED_SYNC_ENABLED:
            tp_log = sync_trainingpeaks_experimental(db)
            print(f"[trainingpeaks] {tp_log.status}: {tp_log.message}")
        else:
            print("[trainingpeaks] automated sync disabled -- using manual/imported entries only")

        today = date.today()
        for week_start in (_this_monday(today), _this_monday(today) + timedelta(days=7)):
            draft = generate_weekly_strength_plan(db, week_start)
            call_ai_review(db, week_start, draft)
            print(f"[strength-plan] generated {len(draft)} sessions for week of {week_start}")
    finally:
        db.close()


if __name__ == "__main__":
    main()
