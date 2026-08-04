"""
Garmin Connect sync.

Uses the community-maintained `garminconnect` library (pip install garminconnect),
which as of 2026 is the best-maintained option for pulling personal Garmin
data (no official self-serve API exists for individual consumer accounts).

Notes on reliability:
- Auth mimics the Garmin Connect mobile app login flow and supports MFA via
  a callback. The resulting OAuth token is cached to GARMIN_TOKEN_STORE and
  auto-refreshes, so a nightly scheduled sync normally does NOT need to send
  your password again -- this both avoids repeated-login lockout risk and
  survives short library hiccups.
- This is an unofficial, reverse-engineered client (not sanctioned by Garmin).
  Garmin has periodically changed anti-bot measures on login before; if a
  sync starts failing, the first thing to check is whether a newer
  `garminconnect` release fixes it (`pip install -U garminconnect`).
"""
from datetime import date, timedelta
from sqlalchemy.orm import Session

from .config import settings
from .models import Activity, DailyWellness, SyncLog


def _mfa_prompt():
    # In a scheduled/background job there's no human to type a code, so this
    # will only work for an interactive first-time login. Run the sync once
    # manually (e.g. `python -m app.garmin_sync`) right after enabling MFA so
    # the cached token file gets created; subsequent scheduled runs reuse it.
    return input("Garmin MFA code: ")


def _get_client():
    import garminconnect

    client = garminconnect.Garmin(
        email=settings.GARMIN_EMAIL,
        password=settings.GARMIN_PASSWORD,
        prompt_mfa=_mfa_prompt,
    )
    client.login(settings.GARMIN_TOKEN_STORE)
    return client


def _duration_to_pace(distance_m, duration_sec):
    if not distance_m or not duration_sec:
        return None
    km = distance_m / 1000.0
    return duration_sec / km if km > 0 else None


def sync_garmin(db: Session, days_back: int | None = None) -> SyncLog:
    log = SyncLog(source="garmin")
    db.add(log)
    db.commit()
    db.refresh(log)

    try:
        client = _get_client()
        days_back = days_back or settings.GARMIN_SYNC_DAYS_BACK
        today = date.today()

        for i in range(days_back):
            d = today - timedelta(days=i)
            d_iso = d.isoformat()

            # --- Activities for this day ---
            activities = client.get_activities_by_date(d_iso, d_iso) or []
            for a in activities:
                external_id = str(a.get("activityId"))
                existing = db.query(Activity).filter_by(external_id=external_id).first()
                if existing:
                    continue
                duration_sec = a.get("duration")
                distance_m = a.get("distance")
                db.add(Activity(
                    external_id=external_id,
                    date=d,
                    sport=(a.get("activityType") or {}).get("typeKey"),
                    name=a.get("activityName"),
                    duration_sec=duration_sec,
                    distance_m=distance_m,
                    avg_hr=a.get("averageHR"),
                    max_hr=a.get("maxHR"),
                    avg_pace_sec_per_km=_duration_to_pace(distance_m, duration_sec),
                    avg_power_w=a.get("avgPower"),
                    calories=a.get("calories"),
                    training_effect_aerobic=a.get("aerobicTrainingEffect"),
                    training_effect_anaerobic=a.get("anaerobicTrainingEffect"),
                    perceived_load=a.get("activityTrainingLoad"),
                    raw_json=a,
                ))

            # --- Daily wellness snapshot ---
            try:
                hr_data = client.get_heart_rates(d_iso) or {}
                sleep_data = client.get_sleep_data(d_iso) or {}
                battery = client.get_body_battery(d_iso) or []
                stress = client.get_stress_data(d_iso) or {}
                training_status = client.get_training_status(d_iso) or {}
                max_metrics = client.get_max_metrics(d_iso) or []
                hrv = client.get_hrv_data(d_iso) or {}
            except Exception:
                # Any single wellness endpoint can 404 for a day with no data;
                # don't let that kill the whole day's sync.
                hr_data, sleep_data, battery, stress, training_status, max_metrics, hrv = {}, {}, [], {}, {}, [], {}

            existing_wellness = db.query(DailyWellness).filter_by(date=d).first()
            if not existing_wellness:
                bb_values = [b.get("bodyBatteryLevel") for b in battery if isinstance(b, dict) and b.get("bodyBatteryLevel") is not None]
                vo2_running = next((m.get("value") for m in max_metrics if isinstance(m, dict) and m.get("metricType") == "VO2_MAX_RUNNING"), None)
                vo2_cycling = next((m.get("value") for m in max_metrics if isinstance(m, dict) and m.get("metricType") == "VO2_MAX_CYCLING"), None)
                db.add(DailyWellness(
                    date=d,
                    resting_hr=hr_data.get("restingHeartRate"),
                    hrv_ms=hrv.get("lastNightAvg") if isinstance(hrv, dict) else None,
                    sleep_score=(sleep_data.get("dailySleepDTO") or {}).get("sleepScores", {}).get("overall", {}).get("value") if isinstance(sleep_data, dict) else None,
                    sleep_duration_sec=(sleep_data.get("dailySleepDTO") or {}).get("sleepTimeSeconds") if isinstance(sleep_data, dict) else None,
                    body_battery_high=max(bb_values) if bb_values else None,
                    body_battery_low=min(bb_values) if bb_values else None,
                    stress_avg=stress.get("avgStressLevel") if isinstance(stress, dict) else None,
                    vo2max_running=vo2_running,
                    vo2max_cycling=vo2_cycling,
                    training_status=(training_status.get("mostRecentTrainingStatus") or {}).get("latestTrainingStatus") if isinstance(training_status, dict) else None,
                    raw_json={
                        "hr": hr_data, "sleep": sleep_data, "stress": stress,
                        "training_status": training_status, "hrv": hrv,
                    },
                ))

        db.commit()
        log.status = "success"
        log.message = f"Synced last {days_back} days"
    except Exception as e:
        db.rollback()
        log.status = "error"
        log.message = str(e)
    finally:
        from datetime import datetime
        log.finished_at = datetime.utcnow()
        db.add(log)
        db.commit()

    return log


if __name__ == "__main__":
    # Run this once interactively the first time (so you can answer an MFA
    # prompt), which caches a token for subsequent unattended scheduled runs.
    from .database import SessionLocal, init_db
    init_db()
    session = SessionLocal()
    result = sync_garmin(session)
    print(result.status, result.message)
