"""
Complementary strength plan generator.

Two layers, matching the "rules baseline + AI review" approach:

1. `generate_weekly_strength_plan()` -- deterministic, rule-based. Looks at
   the week's prescribed endurance plan (from TrainingPeaks/manual entries)
   and recent recovery data (from Garmin) to decide HOW MANY strength
   sessions to schedule, WHICH days, and roughly how hard, using simple
   load-management rules from sports science (acute:chronic workload ratio,
   avoiding heavy strength next to key endurance sessions, tapering strength
   volume as races approach).

2. `build_ai_review_prompt()` / `call_ai_review()` -- takes that draft plus
   the athlete's actual recent recovery trend and upcoming plan, and asks an
   LLM to sanity-check and adjust it (e.g. "drop Thursday's lower-body
   session to mobility-only, HRV dropped 15% after Wednesday's key bike").
   If ANTHROPIC_API_KEY isn't configured, `build_ai_review_prompt()` still
   returns a ready-to-paste prompt you can run manually in a Claude
   conversation -- the AI-review step doesn't require automating the API
   call to be useful.
"""
from datetime import date, timedelta
from statistics import mean

from sqlalchemy.orm import Session

from .config import settings
from .models import PlannedWorkout, DailyWellness, Activity, StrengthSession


EXERCISE_LIBRARY = {
    "upper": {
        "base":  [("Push-ups or bench press", "3x10-12", "moderate"),
                  ("Single-arm dumbbell row", "3x10 /side", "moderate"),
                  ("Overhead press", "3x8-10", "moderate"),
                  ("Band pull-aparts", "2x15", "light")],
        "build": [("Bench or push-up (weighted if possible)", "4x6-8", "harder"),
                  ("Pull-ups or lat pulldown", "4x6-8", "harder"),
                  ("Overhead press", "3x6-8", "moderate")],
        "taper": [("Push-ups", "2x10", "light"),
                  ("Band rows", "2x12", "light")],
    },
    "lower": {
        "base":  [("Goblet squat", "3x10-12", "moderate"),
                  ("Romanian deadlift", "3x10", "moderate"),
                  ("Walking lunges", "3x10 /leg", "moderate"),
                  ("Calf raises", "3x15", "light")],
        "build": [("Back squat or leg press", "4x5-6", "harder, low reps"),
                  ("Single-leg RDL", "3x8 /leg", "moderate"),
                  ("Nordic curls or hamstring curls", "3x8", "moderate")],
        "taper": [("Bodyweight squat", "2x12", "light"),
                  ("Calf raises", "2x15", "light")],
    },
    "core": {
        "base":  [("Plank", "3x45-60s", "moderate"),
                  ("Pallof press", "3x10 /side", "moderate"),
                  ("Dead bug", "3x10 /side", "light"),
                  ("Side plank", "2x30-45s /side", "moderate")],
        "build": [("Weighted plank", "3x45s", "moderate"),
                  ("Hanging leg raise", "3x8-10", "moderate"),
                  ("Pallof press", "3x10 /side", "moderate")],
        "taper": [("Plank", "2x30s", "light"),
                  ("Dead bug", "2x10 /side", "light")],
    },
    "full_body": {
        "base":  [("Goblet squat", "3x10", "moderate"),
                  ("Push-ups", "3x10", "moderate"),
                  ("Single-arm row", "3x10 /side", "moderate"),
                  ("Plank", "2x45s", "moderate")],
        "build": [("Squat", "3x6-8", "harder"),
                  ("Bench/push-up", "3x6-8", "harder"),
                  ("Pallof press", "2x10 /side", "moderate")],
        "taper": [("Bodyweight circuit", "2 rounds", "light")],
    },
    "mobility": {
        "base":  [("Hip flexor + 90/90 mobility flow", "10 min", "very light"),
                  ("Thoracic rotations", "2x10 /side", "very light"),
                  ("Ankle mobility", "5 min", "very light")],
        "build": [("Hip + ankle mobility flow", "10 min", "very light")],
        "taper": [("Full-body mobility flow", "10-15 min", "very light")],
    },
}

# Which focuses to rotate through depending on how many sessions/week.
ROTATIONS = {
    1: ["full_body"],
    2: ["upper_lower_combo", "core"],  # handled specially below
    3: ["upper", "lower", "core"],
    4: ["upper", "lower", "core", "full_body"],
}


def _phase_for_week(week_start: date, race_date: date | None) -> str:
    if not race_date:
        return "base"
    days_out = (race_date - week_start).days
    if days_out < 0:
        return "base"
    if days_out <= 6:
        return "taper"  # race week -- minimal/no new strength load
    if days_out <= 21:
        return "taper" if days_out <= 10 else "build"
    return "base"


def _acute_chronic_ratio(db: Session, as_of: date) -> float | None:
    """Rolling 7-day load vs 28-day average load, using Garmin's per-activity
    perceived_load where available. >1.3 is a commonly used caution
    threshold for elevated injury/overreaching risk."""
    acute_start = as_of - timedelta(days=7)
    chronic_start = as_of - timedelta(days=28)

    acute_loads = [a.perceived_load for a in db.query(Activity)
                   .filter(Activity.date >= acute_start, Activity.date <= as_of)
                   if a.perceived_load]
    chronic_loads = [a.perceived_load for a in db.query(Activity)
                      .filter(Activity.date >= chronic_start, Activity.date <= as_of)
                      if a.perceived_load]

    if not acute_loads or not chronic_loads:
        return None

    acute_avg = sum(acute_loads) / 7.0
    chronic_avg = sum(chronic_loads) / 28.0
    if chronic_avg == 0:
        return None
    return acute_avg / chronic_avg


def _week_planned_load(db: Session, week_start: date) -> dict[date, float]:
    """Planned endurance load (TSS if available, else duration in minutes as
    a proxy) per day for the week, used to find the easiest days."""
    week_end = week_start + timedelta(days=6)
    workouts = db.query(PlannedWorkout).filter(
        PlannedWorkout.date >= week_start, PlannedWorkout.date <= week_end
    ).all()
    loads = {week_start + timedelta(days=i): 0.0 for i in range(7)}
    for w in workouts:
        proxy = w.planned_tss or ((w.planned_duration_sec or 0) / 60.0)
        loads[w.date] = loads.get(w.date, 0.0) + proxy
    return loads


def generate_weekly_strength_plan(db: Session, week_start: date,
                                   race_date: date | None = None,
                                   sessions_per_week: int | None = None) -> list[StrengthSession]:
    """Rule-based draft for one week. Deletes any existing non-completed
    generated sessions for that week first so re-running is idempotent."""
    sessions_per_week = sessions_per_week or settings.STRENGTH_SESSIONS_PER_WEEK
    phase = _phase_for_week(week_start, race_date)
    ratio = _acute_chronic_ratio(db, week_start)

    # Load-management guardrail: trim volume when acute:chronic ratio is high,
    # or during taper/race week, regardless of the configured default.
    effective_sessions = sessions_per_week
    reason_bits = [f"Phase: {phase}."]
    if phase == "taper":
        effective_sessions = min(effective_sessions, 1)
        reason_bits.append("Taper/race week -- strength volume cut to near-zero, mobility only.")
    elif ratio is not None and ratio > 1.3:
        effective_sessions = max(1, effective_sessions - 1)
        reason_bits.append(f"Acute:chronic training load ratio is {ratio:.2f} (>1.3) -- trimming one strength session to protect recovery.")
    elif ratio is not None:
        reason_bits.append(f"Acute:chronic training load ratio is {ratio:.2f} -- within normal range.")
    else:
        reason_bits.append("Not enough Garmin history yet to compute load ratio -- using default volume.")

    daily_loads = _week_planned_load(db, week_start)
    # Find the single highest-load day (the key/long session) to avoid
    # scheduling heavy strength immediately before/after it.
    hardest_day = max(daily_loads, key=daily_loads.get) if any(daily_loads.values()) else None
    blocked_days = set()
    if hardest_day:
        blocked_days = {hardest_day - timedelta(days=1), hardest_day, hardest_day + timedelta(days=1)}

    candidate_days = sorted(
        [d for d in daily_loads if d not in blocked_days],
        key=lambda d: daily_loads[d],
    )
    if len(candidate_days) < effective_sessions:
        # Not enough "safe" days -- allow reuse of blocked days as a last resort.
        candidate_days = sorted(daily_loads, key=lambda d: daily_loads[d])
    chosen_days = sorted(candidate_days[:effective_sessions])

    if phase == "taper":
        focuses = ["mobility"] * effective_sessions
    else:
        focuses = ROTATIONS.get(effective_sessions, ["full_body"] * effective_sessions)
        # expand the shorthand 2-session rotation
        if effective_sessions == 2:
            focuses = ["full_body", "core"]

    # Clear previous non-completed auto-generated sessions for this week so
    # regenerating (e.g. after a load update) doesn't create duplicates.
    week_end = week_start + timedelta(days=6)
    db.query(StrengthSession).filter(
        StrengthSession.date >= week_start, StrengthSession.date <= week_end,
        StrengthSession.completed == False,  # noqa: E712
    ).delete()

    created = []
    lib_phase = phase if phase in ("base", "build", "taper") else "base"
    for d, focus in zip(chosen_days, focuses):
        exercises = [
            {"name": name, "prescription": rx, "intensity": intensity}
            for name, rx, intensity in EXERCISE_LIBRARY[focus][lib_phase]
        ]
        rationale = " ".join(reason_bits)
        if hardest_day:
            rationale += f" Avoided scheduling next to {hardest_day.isoformat()} (this week's biggest endurance session)."
        session = StrengthSession(
            date=d, focus=focus, exercises=exercises,
            duration_min=45 if lib_phase != "taper" else 15,
            rationale=rationale, generation_method="rule_based",
        )
        db.add(session)
        created.append(session)

    db.commit()
    for s in created:
        db.refresh(s)
    return created


def build_ai_review_prompt(db: Session, week_start: date, draft: list[StrengthSession]) -> str:
    """Assembles a prompt with the rule-based draft + recent recovery trend +
    upcoming endurance plan, ready to send to an LLM (or paste into a Claude
    chat) for a human-judgment sanity check the rules can't fully capture."""
    week_end = week_start + timedelta(days=6)
    wellness = db.query(DailyWellness).filter(
        DailyWellness.date >= week_start - timedelta(days=7), DailyWellness.date <= week_start
    ).order_by(DailyWellness.date).all()
    upcoming = db.query(PlannedWorkout).filter(
        PlannedWorkout.date >= week_start, PlannedWorkout.date <= week_end
    ).order_by(PlannedWorkout.date).all()

    wellness_lines = "\n".join(
        f"- {w.date}: sleep_score={w.sleep_score}, body_battery_low={w.body_battery_low}, "
        f"resting_hr={w.resting_hr}, hrv={w.hrv_ms}, training_status={w.training_status}"
        for w in wellness
    ) or "(no Garmin wellness data synced yet for this period)"

    plan_lines = "\n".join(
        f"- {p.date} ({p.sport}): {p.title}, planned_duration={p.planned_duration_sec}, planned_tss={p.planned_tss}"
        for p in upcoming
    ) or "(no endurance plan synced yet for this week)"

    draft_lines = "\n".join(
        f"- {s.date} [{s.focus}]: " + ", ".join(f"{e['name']} {e['prescription']}" for e in s.exercises)
        for s in draft
    )

    return f"""You are reviewing a rule-generated complementary strength plan for a triathlete,
to check it doesn't overload them alongside their endurance training.

Recent recovery data (last 7 days):
{wellness_lines}

This week's prescribed endurance plan:
{plan_lines}

Rule-based draft strength plan for the same week:
{draft_lines}

Please: (1) flag anything that looks like it risks overloading the athlete given the
recovery trend above, (2) suggest specific adjustments (swap a session to mobility,
move a day, reduce load) if warranted, or confirm the draft looks appropriately balanced,
and (3) give a one-paragraph rationale suitable for showing the athlete in the app."""


def call_ai_review(db: Session, week_start: date, draft: list[StrengthSession]) -> str | None:
    """Optional: if ANTHROPIC_API_KEY is set, actually calls Claude to get
    the review text back and stores it on each session's rationale. Returns
    None (and leaves the rule-based rationale as-is) if no key is configured
    -- in that case, use build_ai_review_prompt() and run it manually."""
    if not settings.ANTHROPIC_API_KEY:
        return None
    try:
        import anthropic
    except ImportError:
        return None

    client = anthropic.Anthropic(api_key=settings.ANTHROPIC_API_KEY)
    prompt = build_ai_review_prompt(db, week_start, draft)
    resp = client.messages.create(
        model="claude-sonnet-4-5",
        max_tokens=1024,
        messages=[{"role": "user", "content": prompt}],
    )
    review_text = "".join(block.text for block in resp.content if hasattr(block, "text"))

    for s in draft:
        s.rationale = s.rationale + "\n\nAI review: " + review_text
        s.generation_method = "ai_reviewed"
        db.add(s)
    db.commit()
    return review_text
