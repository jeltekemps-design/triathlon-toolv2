# Triathlon Training Dashboard

A personal tool that pulls your actual Garmin training/recovery data, your
coach's prescribed plan from TrainingPeaks, and generates a complementary
strength plan that adapts to your load — all in one dashboard you can check
off from your phone.


## What it does

- **Garmin sync**: nightly (or on-demand) pull of activities, sleep, HRV,
  body battery, resting HR, training status and VO2max via the
  `garminconnect` library.
- **TrainingPeaks**: your coach's plan comes in either by manual entry, by
  pasting/uploading a `.ics` calendar export, or (optional, experimental) an
  automated pull. See `backend/app/trainingpeaks_sync.py` for why automated
  TrainingPeaks access is the least reliable piece of this tool and is off
  by default.
- **Strength plan**: a rule-based generator picks how many sessions per
  week, which days (avoiding your key/long endurance sessions), and how
  hard, based on your acute:chronic training-load ratio and proximity to
  race day — then an optional AI-review step (Claude) sanity-checks the
  draft against your actual recent recovery trend.
- **Dashboard**: Today / This week / Insights (charts) / Add-Import tabs,
  with checkboxes to mark workouts and strength sessions done.

## Why "cloud-hosted" needs a few manual steps from you

Garmin and TrainingPeaks don't offer a self-serve public API for individual
athletes, so this reaches your data the same way community tools do: by
logging in with your own credentials. That means your credentials need to
live somewhere as encrypted secrets, and I can't create a hosting account or
enter payment details on your behalf — so the one-time setup below is
something you do yourself (15-20 minutes), then it runs unattended.

## Recommended host: Railway

Based on 2026 research into Render / Fly.io / Railway, **Railway** is the
best fit for this specific tool: native cron-job scheduling, no cold-start
sleep (so the dashboard opens instantly), simple GitHub-connected deploys,
one-click Postgres, and easy secret management. Expect roughly **$5-10/month**
(Hobby plan, light usage). Render is a reasonable alternative if you prefer
it, but its free tier sleeps after 15 minutes idle and cron jobs are a
separate paid add-on.

## One-time setup

1. **Put this code in a GitHub repo.**
   ```
   cd triathlon-tool
   git init
   git add .
   git commit -m "Initial triathlon dashboard"
   ```
   Create a new (private) repo on GitHub and push this to it.

2. **Create a Railway account** at railway.app (GitHub login is easiest),
   then "New Project" -> "Deploy from GitHub repo" -> select your repo.
   Set the **root directory** to `backend` in the service settings (Railway
   needs to know `requirements.txt`/`Procfile` live there).

3. **Add a Postgres database**: in the same Railway project, "+ New" ->
   "Database" -> "PostgreSQL". Railway automatically injects `DATABASE_URL`
   into your web service's environment — you don't need to set it by hand.

4. **Add a persistent volume** for the Garmin token cache (so the nightly
   sync doesn't need your password every time): in the service's Settings ->
   Volumes, add a volume mounted at `/data`, and set the environment
   variable `GARMIN_TOKEN_STORE=/data/.garminconnect`.

5. **Set environment variables** (Settings -> Variables) using
   `backend/.env.example` as the checklist:
   - `GARMIN_EMAIL`, `GARMIN_PASSWORD` — your real Garmin Connect login.
   - `APP_USERNAME`, `APP_PASSWORD` — whatever you want to log into *this*
     dashboard with (this is separate from your Garmin/TP passwords).
   - `STRENGTH_SESSIONS_PER_WEEK` — default 3, change if you want.
   - `ANTHROPIC_API_KEY` — optional; only needed if you want the backend to
     automatically call Claude for the weekly AI-review step. If you leave
     this blank, use the "Generate" button in the dashboard, which still
     produces the rule-based plan, and copy the review prompt from
     `/api/strength-plan/review-prompt` into a Claude conversation manually
     whenever you want the extra sanity-check.
   - Leave `TP_AUTOMATED_SYNC_ENABLED=false` unless you've read
     `trainingpeaks_sync.py` and want to try the experimental cookie-based
     pull — otherwise just use the manual-entry form or the `.ics` import in
     the "Add / Import" tab for your coach's plan.

6. **First Garmin login (handles 2FA if you have it on)**: Railway's cron
   job runs unattended, so the very first login (which may prompt for an
   MFA code) needs to happen once interactively. Easiest way: run it locally
   first —
   ```
   cd backend
   python -m venv venv && source venv/bin/activate
   pip install -r requirements.txt
   export GARMIN_EMAIL=... GARMIN_PASSWORD=... GARMIN_TOKEN_STORE=./garmin_tokens
   python -m app.garmin_sync
   ```
   then upload the resulting token folder to the Railway volume (Railway's
   dashboard lets you use their CLI, `railway run`, to copy files in), or
   simply trigger the first sync from the deployed app's Settings and
   answer the MFA prompt via Railway's log/shell if it appears. After the
   first successful login, the cached token refreshes on its own.

7. **Add the nightly Cron job**: in Railway, add a new service in the same
   project using the same repo/root directory, but set its "Cron Schedule"
   (e.g. `0 4 * * *` for 4am) and its start command to:
   ```
   python run_sync.py
   ```
   This pulls Garmin (and TrainingPeaks if enabled), then regenerates the
   current and next week's strength plan from the freshest data.

8. **Open your dashboard** at the URL Railway gives your web service, log in
   with the `APP_USERNAME`/`APP_PASSWORD` you set, and click "Sync now" once
   to pull your recent history immediately instead of waiting for the
   nightly job.

## Local development (no Railway needed)

```
cd backend
python -m venv venv && source venv/bin/activate
pip install -r requirements.txt
export DATABASE_URL="sqlite:///./triathlon.db"
export APP_USERNAME=athlete APP_PASSWORD=devpass
uvicorn app.main:app --reload
```
Open http://localhost:8000 and log in with `athlete` / `devpass`. Everything
works against the local SQLite file, including manual workout entry and
strength-plan generation — you only need real Garmin/TrainingPeaks
credentials once you're ready to sync real data.

## Known limitations (so nothing surprises you)

- **Garmin sync** relies on an unofficial, reverse-engineered client. It's
  actively maintained and handles MFA, but Garmin has changed its
  anti-bot measures before — if a sync starts failing, first try
  `pip install -U garminconnect` and redeploy.
- **TrainingPeaks** has no equivalent mature library. Manual entry and
  `.ics` import are the reliable path; the automated pull is genuinely
  experimental and disabled by default.
- **This is a single-user tool**: one login, one athlete. Not built for
  multiple users/coaches.
- Data storage is minimal (a few years of daily rows for one person) —
  Railway's smallest Postgres plan is overkill, cost stays low.
