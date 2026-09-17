#!/usr/bin/env python3
"""
Daily Garmin Connect session analyser — GCP Cloud Function version
Plan-aware training feedback for UTCT PT55 (RMB Ultra-Trail Cape Town,
Peninsula Traverse 55km, Llandudno -> Gardens RC, Fri 20 Nov 2026).
Otter African Trail Run 2026 was cancelled 2026-08-16; PT55 is now the
sole A-race. The 14-week block (Build-In -> Build -> Specificity -> Peak
-> Taper -> Race) lives in BQ `abmtest-429810.garmin_training.training_plan`,
2026-08-17 through 2026-11-22.

Pulls the latest activity, compares it against the prescribed session for
that day (type, distance, duration, elevation, HR effort), and generates
an explicit adherence verdict (ON PLAN / PARTIAL / OFF PLAN / MISSED) —
not a participation trophy. Praise is only printed when the data supports it.

Inspired by: Jason Koop (ultrarunning), Joe Friel (triathlete's bible),
             Steve Magness (science of running), Maffetone (aerobic base)
"""

import html
import json
import os
import re
import smtplib
import random
import functions_framework
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from datetime import datetime, timedelta, date
from garminconnect import Garmin
import garth
from google.cloud import secretmanager
from google.cloud import bigquery

# ── Config ───────────────────────────────────────────────────────────────────
PROJECT_ID   = "abm2020"
BQ_PROJECT   = "abmtest-429810"
BQ_DATASET   = "garmin_training"
BQ_TABLE     = f"{BQ_PROJECT}.{BQ_DATASET}.training_sessions"
BQ_PLAN      = f"{BQ_PROJECT}.{BQ_DATASET}.training_plan"
TOKEN_DIR    = "/tmp/.garth"
LT_HR        = 176
MAX_HR       = 198

# Race date: UTCT PT55 (Peninsula Traverse 55km), Llandudno -> Gardens RC.
# Otter African Trail Run 2026 was cancelled 2026-08-16 -- PT55 is now the
# sole A-race. Block runs 2026-08-17 (Build-In wk1) -> 2026-11-22 (post-race).
RACE_DATE    = date(2026, 11, 20)
PLAN_START   = date(2026, 8, 17)

# ── Secret Manager ────────────────────────────────────────────────────────────
def get_secret(secret_id):
    client = secretmanager.SecretManagerServiceClient()
    name = f"projects/{PROJECT_ID}/secrets/{secret_id}/versions/latest"
    response = client.access_secret_version(request={"name": name})
    return response.payload.data.decode("utf-8")

def update_secret(secret_id, value):
    client = secretmanager.SecretManagerServiceClient()
    parent = f"projects/{PROJECT_ID}/secrets/{secret_id}"
    if isinstance(value, str):
        value = value.encode("utf-8")
    client.add_secret_version(request={"parent": parent, "payload": {"data": value}})

# ── Auth ──────────────────────────────────────────────────────────────────────
def load_garmin_client():
    os.makedirs(TOKEN_DIR, exist_ok=True)
    oauth2 = get_secret("garmin-oauth2-token")
    oauth1 = get_secret("garmin-oauth1-token")
    with open(f"{TOKEN_DIR}/oauth2_token.json", "w") as f:
        f.write(oauth2)
    with open(f"{TOKEN_DIR}/oauth1_token.json", "w") as f:
        f.write(oauth1)
    garth.resume(TOKEN_DIR)
    client = Garmin()
    client.garth = garth.client
    return client

def save_tokens_if_refreshed():
    try:
        garth.save(TOKEN_DIR)
        with open(f"{TOKEN_DIR}/oauth2_token.json") as f:
            update_secret("garmin-oauth2-token", f.read())
        print("Tokens saved to Secret Manager")
    except Exception as e:
        print(f"Token save warning: {e}")

# ── Email ─────────────────────────────────────────────────────────────────────
def send_email(subject, markdown_body):
    """Returns True on confirmed send, False on any failure. Callers must
    check this and surface a non-200 response on False -- otherwise Cloud
    Scheduler sees a 200 and never retries a silently-dropped email (e.g.
    a rotated Gmail app password or an SMTP outage)."""
    try:
        gmail_user = get_secret("garmin-gmail-user")
        app_password = get_secret("garmin-gmail-app-password")
        recipient = gmail_user
        # NOT named `html` -- that would shadow the module-level `import html`
        # (used for escaping Garmin free text) for the rest of this function.
        html_body = markdown_to_html(markdown_body)
        msg = MIMEMultipart("alternative")
        msg["Subject"] = subject
        msg["From"]    = f"Coach Aria <{gmail_user}>"
        msg["To"]      = recipient
        msg.attach(MIMEText(markdown_body, "plain"))
        msg.attach(MIMEText(html_body, "html"))
        with smtplib.SMTP_SSL("smtp.gmail.com", 465) as smtp:
            smtp.login(gmail_user, app_password)
            smtp.sendmail(gmail_user, recipient, msg.as_string())
        print("Email sent successfully")
        return True
    except Exception as e:
        print(f"Email failed: {e}")
        return False

def markdown_to_html(md):
    lines = md.split("\n")
    html_lines = ["""
    <html><body style="font-family:-apple-system,sans-serif;max-width:600px;
    margin:0 auto;padding:20px;background:#f9f9f9;color:#222;">
    <div style="background:white;border-radius:12px;padding:24px;
    box-shadow:0 2px 8px rgba(0,0,0,0.08);">
    """]
    for line in lines:
        if line.startswith("# "):
            html_lines.append(f'<h1 style="color:#1a1a2e;font-size:20px;margin-bottom:4px">{line[2:]}</h1>')
        elif line.startswith("## "):
            html_lines.append(f'<h2 style="color:#16213e;font-size:16px;border-bottom:2px solid #e8f4f8;padding-bottom:6px;margin-top:20px">{line[3:]}</h2>')
        elif line.startswith("**") and line.endswith("**"):
            html_lines.append(f'<p style="font-weight:700;margin:8px 0">{line[2:-2]}</p>')
        elif line.startswith("- "):
            html_lines.append(f'<li style="margin:4px 0;line-height:1.5">{line[2:]}</li>')
        elif line.startswith("ADHERENCE VERDICT:"):
            # Special styling for the adherence verdict (ON PLAN / PARTIAL / OFF PLAN / MISSED / UNCONFIRMED)
            if "ON PLAN" in line:
                html_lines.append(f'<p style="color:#2d6a4f;font-weight:700;font-size:15px;margin:10px 0;padding:8px;background:#e8f5e9;border-radius:6px">{line}</p>')
            elif "PARTIAL" in line or "UNCONFIRMED" in line:
                html_lines.append(f'<p style="color:#e65100;font-weight:700;font-size:15px;margin:10px 0;padding:8px;background:#fff3e0;border-radius:6px">{line}</p>')
            elif "OFF PLAN" in line or "MISSED" in line:
                html_lines.append(f'<p style="color:#c62828;font-weight:700;font-size:15px;margin:10px 0;padding:8px;background:#ffebee;border-radius:6px">{line}</p>')
            else:
                html_lines.append(f'<p style="font-weight:700;margin:10px 0;padding:8px;background:#f5f5f5;border-radius:6px">{line}</p>')
        elif line.startswith("Effort intensity:"):
            html_lines.append(f'<p style="margin:4px 0 4px 8px;line-height:1.6;color:#333">{line}</p>')
        elif line.startswith("PLANNED:") or line.startswith("DONE:"):
            html_lines.append(f'<p style="font-family:monospace;margin:4px 0;line-height:1.6;background:#f8f9fa;padding:4px 8px;border-radius:4px">{line}</p>')
        elif any(line.startswith(e) for e in ["Status:", "Target:", "Done:"]):
            line = re.sub(r'\*\*(.+?)\*\*', r'<strong>\1</strong>', line)
            html_lines.append(f'<p style="margin:4px 0;line-height:1.6">{line}</p>')
        elif line.startswith("---"):
            html_lines.append('<hr style="border:none;border-top:1px solid #eee;margin:16px 0">')
        elif line.strip() == "":
            html_lines.append("<br>")
        else:
            line = re.sub(r'\*\*(.+?)\*\*', r'<strong>\1</strong>', line)
            if line.startswith("*") and line.endswith("*") and not line.startswith("**"):
                html_lines.append(f'<p style="font-style:italic;color:#555;margin:4px 0">{line[1:-1]}</p>')
            else:
                html_lines.append(f'<p style="margin:4px 0;line-height:1.6">{line}</p>')
    html_lines.append("</div></body></html>")
    return "\n".join(html_lines)

# ── Zones ─────────────────────────────────────────────────────────────────────
ZONES = {
    "Z1": (0,   141),
    "Z2": (141, 158),
    "Z3": (158, 167),
    "Z4": (167, 178),
    "Z5": (178, 999),
}

# Expected HR ranges per session type for effort comparison.
# Kept in sync with the session_type vocabulary in the PT55 block
# (abmtest-429810.garmin_training.training_plan). Update this dict
# whenever a new session_type is introduced in the plan, or sessions
# of that type will silently get NO effort verdict (see assess_effort_intensity).
SESSION_HR_TARGETS = {
    "easy_trail":    {"min": 120, "max": 150, "zone": "Z1-Z2"},
    "long_run":      {"min": 135, "max": 160, "zone": "Z2"},
    "threshold":     {"min": 167, "max": 178, "zone": "Z4"},
    "hill_repeats":  {"min": 160, "max": 178, "zone": "Z3-Z4"},
    "vo2max":        {"min": 175, "max": 192, "zone": "Z5"},
    "sharpener":     {"min": 165, "max": 180, "zone": "Z4-Z5"},
    "activation":    {"min": 120, "max": 145, "zone": "Z1"},
    "race":          {"min": 155, "max": 185, "zone": "Z2-Z5"},
    "recce":         {"min": 130, "max": 158, "zone": "Z2"},        # course recon -- steady, technique focus
    "downhill":      {"min": 130, "max": 165, "zone": "Z2-Z3"},     # eccentric loading -- effort is technical, not HR-defined
    "bike":          {"min": 120, "max": 150, "zone": "Z1-Z2"},     # road bike aerobic/leg-speed
    "mtb":           {"min": 130, "max": 162, "zone": "Z2-Z3"},     # more vert/technical load than road bike
}

# Category groups: which Garmin activity types plausibly satisfy which
# plan session_type. Used to catch "wrong sport entirely" (e.g. plan said
# bike, you ran) before any HR-based intensity check even runs.
RUN_SESSION_TYPES   = {"easy_trail", "long_run", "threshold", "hill_repeats", "vo2max",
                        "sharpener", "activation", "race", "recce", "downhill"}
BIKE_SESSION_TYPES  = {"bike", "mtb"}
STRENGTH_SESSION_TYPES = {"strength"}
REST_SESSION_TYPES  = {"rest"}

# Includes indoor/treadmill/street variants -- a common bad-weather
# substitution (e.g. treadmill_running for a planned outdoor easy run) is
# still the SAME SPORT and must not trip the wrong-sport gate in
# assess_adherence(). Anything not in these sets categorises as "other" and
# WILL trip that gate against a run/bike plan session (see the widened
# act_cat != plan_cat check) -- keep this list in sync with Garmin's actual
# activityType.typeKey taxonomy as new variants are seen in the wild.
GARMIN_RUN_TYPES  = {"running", "trail_running", "track_running", "ultra_run",
                      "obstacle_run", "virtual_run", "hiking",
                      "treadmill_running", "indoor_running", "street_running"}
GARMIN_BIKE_TYPES = {"road_biking", "mountain_biking", "cycling", "gravel_cycling",
                      "virtual_ride", "indoor_cycling", "cyclocross",
                      "track_cycling"}
GARMIN_STRENGTH_TYPES = {"strength_training", "indoor_cardio", "fitness_equipment"}

# INTERVAL_SESSION_TYPES and _parse_session_structure() now live in
# session_parser.py (canonical: ~/Projects/garmin/shared/session_parser.py,
# copied byte-for-byte into this directory by scripts/sync_shared_parser.sh
# before every deploy) -- training-plan-sync needs the exact same parsing
# logic to build intervals.icu's workout DSL, and two copies of a free-text
# parser drifting apart was flagged as the single most common failure mode
# in this project's history. See session_parser.py's module docstring for
# the full reasoning. Do NOT redefine either symbol here -- edit the
# canonical file, run the sync script, redeploy both functions.
from session_parser import INTERVAL_SESSION_TYPES, _parse_session_structure  # noqa: E402

# Session types excluded from fade-based verdict downgrade (Aria's ruling via
# Marco, 2026-09-16): sharpener reps are very short/sharp with full recovery
# between them -- too much rep-to-rep HR noise for a first-half-vs-second-half
# fade read to mean anything. Excluded ENTIRELY (no fade commentary at all for
# this session_type, not just no downgrade).
FADE_EXCLUDED_SESSION_TYPES = {"sharpener"}

# Decoupling significance threshold, as a % rise in the HR/output efficiency
# ratio from first-half to second-half of the work reps. Aria's calibration,
# 2026-09-16 round 2 (see domain_aria_fitness.md) -- her regression of the real
# 2026-09-16 VO2max lap data found ~10% natural rep-to-rep noise in distance
# covered even on a genuinely fade-free session; the original 10% threshold
# sat inside that noise floor. 20% gives real margin. Flat across
# threshold/vo2max/hill_repeats -- settled, not to be relitigated without new
# evidence.
DECOUPLING_THRESHOLD_PCT = 20

# Fallback vertical-equivalent factor for the output term, used ONLY when
# Garmin's own per-lap `avgGradeAdjustedSpeed` is unavailable for a session
# (see assess_interval_effort). Aria's calibration, 2026-09-16 round 2: a
# regression of 85 of Alexis's own trail sessions found the true
# cost-of-climbing curve is convex, not linear -- ~5-6x on moderate/rolling
# terrain (threshold reps), ~12-13x on steep terrain (vo2max/hill_repeats
# reps, e.g. Platteklip Gorge/Kloof Nek). A SPLIT constant, not a single
# uniform value -- deliberately, so the next person doesn't collapse this back
# into one number. `sharpener` omitted: excluded from fade entirely upstream.
GRADE_FACTOR_FALLBACK = {"threshold": 6, "vo2max": 12, "hill_repeats": 12}

def _plan_category(session_type):
    if session_type in BIKE_SESSION_TYPES: return "bike"
    if session_type in RUN_SESSION_TYPES: return "run"
    if session_type in STRENGTH_SESSION_TYPES: return "strength"
    if session_type in REST_SESSION_TYPES: return "rest"
    return "other"

def _activity_category(garmin_type):
    if garmin_type in GARMIN_BIKE_TYPES: return "bike"
    if garmin_type in GARMIN_RUN_TYPES: return "run"
    if garmin_type in GARMIN_STRENGTH_TYPES: return "strength"
    return "other"

def hr_zone(hr):
    for z, (lo, hi) in ZONES.items():
        if lo <= hr < hi:
            return z
    return "Z5"

def fmt_pace(min_per_km):
    if not min_per_km or min_per_km > 20: return "N/A"
    return f"{int(min_per_km)}:{int((min_per_km % 1) * 60):02d}/km"

def fmt_duration(minutes):
    h = int(minutes // 60)
    m = int(minutes % 60)
    return f"{h}h{m:02d}m" if h else f"{m}min"

# ── BigQuery ──────────────────────────────────────────────────────────────────
bq_client = None

def get_bq_client():
    global bq_client
    if bq_client is None:
        bq_client = bigquery.Client(project=BQ_PROJECT)
    return bq_client

def save_session_to_bq(a):
    """Write a Garmin activity to BQ via an atomic MERGE (WHEN NOT MATCHED
    THEN INSERT). The previous SELECT-then-INSERT was non-atomic: two
    overlapping instances (a Scheduler retry racing the original run, or a
    manual trigger overlapping the scheduled one) could both see "not
    present" and both insert -- duplicating the row AND duplicating the
    email. max-instances=1 on this function's deploy config is the primary
    guard against the overlap itself; this MERGE is the second, independent
    layer in case that's ever changed or bypassed."""
    client = get_bq_client()
    activity_id = a.get("activityId")
    if not activity_id:
        return
    try:
        activity_id = int(activity_id)
    except (TypeError, ValueError):
        print(f"Skipping activity with non-integer activity_id: {activity_id!r}")
        return

    dist_km = round((a.get("distance") or 0) / 1000, 2)
    dur_min = round((a.get("duration") or 0) / 60, 1)
    elev_m = round(a.get("elevationGain") or 0, 0)
    avg_hr = a.get("averageHR")
    max_hr_val = a.get("maxHR")
    avg_pace = round((a.get("duration") or 0) / 60 / ((a.get("distance") or 1) / 1000), 2) if a.get("distance") else None
    m_per_km = round(elev_m / dist_km, 1) if dist_km else 0
    zone = hr_zone(avg_hr) if avg_hr else None
    speed_kmh = 60 / avg_pace if avg_pace and avg_pace > 0 else None
    efficiency = round(avg_hr / speed_kmh, 2) if avg_hr and speed_kmh else None

    activity_name = a.get("activityName", "Unnamed")
    activity_type = (a.get("activityType") or {}).get("typeKey", "unknown")
    # Same "naive local string, interpreted as UTC" semantics as the old
    # insert_rows_json call -- TIMESTAMP(string) treats a timezone-less
    # string as UTC, same as the streaming insert API did.
    start_time_str = (a.get("startTimeLocal") or "")[:19].replace("T", " ")
    inserted_at_str = datetime.utcnow().isoformat()

    q = f"""
    MERGE `{BQ_TABLE}` T
    USING (SELECT @activity_id AS activity_id) S
    ON T.activity_id = S.activity_id
    WHEN NOT MATCHED THEN
      INSERT (activity_id, activity_name, activity_type, start_time, distance_km,
              duration_min, elevation_gain_m, avg_hr, max_hr, avg_pace_min_km,
              aerobic_training_effect, vo2max, calories, elevation_density_m_km,
              hr_zone, efficiency_index, inserted_at)
      VALUES (@activity_id, @activity_name, @activity_type, TIMESTAMP(@start_time),
              @distance_km, @duration_min, @elevation_gain_m, @avg_hr, @max_hr,
              @avg_pace_min_km, @aerobic_training_effect, @vo2max, @calories,
              @elevation_density_m_km, @hr_zone, @efficiency_index, TIMESTAMP(@inserted_at))
    """
    job_config = bigquery.QueryJobConfig(query_parameters=[
        bigquery.ScalarQueryParameter("activity_id", "INT64", activity_id),
        bigquery.ScalarQueryParameter("activity_name", "STRING", activity_name),
        bigquery.ScalarQueryParameter("activity_type", "STRING", activity_type),
        bigquery.ScalarQueryParameter("start_time", "STRING", start_time_str),
        bigquery.ScalarQueryParameter("distance_km", "FLOAT64", dist_km),
        bigquery.ScalarQueryParameter("duration_min", "FLOAT64", dur_min),
        bigquery.ScalarQueryParameter("elevation_gain_m", "FLOAT64", elev_m),
        bigquery.ScalarQueryParameter("avg_hr", "FLOAT64", avg_hr),
        bigquery.ScalarQueryParameter("max_hr", "FLOAT64", max_hr_val),
        bigquery.ScalarQueryParameter("avg_pace_min_km", "FLOAT64", avg_pace),
        bigquery.ScalarQueryParameter("aerobic_training_effect", "FLOAT64", a.get("aerobicTrainingEffect")),
        bigquery.ScalarQueryParameter("vo2max", "FLOAT64", a.get("vO2MaxValue")),
        bigquery.ScalarQueryParameter("calories", "FLOAT64", a.get("calories")),
        bigquery.ScalarQueryParameter("elevation_density_m_km", "FLOAT64", m_per_km),
        bigquery.ScalarQueryParameter("hr_zone", "STRING", zone),
        bigquery.ScalarQueryParameter("efficiency_index", "FLOAT64", efficiency),
        bigquery.ScalarQueryParameter("inserted_at", "STRING", inserted_at_str),
    ])
    result_job = client.query(q, job_config=job_config)
    result_job.result()
    if result_job.num_dml_affected_rows:
        print(f"Saved activity {activity_id} to BQ (MERGE inserted {result_job.num_dml_affected_rows} row)")
    else:
        print(f"Activity {activity_id} already in BQ, skipping")

# ── Plan queries ─────────────────────────────────────────────────────────────

def get_todays_plan(today_date):
    """Query BQ for the planned session on the given date. Returns dict or None.
    Despite the name, this is called with any date (see garmin_daily_feedback,
    which keys the adherence comparison to the ACTIVITY's own date, not
    necessarily today) -- kept generic on purpose."""
    client = get_bq_client()
    q = f"""
    SELECT plan_date, week_number, phase, day_of_week, session_type, session_name,
           target_km, target_vert_m, target_duration_min, target_hr_zone,
           target_hr_max, target_rpe, week_target_km, week_target_vert,
           description, effort_description, is_key_session
    FROM `{BQ_PLAN}`
    WHERE plan_date = @plan_date
    LIMIT 1
    """
    job_config = bigquery.QueryJobConfig(
        query_parameters=[bigquery.ScalarQueryParameter("plan_date", "DATE", today_date)]
    )
    rows = list(client.query(q, job_config=job_config).result())
    if not rows:
        return None
    r = rows[0]
    return {
        "plan_date": r.plan_date,
        "week_number": r.week_number,
        "phase": r.phase,
        "day_of_week": r.day_of_week,
        "session_type": r.session_type,
        "session_name": r.session_name,
        "target_km": r.target_km,
        "target_vert_m": r.target_vert_m,
        "target_duration_min": r.target_duration_min,
        "target_hr_zone": r.target_hr_zone,
        "target_hr_max": r.target_hr_max,
        "target_rpe": r.target_rpe,
        "week_target_km": r.week_target_km,
        "week_target_vert": r.week_target_vert,
        "description": r.description,
        "effort_description": r.effort_description,
        "is_key_session": r.is_key_session,
    }


def get_tomorrows_plan(today_date):
    """Query BQ for tomorrow's planned session."""
    tomorrow = today_date + timedelta(days=1)
    return get_todays_plan(tomorrow)


def get_week_progress(today_date):
    """Compare actual sessions this week vs planned targets.
    Week runs Mon-Sun, matching the plan's day_of_week layout."""
    client = get_bq_client()

    # Find the plan week that contains today
    q_plan = f"""
    SELECT week_number, phase, week_target_km, week_target_vert,
           MIN(plan_date) as week_start, MAX(plan_date) as week_end,
           COUNTIF(session_type NOT IN ('rest', 'strength')) as planned_run_sessions,
           COUNT(*) as planned_total_sessions
    FROM `{BQ_PLAN}`
    WHERE plan_date <= @today_date
      AND plan_date >= DATE_SUB(@today_date, INTERVAL 6 DAY)
    GROUP BY week_number, phase, week_target_km, week_target_vert
    ORDER BY week_number DESC
    LIMIT 1
    """
    plan_job_config = bigquery.QueryJobConfig(
        query_parameters=[bigquery.ScalarQueryParameter("today_date", "DATE", today_date)]
    )
    plan_rows = list(client.query(q_plan, job_config=plan_job_config).result())
    if not plan_rows:
        return None

    pr = plan_rows[0]
    week_start = pr.week_start
    week_end = pr.week_end

    # Get actual sessions this week from training_sessions
    q_actual = f"""
    SELECT COALESCE(SUM(distance_km), 0) as total_km,
           COALESCE(SUM(elevation_gain_m), 0) as total_vert,
           COUNT(*) as session_count
    FROM `{BQ_TABLE}`
    WHERE DATE(start_time) >= @week_start
      AND DATE(start_time) <= @today_date
    """
    actual_job_config = bigquery.QueryJobConfig(
        query_parameters=[
            bigquery.ScalarQueryParameter("week_start", "DATE", week_start),
            bigquery.ScalarQueryParameter("today_date", "DATE", today_date),
        ]
    )
    actual_rows = list(client.query(q_actual, job_config=actual_job_config).result())
    ar = actual_rows[0]

    target_km = pr.week_target_km or 0
    target_vert = pr.week_target_vert or 0
    actual_km = float(ar.total_km or 0)
    actual_vert = float(ar.total_vert or 0)

    # Days elapsed in the week (for pace calculation)
    days_elapsed = (today_date - week_start).days + 1
    days_total = (week_end - week_start).days + 1
    pct_week_elapsed = days_elapsed / max(days_total, 1)

    km_pct = (actual_km / target_km * 100) if target_km > 0 else 0
    vert_pct = (actual_vert / target_vert * 100) if target_vert > 0 else 0

    # Determine on-track status
    expected_km_pct = pct_week_elapsed * 100
    if km_pct >= expected_km_pct - 10:
        status = "on track"
    elif km_pct >= expected_km_pct - 25:
        status = "slightly behind"
    else:
        status = "behind"

    if km_pct > expected_km_pct + 15:
        status = "ahead"

    return {
        "week_number": pr.week_number,
        "phase": pr.phase,
        "target_km": target_km,
        "target_vert": target_vert,
        "actual_km": actual_km,
        "actual_vert": actual_vert,
        "planned_sessions": pr.planned_run_sessions,
        "actual_sessions": int(ar.session_count or 0),
        "km_pct": km_pct,
        "vert_pct": vert_pct,
        "status": status,
        "days_elapsed": days_elapsed,
        "days_total": days_total,
    }


def get_phase_status(today_date):
    """Week-by-week compliance within the current phase."""
    client = get_bq_client()

    # First get today's phase
    q_phase = f"""
    SELECT phase FROM `{BQ_PLAN}`
    WHERE plan_date = @today_date
    LIMIT 1
    """
    phase_job_config = bigquery.QueryJobConfig(
        query_parameters=[bigquery.ScalarQueryParameter("today_date", "DATE", today_date)]
    )
    phase_rows = list(client.query(q_phase, job_config=phase_job_config).result())
    if not phase_rows:
        return None
    current_phase = phase_rows[0].phase

    # Get all weeks in this phase
    q_weeks = f"""
    SELECT week_number, week_target_km, week_target_vert,
           MIN(plan_date) as week_start, MAX(plan_date) as week_end
    FROM `{BQ_PLAN}`
    WHERE phase = @phase
    GROUP BY week_number, week_target_km, week_target_vert
    ORDER BY week_number
    """
    weeks_job_config = bigquery.QueryJobConfig(
        query_parameters=[bigquery.ScalarQueryParameter("phase", "STRING", current_phase)]
    )
    week_rows = list(client.query(q_weeks, job_config=weeks_job_config).result())

    weeks_in_phase = []
    for wr in week_rows:
        # Only include weeks up to today
        if wr.week_start > today_date:
            continue

        q_actual = f"""
        SELECT COALESCE(SUM(distance_km), 0) as total_km,
               COALESCE(SUM(elevation_gain_m), 0) as total_vert,
               COUNT(*) as sessions
        FROM `{BQ_TABLE}`
        WHERE DATE(start_time) >= @week_start
          AND DATE(start_time) <= @week_end
        """
        wk_job_config = bigquery.QueryJobConfig(
            query_parameters=[
                bigquery.ScalarQueryParameter("week_start", "DATE", wr.week_start),
                bigquery.ScalarQueryParameter("week_end", "DATE", wr.week_end),
            ]
        )
        ar = list(client.query(q_actual, job_config=wk_job_config).result())[0]

        target_km = wr.week_target_km or 0
        actual_km = float(ar.total_km or 0)
        compliance = (actual_km / target_km * 100) if target_km > 0 else 0

        weeks_in_phase.append({
            "week_number": wr.week_number,
            "target_km": target_km,
            "actual_km": actual_km,
            "compliance_pct": compliance,
            "sessions": int(ar.sessions or 0),
        })

    if not weeks_in_phase:
        return None

    avg_compliance = sum(w["compliance_pct"] for w in weeks_in_phase) / len(weeks_in_phase)

    total_weeks_in_phase = len(week_rows)
    completed_weeks = len(weeks_in_phase)

    return {
        "phase": current_phase,
        "weeks": weeks_in_phase,
        "avg_compliance": avg_compliance,
        "completed_weeks": completed_weeks,
        "total_weeks": total_weeks_in_phase,
    }


_total_weeks_cache = None

def get_total_weeks():
    """Total weeks in the current plan block, read from BQ so this never
    goes stale again when the plan is revised or replaced (see 2026-08
    Otter->PT55 switch, where 'Week X of 13' kept printing after the plan
    became a 14-week PT55 block)."""
    global _total_weeks_cache
    if _total_weeks_cache is not None:
        return _total_weeks_cache
    try:
        client = get_bq_client()
        q = f"SELECT MAX(week_number) as n FROM `{BQ_PLAN}`"
        rows = list(client.query(q).result())
        _total_weeks_cache = int(rows[0].n) if rows and rows[0].n else None
    except Exception as e:
        print(f"get_total_weeks failed: {e}")
        _total_weeks_cache = None
    return _total_weeks_cache


# ── Interval-session effort assessment ──────────────────────────────────────
# Root cause fixed here (2026-09): assess_effort_intensity() below judges a
# session by its WHOLE-ACTIVITY average HR. For a steady effort (easy_trail,
# long_run) that's the right number. For a structured interval session
# (INTERVAL_SESSION_TYPES) it is not -- averaging warm-up + hard reps +
# recovery jogs + cool-down together produces a number that describes none
# of them. On 2026-09-16 this fired "NOT HARD ENOUGH" on a 6x3min Z5 hill
# session because the whole-activity average (147bpm, diluted by a 2km
# warm-up and 2km cool-down) undercut the Z5 floor, when the isolated work
# reps averaged 167bpm / peaked at 176-177bpm -- a well-executed session.
# This is the false-criticism mirror of the false-praise bug fixed in
# August: judging a structured session by a single aggregate is wrong in
# both directions.
#
# _parse_session_structure() itself is imported from session_parser.py (see
# note above INTERVAL_SESSION_TYPES) -- not redefined here.


def fetch_activity_laps(garmin_client, activity_id):
    """One extra Garmin Connect call: GET activity-service/activity/{id}/splits.
    Read-only, reuses the already-authenticated session from load_garmin_client
    -- no extra login/token exchange, so no incremental exposure to the 429s
    that have taken this pipeline down before. Only called once per daily run,
    and only for the single activity being analysed (never for the whole
    recent-activities list). Fails soft: any error returns [] so the caller
    falls back to UNCONFIRMED instead of raising and losing the whole email."""
    try:
        data = garmin_client.get_activity_splits(activity_id)
        return data.get("lapDTOs") or []
    except Exception as e:
        print(f"fetch_activity_laps failed for activity {activity_id}: {e}")
        return []


def assess_interval_effort(plan, activity_id, garmin_client):
    """Assess a structured/interval session (INTERVAL_SESSION_TYPES) by
    isolating the WORK reps from warm-up, recovery jogs, and cool-down --
    never by whole-activity average HR. Returns (verdict, explanation) using
    the existing verdict vocabulary (NAILED IT / TOO HARD / TOO EASY /
    NOT HARD ENOUGH), plus UNCONFIRMED whenever the lap data can't support a
    confident read. UNCONFIRMED is a deliberate answer, not a fallback to the
    old (wrong) whole-activity number -- guessing confidently from bad data
    is worse than admitting the data doesn't support a verdict.
    """
    session_type = plan["session_type"]
    hr_target = SESSION_HR_TARGETS.get(session_type)
    if not hr_target:
        # Every sibling early-return in this function yields UNCONFIRMED, not a bare
        # (None, None) -- a silent None verdict is exactly the failure mode this whole
        # feature exists to close off (Rune IMPORTANT, 2026-09-16): the caller's
        # `if adherence["intensity_verdict"]:` check would just omit the "Effort
        # intensity:" line entirely rather than surfacing that something is wrong.
        # Unreachable today (SESSION_HR_TARGETS and INTERVAL_SESSION_TYPES agree on all
        # four types) -- kept as a structural guard against future drift between them.
        return "UNCONFIRMED", (
            f"No HR target is configured for session_type '{session_type}' -- intensity on "
            "the work reps could not be judged without one. This indicates a config gap "
            "(SESSION_HR_TARGETS / INTERVAL_SESSION_TYPES out of sync), not a data problem."
        )

    laps = fetch_activity_laps(garmin_client, activity_id)
    if len(laps) < 3:
        return "UNCONFIRMED", (
            "This was a structured interval session, but Garmin returned fewer than 3 laps for it -- "
            "not enough to separate warm-up, work reps, recovery, and cool-down. Whole-activity average "
            "HR is not a valid substitute; it blends all four into one number that represents none of "
            "them. Intensity on the work reps could not be confirmed this time."
        )

    # Structured-workout laps carry a non-'ACTIVE' intensityType (this Garmin
    # account's data shows 'INTERVAL' end-to-end on a real structured
    # workout, including its warm-up/cool-down laps). Plain GPS auto-lap on a
    # free run (no course loaded) comes back 'ACTIVE' with near-identical
    # lap distances and carries NO rep-boundary information at all -- two of
    # three threshold/hill_repeats sessions checked on 2026-09-16 were this
    # case (auto-lapped every 1km, no course loaded that day).
    structured = any((l.get("intensityType") or "ACTIVE") != "ACTIVE" for l in laps)
    # NULL guard convention (established 2026-08, domain_kai_devops.md): `l.get(k) or 0`,
    # not `l.get(k, 0)` -- the two-arg form only fires its default on a MISSING key, not on
    # a key present with an explicit `None`, which is exactly what a null lap field comes
    # back as from the Garmin API.
    interior_dists = [l.get("distance") or 0 for l in laps[:-1]]
    autolap_uniform = len(interior_dists) >= 3 and (max(interior_dists) - min(interior_dists)) < 50

    # `structured` (from Garmin's own intensityType) is the AUTHORITATIVE signal --
    # `autolap_uniform` is a fallback heuristic that exists specifically to catch
    # the case where intensityType ISN'T reliable (a free run with plain GPS
    # auto-lap, which always reads 'ACTIVE'). ORing them let the fallback veto the
    # authoritative signal (Rune IMPORTANT, 2026-09-16 close-out): a well-paced
    # session with consistent rep distances -- i.e. good execution -- where
    # recovery jogs happen to land within ~50m of the work reps got flagged as
    # "looks like auto-lap" and silently UNCONFIRMED despite intensityType
    # correctly confirming a real structured workout with genuine rep boundaries.
    # That's the inverted failure mode this whole feature exists to avoid:
    # rewarding good execution with silence. Fixed: autolap_uniform is now only
    # consulted when `structured` is False -- i.e. only as a fallback for the
    # specific case its own comment above describes, never as a veto over a
    # metadata-confirmed structured workout.
    if not structured and autolap_uniform:
        return "UNCONFIRMED", (
            "Lap data on this activity looks like default GPS auto-lap (even splits), not the "
            "structured interval workout the plan prescribed -- there's no way to separate work reps "
            "from recovery in this data. Load the course/structured workout on the watch for this "
            "session type; until then, intensity on the work reps can't be confirmed."
        )
    if not structured:
        return "UNCONFIRMED", (
            "Lap data on this activity doesn't carry the structured-workout intensity metadata "
            "(intensityType) that marks a real course-loaded interval session, and lap distances "
            "aren't uniform enough to identify it as plain auto-lap either -- there's no reliable "
            "way to separate work reps from recovery in this data. Intensity on the work reps "
            "could not be confirmed this time."
        )

    structure = _parse_session_structure(plan.get("description"))
    # CRITICAL (Rune, 2026-09-16): rep_minutes=None (unparseable plan description --
    # confirmed live on 4/28 current interval-type rows, e.g. "4x90sec" using seconds
    # not "min", or a hill_repeats description with no numeric rep duration at all)
    # previously fell through to `if rep_minutes and rep_minutes <= 4:` being FALSE,
    # silently routing into the long-rep/whole-work-average branch below -- which is
    # the exact whole-activity-style averaging this feature exists to avoid for short
    # reps. Fail safe and explicit instead of picking a method by accident.
    if structure["rep_minutes"] is None:
        return "UNCONFIRMED", (
            "This is a structured interval session, but the prescribed rep duration could "
            "not be parsed from the plan description (expected a pattern like 'Nx Ymin' or "
            "'Nx hill reps, ~Ymin'). Without it there's no safe way to choose between the "
            "short-rep (max-HR) and long-rep (average-HR) judging method -- intensity on "
            "the work reps could not be confirmed this time. Check the plan description's "
            "structure text for this session."
        )

    # IMPORTANT (Rune, 2026-09-16): a mentioned-but-unparseable warm-up/cool-down is
    # NOT the same as "there isn't one." The distance-gated strips below only fire
    # when a km figure parsed; if the plan text says "Cool down." with no distance
    # (confirmed live on 14/28 current rows -- rep_minutes parses fine on these, so
    # they sailed past the CRITICAL check and were WRONGLY characterised as safe),
    # the cool-down lap silently stays in `interior`, pulls `min(hrs)`/`midpoint`
    # down (a cool-down runs cooler than a mid-set recovery jog), can cross genuine
    # recovery laps into `work`, and -- worst case -- depresses the tail of
    # `rep_hrs` into a false-positive `significant_fade` that downgrades a clean
    # set with emphatic "you did not hold the target" language. No existing gate
    # catches this; it proceeds straight to a confident, contaminated verdict.
    # Fail safe instead of guessing which lap is the untimed warm-up/cool-down.
    if structure["warmup_mentioned"] and not structure["warmup_km"]:
        return "UNCONFIRMED", (
            "This session's plan description mentions a warm-up but doesn't give its distance, "
            "so the warm-up lap can't be safely separated from the work reps in the lap data -- "
            "including it would contaminate the work-rep HR average. Intensity could not be "
            "confirmed this time."
        )
    if structure["cooldown_mentioned"] and not structure["cooldown_km"]:
        return "UNCONFIRMED", (
            "This session's plan description mentions a cool-down but doesn't give its distance, "
            "so the cool-down lap can't be safely separated from the work reps in the lap data -- "
            "a cool-down typically reads cooler than a mid-set recovery jog and would pull the "
            "work-rep HR average down (or trigger a false fade-based downgrade). Intensity could "
            "not be confirmed this time."
        )

    interior = list(laps)
    # Same NULL guard as above -- direct `["distance"]` indexing would KeyError on a
    # missing field and a bare `/1000` would TypeError on an explicit `None`; either
    # crashes this function uncaught (fetch_activity_laps only guards the API call
    # itself, not this post-processing), which loses the whole day's email, not just
    # this verdict.
    if structure["warmup_km"] and interior and (interior[0].get("distance") or 0) / 1000 >= structure["warmup_km"] * 0.6:
        interior = interior[1:]
    if structure["cooldown_km"] and interior and (interior[-1].get("distance") or 0) / 1000 >= structure["cooldown_km"] * 0.5:
        interior = interior[:-1]
    interior = [l for l in interior if l.get("averageHR")]

    if len(interior) < 2:
        return "UNCONFIRMED", (
            "Could not isolate work reps from warm-up/cool-down in the lap data for this session."
        )

    # Work vs recovery split: laps at/above the midpoint between the lowest
    # and highest interior avg HR are the hard reps, the rest are recovery
    # jogs. Heuristic, not a Garmin-provided label -- holds up on every
    # structured workout inspected so far because a genuine work rep reads
    # meaningfully higher than the recovery either side of it, but a
    # pathological case (e.g. recovery HR never drops) could fool it.
    hrs = [l["averageHR"] for l in interior]
    midpoint = (max(hrs) + min(hrs)) / 2
    work = [l for l in interior if l["averageHR"] >= midpoint]

    if not work:
        return "UNCONFIRMED", "Could not distinguish work reps from recovery in the lap data."

    # IMPORTANT #2 (Rune, 2026-09-16): rep_count is parsed but was never checked
    # against what the midpoint heuristic actually isolated. If isolation misfires
    # (e.g. finds 1-2 laps when 6 were prescribed -- the exact failure mode the
    # comment above already calls out as possible), the majority rule further down
    # fires confidently on a degenerate denominator: a 1-rep "work" set reduces
    # "majority" to a single pass/fail, with nothing flagging that the isolation
    # itself was suspect. Tolerance chosen: +/-1 lap -- absorbs an ordinary
    # lap-press timing quirk (one boundary merged or split) without masking a
    # mismatch at the scale that actually indicates isolation failure.
    rep_count = structure["rep_count"]
    if rep_count is not None and abs(len(work) - rep_count) > 1:
        return "UNCONFIRMED", (
            f"The plan prescribed {rep_count} work reps, but lap-based isolation found "
            f"{len(work)} -- too large a mismatch to trust the isolation. Rather than score a "
            "mis-isolated subset of the reps, intensity could not be confirmed this time."
        )

    work_avg_hr = sum(l["averageHR"] for l in work) / len(work)
    work_max_hr = max(l.get("maxHR") or 0 for l in work)
    rep_hrs = [l["averageHR"] for l in work]  # chronological -- laps come back in activity order

    # `significant_fade` is a VERDICT input, not just narrative (Rune IMPORTANT,
    # 2026-09-16 round 2): a fade signal must feed verdict selection, never just
    # narrate -- an email must never read "NAILED IT" immediately followed by
    # "you did not hold the target through to the end of the set."
    #
    # FADE-VS-ARTIFACT REDESIGN (Aria's ruling via Marco, 2026-09-16 round 3):
    # a raw HR drop between first-half and second-half reps is ambiguous -- on
    # real trail/hill terrain a rep cut short at a road crossing, or a later
    # hill-rep landing on a different section of climb, reads identically to
    # genuine fatigue. Fixed by judging EFFICIENCY (HR per unit of output),
    # not raw HR, gated on a terrain-consistency precheck, and requiring an
    # actual decoupling pattern (HR holding/rising while output falls) rather
    # than a raw HR decline. If any precondition fails, the fade line is
    # OMITTED entirely -- silence, not a guess -- per Aria's explicit
    # acceptance criterion: fade must never downgrade a verdict on evidence
    # that can't support it.
    fade_note = ""
    significant_fade = False
    # (1) sharpener excluded ENTIRELY -- very short/sharp reps with full
    # recovery carry too much rep-to-rep HR noise for a fade read to mean
    # anything, not just an unfair downgrade; no fade commentary at all for
    # this session_type, not even a positive "held efficiency" note.
    if session_type not in FADE_EXCLUDED_SESSION_TYPES and len(rep_hrs) >= 4:
        # (4) Terrain-consistency precheck: rep distances within ~30% of the
        # (approximate) median. Reps that vary more than that aren't
        # comparable -- one may be a genuinely different climb section or a
        # shortened rep, not a fatigue signal. Gates the WHOLE fade read, not
        # just the downgrade half, because "held efficiency" is equally
        # invalid to claim on inconsistent terrain.
        work_dists = [l.get("distance") or 0 for l in work]
        sorted_dists = sorted(work_dists)
        median_dist = sorted_dists[len(sorted_dists) // 2]
        terrain_consistent = median_dist > 0 and all(
            abs(d - median_dist) / median_dist <= 0.30 for d in work_dists
        )
        if terrain_consistent:
            # (3) Efficiency ratio = HR / grade-adjusted output, not raw HR.
            #
            # Output term (Aria's calibration, 2026-09-16, round 2): a constant
            # vertical-equivalent factor is wrong because the true cost-of-climbing
            # curve is CONVEX, not linear -- her regression of 85 of Alexis's own
            # trail sessions (matched HR band; whole-session aggregates as a proxy,
            # her own caveat: direction/magnitude sound, exact figures not precise)
            # found ~5-6x on moderate/rolling terrain (where threshold reps happen)
            # rising to ~12-13x on steep terrain like Platteklip Gorge/Kloof Nek
            # (where vo2max/hill_repeats reps happen). A single constant
            # over-penalises rolling terrain and under-penalises steep climbs --
            # backwards for exactly the sessions that matter most.
            #
            # PRIMARY: Garmin's own per-lap `avgGradeAdjustedSpeed` -- confirmed
            # present and populated live (31/31 laps across 2 real activities
            # checked 2026-09-16, field name and non-null/non-zero values
            # verified directly, not assumed). It captures the nonlinearity
            # natively and removes the constant-picking problem entirely; used
            # directly as the output term (it's already a speed, no division needed).
            #
            # FALLBACK: only if avgGradeAdjustedSpeed is missing/null/zero on ANY
            # work rep -- never mix methods within one comparison (one lap on GAS,
            # another on the constant formula would make the ratio meaningless).
            # Falls back to a SPLIT constant (her figures, not a uniform value):
            # GRADE_FACTOR_FALLBACK below, keyed by session_type.
            def _rep_output_gas(l):
                gas = l.get("avgGradeAdjustedSpeed")
                return gas if gas and gas > 0 else None

            def _rep_output_fallback(l, factor):
                dist = l.get("distance") or 0
                elev = l.get("elevationGain") or 0
                dur = l.get("duration") or 0
                if dur <= 0:
                    return None
                return (dist + factor * elev) / dur  # effective m/s

            gas_outputs = [_rep_output_gas(l) for l in work]
            method = None
            outputs = None
            if all(o is not None for o in gas_outputs):
                outputs = gas_outputs
                method = "Garmin's grade-adjusted speed"
            else:
                factor = GRADE_FACTOR_FALLBACK.get(session_type)
                if factor is not None:
                    fb_outputs = [_rep_output_fallback(l, factor) for l in work]
                    if all(o is not None and o > 0 for o in fb_outputs):
                        outputs = fb_outputs
                        method = f"a {factor}x vertical-equivalent estimate (Garmin's own grade-adjusted speed wasn't available for this activity)"
                # else: no fallback factor defined for this session_type, or the
                # fallback itself couldn't compute (missing distance/duration) --
                # outputs stays None, fade_note stays "", omitted rather than guessed.

            if outputs is not None:
                # HR / output: a RISING ratio means more heartbeats per unit of
                # work done as the set goes on -- decoupling. A flat or falling
                # ratio means efficiency held even if raw HR happened to drop
                # (that rep just produced the same or more work for less HR --
                # the opposite of fatigue).
                ratios = [l["averageHR"] / o for l, o in zip(work, outputs)]
                half = len(ratios) // 2
                first_half_ratio = sum(ratios[:half]) / half
                second_half_ratio = sum(ratios[half:]) / (len(ratios) - half)
                ratio_rise_pct = (
                    ((second_half_ratio - first_half_ratio) / first_half_ratio) * 100
                    if first_half_ratio else 0
                )
                # (5) Decoupling requires HR holding or rising while output falls --
                # not just a ratio artifact. A small noise tolerance (2bpm) avoids
                # rejecting a genuine flat-HR case on rounding.
                first_half_hr = sum(rep_hrs[:half]) / half
                second_half_hr = sum(rep_hrs[half:]) / (len(rep_hrs) - half)
                hr_not_falling = second_half_hr >= first_half_hr - 2

                # (2) Threshold (Aria's calibration, 2026-09-16, round 2): her
                # regression of the REAL 2026-09-16 VO2max lap data found ~10%
                # natural rep-to-rep noise in distance covered on fixed-duration
                # reps even in a genuinely fade-free session -- the original 10%
                # ratio-rise threshold sat INSIDE that noise floor and would fire
                # on noise. Raised to 20% for real margin above it. Flat across
                # threshold/vo2max/hill_repeats -- no per-type variation (sharpener
                # is excluded from fade entirely, upstream of this block). Settled
                # per her domain_aria_fitness.md write-up -- not to be relitigated
                # without new evidence.
                if ratio_rise_pct >= DECOUPLING_THRESHOLD_PCT and hr_not_falling:
                    significant_fade = True
                    fade_note = (
                        f" Efficiency faded across the set (judged on {method}): HR cost per unit "
                        f"of effort rose {ratio_rise_pct:.0f}% from the first half to the second half "
                        f"(HR {second_half_hr:.0f} bpm in the second half vs {first_half_hr:.0f} bpm "
                        f"in the first, while output fell) -- you did not hold the target through to "
                        f"the end of the set."
                    )
                elif ratio_rise_pct <= -DECOUPLING_THRESHOLD_PCT:
                    fade_note = f" Efficiency held or improved across the set (judged on {method}) -- no fade."
                else:
                    fade_note = f" Efficiency held steady across all {len(work)} reps (judged on {method})."
                # else (no viable output method): fade_note stays "", omitted rather than guessed.
            # else (terrain inconsistent across reps): fade_note stays "", omitted.
        # else (sharpener, or <4 reps to compare halves): fade_note stays "", omitted.

    expected_min, expected_max = hr_target["min"], hr_target["max"]
    rep_minutes = structure["rep_minutes"]

    # Short reps (<=4min) don't give HR time to plateau before the rep ends --
    # judging avg-HR-during-rep against a steady-state zone floor is not a
    # fair read there (Magness/Koop: cardiac lag on short VO2max efforts).
    # Max HR reached, plus consistency across reps, is the honest signal.
    # Longer reps (threshold-style, ~6min+) give HR time to settle, so
    # average-during-rep is treated as a fair signal there, same as before.
    if rep_minutes and rep_minutes <= 4:
        # Majority rule (Rune IMPORTANT, 2026-09-16): the old check
        # (`work_max_hr >= floor`) let ONE strong rep among several weak ones --
        # or a single sensor glitch -- decide NAILED IT vs NOT HARD ENOUGH for the
        # whole set. Require more than half the reps to individually reach the
        # floor on their own max HR.
        per_rep_max = [l.get("maxHR") or 0 for l in work]
        reps_hit_target = sum(1 for m in per_rep_max if m >= expected_min - 3)
        majority_hit = reps_hit_target > len(work) / 2

        if majority_hit and not significant_fade:
            verdict = "NAILED IT"
            expl = (f"Work reps peaked at {work_max_hr:.0f} bpm (avg {work_avg_hr:.0f} bpm across "
                    f"{len(work)} reps, {reps_hit_target}/{len(work)} individually reaching the "
                    f"{expected_min} bpm floor).{fade_note} On {rep_minutes}-min reps, HR does not have time to "
                    f"plateau at the target average before the rep ends -- max HR reached and consistency "
                    f"across reps are the honest read here, and both look good. "
                    f"The plan said: \"{plan.get('effort_description','')}\".")
        elif majority_hit and significant_fade:
            # Downgraded from NAILED IT, not just footnoted -- also feeds the
            # existing OFF-PLAN/PARTIAL/ON-PLAN rollup below via the
            # ("TOO HARD","TOO EASY","NOT HARD ENOUGH") membership check, same as
            # every other non-NAILED-IT verdict.
            verdict = "TOO EASY"
            expl = (f"Work reps peaked at {work_max_hr:.0f} bpm (avg {work_avg_hr:.0f} bpm across "
                    f"{len(work)} reps, {reps_hit_target}/{len(work)} individually reaching the "
                    f"{expected_min} bpm floor) -- the early reps were hard enough, but you faded before "
                    f"the end of the set.{fade_note} That's not the full stimulus this session "
                    f"prescribed; hold the intensity to the last rep next time.")
        else:
            verdict = "NOT HARD ENOUGH"
            expl = (f"Only {reps_hit_target}/{len(work)} work reps reached the {expected_min} bpm floor "
                    f"on their own max HR (overall peak {work_max_hr:.0f} bpm, avg {work_avg_hr:.0f} bpm "
                    f"across {len(work)} reps) -- below target even accounting for HR lag on short reps."
                    f"{fade_note} Push harder on the climbs next time.")
    else:
        if work_avg_hr < expected_min - 10:
            verdict = "NOT HARD ENOUGH"
            expl = (f"Work reps averaged {work_avg_hr:.0f} bpm across {len(work)} reps -- well short of "
                    f"the {expected_min}-{expected_max} bpm target.{fade_note}")
        elif work_avg_hr < expected_min:
            verdict = "TOO EASY"
            expl = (f"Work reps averaged {work_avg_hr:.0f} bpm across {len(work)} reps -- just under the "
                    f"{expected_min} bpm floor.{fade_note}")
        elif work_avg_hr > expected_max + 5:
            verdict = "TOO HARD"
            expl = (f"Work reps averaged {work_avg_hr:.0f} bpm across {len(work)} reps -- over the "
                    f"{expected_max} bpm ceiling.{fade_note}")
        elif significant_fade:
            # Same downgrade as the short-rep branch: the average lands in zone,
            # but that average hides a real decline across the set -- NAILED IT
            # would contradict the fade narrative that follows it.
            verdict = "TOO EASY"
            expl = (f"Work reps averaged {work_avg_hr:.0f} bpm across {len(work)} reps -- in the "
                    f"{expected_min}-{expected_max} bpm target zone overall, but that average hides a "
                    f"real fade.{fade_note} Credit for starting strong, but this isn't a full NAILED IT "
                    f"-- hold the intensity to the last rep next time.")
        else:
            verdict = "NAILED IT"
            expl = (f"Work reps averaged {work_avg_hr:.0f} bpm across {len(work)} reps -- right in the "
                    f"{expected_min}-{expected_max} bpm target zone.{fade_note}")

    return verdict, expl


# ── Effort intensity comparison ──────────────────────────────────────────────

def assess_effort_intensity(plan, avg_hr):
    """Compare actual effort against prescribed effort.
    Returns (verdict, explanation) tuple."""
    if not plan or not avg_hr:
        return None, None

    session_type = plan["session_type"]
    target_rpe = plan.get("target_rpe", 0) or 0
    target_hr_max = plan.get("target_hr_max")
    effort_desc = plan.get("effort_description", "")

    # Get expected HR range for this session type
    hr_target = SESSION_HR_TARGETS.get(session_type)
    if not hr_target:
        return None, None

    expected_min = hr_target["min"]
    expected_max = hr_target["max"]
    expected_zone = hr_target["zone"]

    # Categorize actual effort
    actual_zone = hr_zone(avg_hr)

    # Easy sessions (RPE <= 4): check if went too hard
    if target_rpe <= 4:
        if avg_hr > expected_max + 10:
            return ("TOO HARD", (
                f"You turned an easy day into a threshold session. "
                f"Your avg HR was {avg_hr:.0f} bpm but should have stayed below {expected_max} bpm ({expected_zone}). "
                f"This defeats the purpose of polarised training. "
                f"The plan said: \"{effort_desc}\" -- instead you ran at {actual_zone} intensity. "
                f"Easy must be EASY. Walk uphills if your HR drifts above {expected_max}."
            ))
        elif avg_hr > expected_max:
            return ("TOO HARD", (
                f"Your avg HR of {avg_hr:.0f} bpm crept above the {expected_max} bpm ceiling for this session. "
                f"Grey zone territory. Not easy enough to recover, not hard enough to improve. "
                f"Next time: walk any climb that pushes HR above {expected_max}."
            ))
        elif avg_hr <= expected_max and avg_hr >= expected_min:
            return ("NAILED IT", (
                f"Avg HR {avg_hr:.0f} bpm -- right in the {expected_zone} zone. "
                f"This is exactly the discipline that builds an aerobic engine. "
                f"The plan said: \"{effort_desc}\" -- and that is what you delivered."
            ))
        else:
            return ("NAILED IT", (
                f"Avg HR {avg_hr:.0f} bpm -- well controlled, even conservative. Perfect for an easy day."
            ))

    # Hard sessions (RPE >= 7): check if went hard enough
    if target_rpe >= 7:
        if avg_hr < expected_min - 10:
            return ("NOT HARD ENOUGH", (
                f"You went too easy. This session should have had you gasping. "
                f"Your HR averaged {avg_hr:.0f} bpm but should have been {expected_min}-{expected_max} bpm on the intervals. "
                f"Push harder next time -- Suther Peak in the first 10km of PT55 will not be forgiving. "
                f"The plan said: \"{effort_desc}\" -- did it feel like that? "
                f"If you held back, you wasted a quality session. If you genuinely could not push harder, that is a fitness signal to address."
            ))
        elif avg_hr < expected_min:
            return ("TOO EASY", (
                f"Your avg HR of {avg_hr:.0f} bpm was below the target range of {expected_min}-{expected_max} bpm. "
                f"For a {plan['session_name']}, you need to commit to the effort. "
                f"The plan said: \"{effort_desc}\" -- next time, push into that zone and stay there."
            ))
        elif avg_hr > expected_max + 5:
            return ("TOO HARD", (
                f"Your avg HR of {avg_hr:.0f} bpm exceeded the {expected_max} bpm ceiling. "
                f"You overcooked it. There is a difference between racing and training hard. "
                f"Going too hard in training means you cannot recover for the next session. "
                f"The plan prescribed {expected_zone}, not all-out."
            ))
        else:
            return ("NAILED IT", (
                f"Avg HR {avg_hr:.0f} bpm -- right in the prescribed {expected_zone} zone ({expected_min}-{expected_max} bpm). "
                f"The plan said: \"{effort_desc}\" -- you delivered exactly that. "
                f"This is how you build race fitness."
            ))

    # Moderate sessions (RPE 5-6): long runs, technical
    if avg_hr > expected_max + 8:
        return ("TOO HARD", (
            f"Too hard for this session. Your avg HR of {avg_hr:.0f} bpm was well above the "
            f"{expected_max} bpm ceiling. You are burning matches you need for race day. "
            f"On a {plan['session_name']}, the effort should be sustainable for hours, not racing."
        ))
    elif avg_hr > expected_max:
        return ("TOO HARD", (
            f"Your avg HR drifted to {avg_hr:.0f} bpm, above the {expected_max} bpm target. "
            f"On long/moderate sessions, HR should stay in {expected_zone}. Control the effort."
        ))
    elif avg_hr < expected_min - 15:
        return ("TOO EASY", (
            f"Your avg HR of {avg_hr:.0f} bpm was well below the expected range. "
            f"This session needed more intention. The plan said: \"{effort_desc}\""
        ))
    else:
        return ("NAILED IT", (
            f"Avg HR {avg_hr:.0f} bpm -- well controlled in the {expected_zone} zone. "
            f"The plan said: \"{effort_desc}\" -- and you executed it."
        ))


# ── Adherence verdict (plan vs actual, not just HR) ──────────────────────────
# This is the fix for the "nailed it regardless" defect: assess_effort_intensity
# above ONLY looks at avg HR. It never checked whether the session that was
# actually done resembles the one that was prescribed -- same sport, same
# rough distance/duration/vert. A session that was the wrong sport entirely,
# or 3x the prescribed vert, or half the prescribed distance, could still
# come back "NAILED IT" purely because HR happened to land in a zone.
# assess_adherence() is the outer check that runs first and can override
# the HR verdict with OFF PLAN / PARTIAL / MISSED. No text below is allowed
# to soften a verdict the numbers don't support.

SEVERE_SHORT_RATIO   = 0.50   # < 50% of prescribed distance/duration = cut drastically short
PARTIAL_SHORT_RATIO  = 0.75
MAJOR_OVERSHOOT_RATIO = 1.50  # distance/duration
FLAG_OVERSHOOT_RATIO  = 1.30
MAJOR_VERT_OVERSHOOT  = 2.00
FLAG_VERT_OVERSHOOT   = 1.50
FLAT_SESSION_VERT_CAP_M = 150  # if plan target_vert_m is 0/None, actual vert above this is notable

def assess_adherence(plan, actual, garmin_client=None, activity_id=None):
    """Compare the ACTUAL session (type, distance, duration, elevation, HR)
    against the PRESCRIBED session for the day.

    Returns a dict:
      verdict: "ON PLAN" | "PARTIAL" | "OFF PLAN" | None (no plan for today)
      reasons: list of str, structural mismatches (sport/distance/duration/vert)
      intensity_verdict / intensity_explanation: the HR-based sub-verdict
        (NAILED IT / TOO HARD / TOO EASY / NOT HARD ENOUGH / UNCONFIRMED),
        still reported but no longer the whole story.
    `actual` is a dict with keys: act_type, name, dist_km, dur_min, elev_m,
    avg_hr, max_hr.
    `garmin_client` / `activity_id` are optional and only used when
    plan["session_type"] is in INTERVAL_SESSION_TYPES -- assessing those
    needs a per-lap Garmin call (assess_interval_effort), not just the
    whole-activity `actual` dict. If either is missing on an interval
    session, the verdict comes back UNCONFIRMED rather than silently
    falling back to the whole-activity-average path that produces false
    verdicts on structured sessions.
    """
    if not plan:
        return {"verdict": None, "reasons": [], "intensity_verdict": None, "intensity_explanation": None}

    reasons = []
    plan_cat = _plan_category(plan["session_type"])
    act_cat = _activity_category(actual.get("act_type"))

    # 1. Wrong sport entirely -- decisive, skip HR check, it's not meaningful.
    # Any mismatch counts, including "other" (swim/yoga/elliptical/paddle/
    # anything not in the run/bike/strength Garmin type sets) -- that used to
    # fall through to the numeric ratio comparison below and could score
    # ON PLAN purely because distance/duration happened to line up.
    if plan_cat in ("run", "bike") and act_cat != plan_cat:
        # act_cat is one of our own fixed category strings (run/bike/strength/
        # other), safe as-is; the "other" fallback surfaces the raw Garmin
        # typeKey, which -- like activityName -- is escaped before it can
        # reach the HTML-rendered "reasons" list.
        logged_desc = act_cat if act_cat != "other" else html.escape(actual.get("act_type") or "unrecognised-type")
        reasons.append(
            f"WRONG SESSION TYPE: plan called for a {plan_cat} session "
            f"(\"{plan['session_name']}\"), you logged a {logged_desc} activity (\"{actual.get('name')}\")."
        )
        return {"verdict": "OFF PLAN", "reasons": reasons, "intensity_verdict": None, "intensity_explanation": None}

    dist_ratio = (actual["dist_km"] / plan["target_km"]) if plan.get("target_km") and actual.get("dist_km") else None
    dur_ratio  = (actual["dur_min"] / plan["target_duration_min"]) if plan.get("target_duration_min") and actual.get("dur_min") else None
    vert_ratio = None
    if plan.get("target_vert_m") and plan["target_vert_m"] > 0 and actual.get("elev_m") is not None:
        vert_ratio = actual["elev_m"] / plan["target_vert_m"]

    # Zero-distance activities (GPS loss, indoor/treadmill without a distance
    # sensor, manual entry) fall back to duration-only comparison below via
    # dist_ratio being None -- flag that explicitly instead of silently
    # re-routing, so Alexis knows why distance wasn't checked.
    if plan.get("target_km") and actual.get("dist_km") == 0:
        reasons.append(
            "NOTE: activity logged 0km distance (GPS loss or manual entry?) -- "
            "falling back to duration only for the distance comparison."
        )

    severe_short = (dist_ratio is not None and dist_ratio < SEVERE_SHORT_RATIO) or \
                   (dist_ratio is None and dur_ratio is not None and dur_ratio < SEVERE_SHORT_RATIO)
    partial_short = (not severe_short) and dist_ratio is not None and dist_ratio < PARTIAL_SHORT_RATIO

    if severe_short:
        reasons.append(
            f"SESSION CUT SHORT: {actual.get('dist_km', 0):.1f}km / {fmt_duration(actual.get('dur_min', 0))} "
            f"done vs {plan['target_km']:.0f}km / {fmt_duration(plan['target_duration_min'])} prescribed "
            f"({(dist_ratio or dur_ratio) * 100:.0f}% of target)."
        )
    elif partial_short:
        reasons.append(
            f"SHORT OF TARGET: {actual['dist_km']:.1f}km vs {plan['target_km']:.0f}km prescribed "
            f"({dist_ratio * 100:.0f}% of target distance)."
        )

    dist_major_overshoot = dist_ratio is not None and dist_ratio > MAJOR_OVERSHOOT_RATIO
    dist_flag_overshoot  = dist_ratio is not None and FLAG_OVERSHOOT_RATIO < dist_ratio <= MAJOR_OVERSHOOT_RATIO
    if dist_ratio is not None and dist_ratio > FLAG_OVERSHOOT_RATIO:
        reasons.append(
            f"DISTANCE OVERSHOOT: {actual['dist_km']:.1f}km vs {plan['target_km']:.0f}km prescribed "
            f"(+{(dist_ratio - 1) * 100:.0f}%)."
        )

    vert_major_overshoot = vert_ratio is not None and vert_ratio > MAJOR_VERT_OVERSHOOT
    vert_flag_overshoot  = vert_ratio is not None and FLAG_VERT_OVERSHOOT < vert_ratio <= MAJOR_VERT_OVERSHOOT
    if vert_ratio is not None and vert_ratio > FLAG_VERT_OVERSHOOT:
        reasons.append(
            f"VERT OVERSHOOT: +{actual.get('elev_m', 0):.0f}m vs +{plan['target_vert_m']:.0f}m prescribed "
            f"({vert_ratio * 100:.0f}% of target -- materially harder terrain than planned)."
        )

    # Vert UNDERSHOOT -- a vert-focused session (mtb, hill_repeats, downhill...)
    # replaced by a flat session at target distance/duration was previously
    # invisible here: only overshoot was checked. Mirrors the distance
    # severe/partial-short thresholds above.
    vert_severe_short  = vert_ratio is not None and vert_ratio < SEVERE_SHORT_RATIO
    vert_partial_short = (not vert_severe_short) and vert_ratio is not None and vert_ratio < PARTIAL_SHORT_RATIO
    if vert_severe_short:
        reasons.append(
            f"VERT UNDERSHOOT: +{actual.get('elev_m', 0):.0f}m vs +{plan['target_vert_m']:.0f}m prescribed "
            f"({vert_ratio * 100:.0f}% of target -- the intended climbing stimulus is largely missing)."
        )
    elif vert_partial_short:
        reasons.append(
            f"VERT SHORT OF TARGET: +{actual.get('elev_m', 0):.0f}m vs +{plan['target_vert_m']:.0f}m prescribed "
            f"({vert_ratio * 100:.0f}% of target)."
        )

    flat_mismatch = False
    if (not plan.get("target_vert_m")) and actual.get("elev_m", 0) and actual["elev_m"] > FLAT_SESSION_VERT_CAP_M:
        flat_mismatch = True
        reasons.append(
            f"TERRAIN MISMATCH: plan prescribed a flat/low-vert session (0m target) but you climbed "
            f"+{actual['elev_m']:.0f}m -- not the intended stimulus."
        )

    only_duration_overshoot = (dist_ratio is None or dist_ratio <= FLAG_OVERSHOOT_RATIO) and \
                               dur_ratio is not None and dur_ratio > FLAG_OVERSHOOT_RATIO
    if only_duration_overshoot:
        reasons.append(
            f"DURATION OVERSHOOT: {fmt_duration(actual['dur_min'])} vs {fmt_duration(plan['target_duration_min'])} prescribed "
            f"(+{(dur_ratio - 1) * 100:.0f}%)."
        )

    # Structured/interval sessions get assessed on their WORK reps (isolated
    # from warm-up/recovery/cool-down via lap data), never on the
    # whole-activity average -- see assess_interval_effort for why. Every
    # other session_type keeps the original whole-activity-average path,
    # which is correct for steady efforts (easy_trail, long_run, etc).
    if plan["session_type"] in INTERVAL_SESSION_TYPES:
        if garmin_client is not None and activity_id is not None:
            # Belt-and-suspenders, matching this file's existing convention (BQ save,
            # BQ history read, plan queries are all try/except-guarded the same way):
            # fetch_activity_laps() only guards the network call itself. Garmin's lap
            # JSON is external, variable-shape data we don't fully control -- a field
            # this function doesn't yet know to null-guard should degrade this ONE
            # verdict to UNCONFIRMED, not take down the whole day's email via the
            # entry point's outer catch-all.
            try:
                intensity_verdict, intensity_explanation = assess_interval_effort(
                    plan, activity_id, garmin_client
                )
            except Exception as e:
                print(f"assess_interval_effort failed for activity {activity_id}: {e}")
                intensity_verdict, intensity_explanation = "UNCONFIRMED", (
                    "This is a structured interval session, but lap-based intensity assessment "
                    "hit an unexpected error processing the data. Intensity on the work reps "
                    "could not be confirmed this time."
                )
        else:
            intensity_verdict, intensity_explanation = "UNCONFIRMED", (
                "This is a structured interval session, but no activity ID / Garmin client was "
                "available to fetch lap data for it. Whole-activity average HR is not a valid "
                "substitute -- intensity on the work reps could not be confirmed this time."
            )
    else:
        intensity_verdict, intensity_explanation = assess_effort_intensity(
            plan, actual.get("avg_hr")
        )

    structural_issue = severe_short or dist_major_overshoot or vert_major_overshoot or vert_severe_short
    partial_issue = partial_short or dist_flag_overshoot or vert_flag_overshoot or vert_partial_short or \
                    only_duration_overshoot or flat_mismatch or \
                    intensity_verdict in ("TOO HARD", "TOO EASY", "NOT HARD ENOUGH")

    if structural_issue:
        verdict = "OFF PLAN"
    elif partial_issue:
        verdict = "PARTIAL"
    else:
        verdict = "ON PLAN"

    return {
        "verdict": verdict,
        "reasons": reasons,
        "intensity_verdict": intensity_verdict,
        "intensity_explanation": intensity_explanation,
    }


# ── Training history ─────────────────────────────────────────────────────────

def get_training_history(weeks=4):
    # weeks is always an internal constant (never derived from request input),
    # but cast defensively since it's interpolated into an INTERVAL literal --
    # BQ query params can't bind inside INTERVAL N DAY, so this is the guard.
    weeks = int(weeks)
    client = get_bq_client()
    q = f"""
    SELECT activity_name, activity_type, start_time, distance_km, duration_min,
           elevation_gain_m, avg_hr, max_hr, hr_zone, aerobic_training_effect,
           efficiency_index, avg_pace_min_km
    FROM `{BQ_TABLE}`
    WHERE start_time >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL {weeks * 7} DAY)
    ORDER BY start_time DESC
    """
    return list(client.query(q).result())

def format_training_context(rows):
    if not rows:
        return None

    total_km = sum(r.distance_km or 0 for r in rows)
    total_elev = sum(r.elevation_gain_m or 0 for r in rows)
    total_dur = sum(r.duration_min or 0 for r in rows)
    count = len(rows)

    weeks = {}
    for r in rows:
        week_key = r.start_time.strftime("%W")
        if week_key not in weeks:
            weeks[week_key] = {"km": 0, "elev": 0, "count": 0, "dur": 0}
        weeks[week_key]["km"] += r.distance_km or 0
        weeks[week_key]["elev"] += r.elevation_gain_m or 0
        weeks[week_key]["count"] += 1
        weeks[week_key]["dur"] += r.duration_min or 0

    avg_weekly_km = total_km / max(len(weeks), 1)

    zone_counts = {}
    for r in rows:
        z = r.hr_zone or "N/A"
        zone_counts[z] = zone_counts.get(z, 0) + 1

    lines = []
    lines.append(f"- Sessions: **{count}** | Total: **{total_km:.0f} km** / **+{total_elev:.0f}m** / **{fmt_duration(total_dur)}**")
    lines.append(f"- Avg weekly volume: **{avg_weekly_km:.1f} km/week**")

    zone_str = ", ".join(f"{z}: {c}" for z, c in sorted(zone_counts.items()))
    lines.append(f"- Zone distribution: {zone_str}")

    sorted_weeks = sorted(weeks.items())
    if len(sorted_weeks) >= 2:
        prev_km = sorted_weeks[-2][1]["km"]
        curr_km = sorted_weeks[-1][1]["km"]
        if prev_km > 0:
            change = ((curr_km - prev_km) / prev_km) * 100
            direction = "up" if change > 0 else "down"
            lines.append(f"- Week-over-week volume: {direction} {abs(change):.0f}% ({prev_km:.0f} -> {curr_km:.0f} km)")

    lines.append("")
    return "\n".join(lines)

# ── Activities ────────────────────────────────────────────────────────────────
def get_recent_activities(client, days=3):
    activities = client.get_activities(0, 10)
    cutoff = datetime.today() - timedelta(days=days)
    recent = []
    for a in activities:
        dt_str = (a.get("startTimeLocal") or "")[:19]
        try:
            dt = datetime.fromisoformat(dt_str)
            if dt >= cutoff:
                recent.append(a)
        except:
            pass
    return recent

# ── Main analysis (plan-aware) ───────────────────────────────────────────────

def build_plan_aware_feedback(a, all_recent, today_date, plan, tomorrow_plan,
                               week_progress, phase_status, training_context,
                               activity_date=None, today_plan=None, garmin_client=None):
    """Build the full plan-aware feedback email.

    IMPORTANT: `plan` here must be the plan for the ACTIVITY's own date
    (`activity_date`), NOT necessarily today's plan -- the caller resolves
    that. A `days=2` activity lookback can surface yesterday's run on a day
    when today itself is prescribed rest; scoring that activity against
    today's plan produced confidently wrong verdicts ("you ran on a rest
    day" when the run was actually yesterday, correctly taken). When
    `activity_date != today_date`, `today_plan` (today's actual plan) is
    used to render a separate "Today" section so today's real status is
    never silently dropped or misrepresented.

    `garmin_client` is the already-authenticated Garmin client from
    load_garmin_client() -- threaded through to assess_adherence() so
    INTERVAL_SESSION_TYPES sessions can fetch lap data (assess_interval_effort).
    Optional only for test/manual invocation; the real entry point
    (garmin_daily_feedback) always passes it.
    """
    # activityName is free text settable by the device / Connect app / any
    # authorised Connect IQ or partner app -- escape before it ever enters
    # an f-string that markdown_to_html renders as raw HTML (Gmail strips
    # <script> but not <img>/<a>, so an unescaped crafted name could still
    # land a tracking pixel or phishing link).
    # `.get(key, default)` only substitutes on a MISSING key -- an explicit
    # `"activityName": null` from the API returns None, and html.escape(None)
    # raises (old code harmlessly rendered "None"). Use `or` instead.
    # Newline-strip is a log-injection guard: html.escape() does not touch
    # \n/\r, so an embedded newline in a Garmin-supplied name could still
    # forge adjacent lines in `print(feedback)` (Cloud Logging).
    name      = html.escape((a.get("activityName") or "Unnamed").replace("\n", " ").replace("\r", " "))
    dt_str    = (a.get("startTimeLocal") or "")[:19]
    dt        = datetime.fromisoformat(dt_str)
    if activity_date is None:
        activity_date = dt.date()
    same_day = activity_date == today_date
        # Same None-unsafe pattern as activityName/startTimeLocal above:
    # a.get("activityType", {}) only substitutes on a MISSING key --
    # an explicit "activityType": null would return None, not {},
    # and .get() on None raises. `or {}` covers both cases.
    act_type  = (a.get("activityType") or {}).get("typeKey", "running")
    dist_km   = round((a.get("distance") or 0) / 1000, 2)
    dur_min   = round((a.get("duration") or 0) / 60, 1)
    elev_m    = round(a.get("elevationGain") or 0, 0)
    avg_hr    = a.get("averageHR")
    max_hr_act= a.get("maxHR")
    avg_pace  = round((a.get("duration") or 0) / 60 / ((a.get("distance") or 1) / 1000), 2) if a.get("distance") else None
    te        = a.get("aerobicTrainingEffect")
    vo2       = a.get("vO2MaxValue")
    calories  = a.get("calories") or 0
    m_per_km  = round(elev_m / dist_km, 1) if dist_km else 0

    days_to_race = (RACE_DATE - today_date).days
    actual_zone = hr_zone(avg_hr) if avg_hr else "N/A"

    lines = []

    # ── Header ── (always TODAY's date -- matches the email subject line;
    # the activity's own date, if different, is called out explicitly below)
    week_num = plan["week_number"] if (plan and same_day) else (today_plan["week_number"] if today_plan else "?")
    phase = plan["phase"] if (plan and same_day) else (today_plan["phase"] if today_plan else "Pre-plan")
    total_weeks = get_total_weeks() or "?"
    lines.append(f"# Daily Training Feedback -- {today_date.strftime('%A %d %B %Y')}")
    lines.append(f"*Week {week_num} of {total_weeks} | {phase} | **{days_to_race} days to UTCT PT55***")
    lines.append("")

    # ── Plan vs Actual ──
    # `plan` is keyed to the ACTIVITY's own date (activity_date), which may
    # not be today. Label the section accordingly so it's never ambiguous
    # which day is being assessed.
    if same_day:
        lines.append("## Today: Plan vs Actual")
    else:
        lines.append(f"## Most Recent Session -- {activity_date.strftime('%A %d %B')} (not today)")
    if plan:
        p_km = f"{plan['target_km']:.0f} km" if plan['target_km'] else "N/A"
        p_vert = f"{plan['target_vert_m']:.0f}m vert" if plan['target_vert_m'] else "N/A"
        p_zone = plan['target_hr_zone'] or "N/A"
        p_rpe = plan['target_rpe'] or "N/A"
        lines.append(f"PLANNED: {plan['session_name']}, {p_km}, {p_vert}, {p_zone}, RPE {p_rpe}")
    else:
        day_desc = "today" if same_day else activity_date.isoformat()
        lines.append(f"PLANNED: No plan for {day_desc} (outside plan dates)")

    lines.append(f"DONE: {name}, {dist_km} km, +{elev_m:.0f}m vert, avg HR {avg_hr:.0f} ({actual_zone})" if avg_hr else f"DONE: {name}, {dist_km} km, +{elev_m:.0f}m vert")

    # ── Adherence verdict (plan vs actual -- not just HR) ──
    day_word = "today" if same_day else "that day"
    if plan and plan["session_type"] == "rest":
        lines.append(f"ADHERENCE VERDICT: OFF PLAN -- {day_word} was a REST day and you ran anyway. "
                      "Was this a deliberate swap? If so, take the rest day elsewhere this week -- "
                      "it does not just disappear.")
    elif plan and plan["session_type"] == "strength":
        lines.append(f"ADHERENCE VERDICT: PARTIAL -- {day_word} was a STRENGTH day. The run is bonus volume, "
                      "not a substitute. Garmin cannot confirm whether the prescribed strength session "
                      "was also done -- if it was not, that week is short a session.")
    elif plan:
        # int-cast for consistency with save_session_to_bq's convention (Cyrus MINOR,
        # 2026-09-16) -- garminconnect str()'s this internally either way, so this is
        # tidiness, not a correctness fix; a bad/missing id just yields None, and
        # fetch_activity_laps's own try/except turns that into UNCONFIRMED downstream.
        _raw_activity_id = a.get("activityId")
        try:
            _lap_activity_id = int(_raw_activity_id) if _raw_activity_id is not None else None
        except (TypeError, ValueError):
            _lap_activity_id = None
        adherence = assess_adherence(plan, {
            "act_type": act_type, "name": name, "dist_km": dist_km, "dur_min": dur_min,
            "elev_m": elev_m, "avg_hr": avg_hr, "max_hr": max_hr_act,
        }, garmin_client=garmin_client, activity_id=_lap_activity_id)
        if adherence["verdict"]:
            lines.append(f"ADHERENCE VERDICT: {adherence['verdict']}")
            for reason in adherence["reasons"]:
                lines.append(f"- {reason}")
            if adherence["intensity_verdict"]:
                lines.append(f"Effort intensity: {adherence['intensity_verdict']} -- {adherence['intensity_explanation']}")
    else:
        lines.append(f"ADHERENCE VERDICT: No prescribed session {day_word} (outside plan dates) -- nothing to compare against.")
    lines.append("")

    # ── Today, if the most recent activity wasn't from today ──
    # Keeps today's actual status visible instead of letting it disappear
    # behind an older session's writeup (no silent/blank email).
    if not same_day:
        lines.append(f"## Today -- {today_date.strftime('%A %d %B')}")
        if today_plan:
            if today_plan["session_type"] == "rest":
                lines.append(f"PLANNED: {today_plan['session_name']} -- {today_plan['description']}")
            elif today_plan["session_type"] == "strength":
                lines.append(f"PLANNED: {today_plan['session_name']} (strength sessions do not show up in Garmin data)")
            else:
                t_km = f"{today_plan['target_km']:.0f} km" if today_plan['target_km'] else "N/A"
                t_vert = f"{today_plan['target_vert_m']:.0f}m vert" if today_plan['target_vert_m'] else "N/A"
                lines.append(f"PLANNED: {today_plan['session_name']}, {t_km}, {t_vert}, RPE {today_plan['target_rpe']}")
        else:
            lines.append("No plan for today (outside plan dates).")
        lines.append(f"DONE: No activity recorded for today -- the session above is from {activity_date.strftime('%A %d %B')}.")
        lines.append("")

    # ── Session Analysis ──
    lines.append("## Session Analysis")
    lines.append(f"**{name}**")
    # act_type is kept raw above for internal category matching
    # (_activity_category / assess_adherence); escape only at display.
    lines.append(f"- Type: {html.escape(act_type.replace('_', ' ').title())}")
    lines.append(f"- Distance: {dist_km} km | Duration: {fmt_duration(dur_min)}")
    lines.append(f"- Elevation: +{elev_m:.0f}m ({m_per_km}m/km)")
    lines.append(f"- Avg pace: {fmt_pace(avg_pace)}")
    if avg_hr:
        lines.append(f"- Avg HR: {avg_hr:.0f} bpm ({actual_zone}) | Max HR: {max_hr_act:.0f} bpm")
    if te:
        lines.append(f"- Training Effect: {te:.1f}/5.0")
    if vo2:
        lines.append(f"- VO2max: {vo2:.0f}")
    lines.append(f"- Calories: {calories:.0f} kcal")

    if m_per_km > 70:
        lines.append(f"- Mountain density: {m_per_km}m/km -- extremely vert-heavy")
    elif m_per_km > 40:
        lines.append(f"- Elevation density: {m_per_km}m/km -- solid mountain load")
    elif m_per_km < 10 and dist_km > 10:
        lines.append(f"- Flat session ({m_per_km}m/km)")

    if avg_pace and avg_hr and avg_hr > 0:
        speed_kmh = 60 / avg_pace
        efficiency = round(avg_hr / speed_kmh, 2)
        lines.append(f"- Efficiency index: {efficiency:.2f} (lower = more efficient)")
    lines.append("")

    # ── 4-week overview (abbreviated) ──
    if training_context:
        lines.append("## 4-Week Overview")
        lines.append(training_context)

    # ── Week Progress ──
    if week_progress:
        wp = week_progress
        lines.append("## Week Progress")
        lines.append(f"Target: **{wp['target_km']:.0f} km** / **{wp['target_vert']:.0f}m** vert ({wp['planned_sessions']} run sessions)")
        lines.append(f"Done: **{wp['actual_km']:.1f} km** / **{wp['actual_vert']:.0f}m** vert ({wp['actual_sessions']} sessions)")
        lines.append(f"Status: **{wp['status']}** -- {wp['km_pct']:.0f}% of km target, {wp['vert_pct']:.0f}% of vert target (day {wp['days_elapsed']}/{wp['days_total']})")
        lines.append("")

    # ── Tomorrow ──
    lines.append("## Tomorrow")
    if tomorrow_plan:
        tp = tomorrow_plan
        if tp["session_type"] == "rest":
            lines.append(f"**REST DAY.** {tp['description']}")
            lines.append(f"\"{tp['effort_description']}\"")
        elif tp["session_type"] == "strength":
            lines.append(f"**{tp['session_name']}**")
            lines.append(f"{tp['description']}")
            lines.append(f"Effort: RPE {tp['target_rpe']} -- \"{tp['effort_description']}\"")
        else:
            t_km = f"{tp['target_km']:.0f} km" if tp['target_km'] else ""
            t_vert = f", {tp['target_vert_m']:.0f}m vert" if tp['target_vert_m'] else ""
            t_zone = f", {tp['target_hr_zone']}" if tp['target_hr_zone'] else ""
            lines.append(f"**{tp['session_name']}** -- {t_km}{t_vert}{t_zone}, RPE {tp['target_rpe']}")
            lines.append(f"{tp['description']}")
            lines.append(f"\"{tp['effort_description']}\"")
    else:
        lines.append("No plan data for tomorrow.")
    lines.append("")

    # ── Phase Progress ──
    if phase_status:
        ps = phase_status
        lines.append("## Phase Progress")
        lines.append(f"**{ps['phase']}** (Week {ps['completed_weeks']} of {ps['total_weeks']}): **{ps['avg_compliance']:.0f}% compliance**")
        for w in ps["weeks"]:
            bar = "=" * int(min(w["compliance_pct"], 100) / 5) + "-" * (20 - int(min(w["compliance_pct"], 100) / 5))
            lines.append(f"- Week {w['week_number']}: [{bar}] {w['compliance_pct']:.0f}% ({w['actual_km']:.0f}/{w['target_km']:.0f} km, {w['sessions']} sessions)")
        lines.append("")

    # ── Recovery Prescription (plan-aware) ──
    lines.append("## Recovery Prescription")
    if plan and plan["session_type"] in ("vo2max", "threshold"):
        lines.append("- **Tonight**: 8-9hrs sleep. Non-negotiable after this intensity.")
        lines.append("- **Nutrition**: 1.6-2.0g protein/kg bodyweight. Carb refuel within 30min.")
        lines.append("- **Tomorrow**: Follow the plan. If it prescribes rest, honour it.")
    elif plan and plan.get("is_key_session"):
        lines.append("- **Tonight**: 7-8hrs sleep. Legs up if possible.")
        lines.append("- **Nutrition**: Solid carb + protein meal within 60min.")
        lines.append("- **Tomorrow**: Follow the plan. Key sessions demand proper recovery.")
    elif te and te >= 4.5:
        lines.append("- **Tonight**: 8-9hrs sleep. TE 4.5+ session demands full recovery.")
        lines.append("- **Nutrition**: 1.6-2.0g protein/kg bodyweight. Carb refuel within 30min.")
        lines.append("- **Tomorrow**: Easy Z2 only OR full rest. No quality work for 48hrs.")
    elif avg_hr and hr_zone(avg_hr) in ("Z4", "Z5"):
        lines.append("- **Tonight**: Prioritise sleep -- hard HR session needs full recovery.")
        lines.append("- **Tomorrow**: Full rest or 30min very easy jog only. HR must stay in Z1.")
    else:
        lines.append("- **Tonight**: Normal sleep (7hrs+).")
        lines.append("- **Tomorrow**: Follow the plan.")
    if elev_m > 1000:
        lines.append("- **Specific**: High elevation session -- quad foam rolling and calf stretching tonight.")
    lines.append("")

    # ── Race Countdown ──
    lines.append("## Race Countdown")
    lines.append(f"**{days_to_race} days to UTCT PT55 (Llandudno -> Gardens RC, 56.7km, +2644m).**")
    if days_to_race > 60:
        lines.append(f"Building the foundation. Consistency now pays dividends in November.")
    elif days_to_race > 30:
        lines.append(f"Deep in the work. Every quality session is a deposit into race-day fitness.")
    elif days_to_race > 14:
        lines.append(f"Peak phase. Trust the process. The hay is almost in the barn.")
    elif days_to_race > 7:
        lines.append(f"Taper time. Less is more. You will feel restless -- that means it is working.")
    elif days_to_race > 1:
        lines.append(f"Race week. Trust the work. You are ready.")
    else:
        lines.append(f"Race day. Leave nothing. PT55 rewards preparation, not heroics on Suther Peak.")
    lines.append("")

    # ── Quote ──
    quotes = [
        ("Jason Koop", "The biggest mistake ultrarunners make is running their easy days too hard and their hard days not hard enough."),
        ("Kilian Jornet", "I don't train to be ready for a race. I train to be ready for life in the mountains."),
        ("Joe Friel", "Aerobic capacity is built slowly, over years. It cannot be rushed -- only damaged."),
        ("Steve Magness", "Fatigue is a signal. The question is whether you are listening."),
        ("Courtney Dauwalter", "Embrace the suffering. It means you are doing it right."),
        ("Maffetone", "The faster you run slow, the faster you will run fast."),
        ("Scott Jurek", "Consistency over intensity. Every time."),
    ]
    author, quote = random.choice(quotes)
    lines.append("---")
    lines.append(f"*\"{quote}\"*")
    lines.append(f"-- **{author}**")

    return "\n".join(lines)


def build_rest_day_feedback(today_date, last_activity_date, plan, tomorrow_plan,
                             week_progress, phase_status):
    """Build feedback for a day with no activity recorded."""
    days_to_race = (RACE_DATE - today_date).days
    week_num = plan["week_number"] if plan else "?"
    phase = plan["phase"] if plan else "Pre-plan"

    total_weeks = get_total_weeks() or "?"
    lines = []
    lines.append(f"# Daily Training Feedback -- {today_date.strftime('%A %d %B %Y')}")
    lines.append(f"*Week {week_num} of {total_weeks} | {phase} | **{days_to_race} days to UTCT PT55***")
    lines.append("")

    # ── Plan vs Actual ──
    lines.append("## Today: Plan vs Actual")
    if plan:
        if plan["session_type"] == "rest":
            lines.append(f"PLANNED: {plan['session_name']} -- {plan['description']}")
            lines.append(f"DONE: No activity recorded")
            lines.append(f"ADHERENCE VERDICT: ON PLAN -- rest was prescribed and rest was taken. {plan['effort_description']}")
        elif plan["session_type"] == "strength":
            lines.append(f"PLANNED: {plan['session_name']}")
            lines.append(f"DONE: No Garmin activity recorded")
            lines.append(f"ADHERENCE VERDICT: UNCONFIRMED -- strength sessions do not show up in Garmin. "
                          f"If it was not done, log it manually; otherwise this week is quietly short a session.")
            lines.append(f"Reminder: {plan['description']}")
            lines.append(f"Effort target: RPE {plan['target_rpe']} -- \"{plan['effort_description']}\"")
        else:
            p_km = f"{plan['target_km']:.0f} km" if plan['target_km'] else "N/A"
            p_vert = f"{plan['target_vert_m']:.0f}m vert" if plan['target_vert_m'] else "N/A"
            lines.append(f"PLANNED: {plan['session_name']}, {p_km}, {p_vert}, RPE {plan['target_rpe']}")
            lines.append(f"DONE: Nothing recorded")
            is_key = plan.get("is_key_session", False)
            if is_key:
                lines.append(f"ADHERENCE VERDICT: MISSED -- this was a KEY SESSION. {plan['session_name']} is one of the critical sessions this week. Missing it creates a gap in your preparation that is hard to recover from. Can you reschedule within 48 hours?")
            else:
                lines.append(f"ADHERENCE VERDICT: MISSED -- {plan['session_name']} was on the plan today. Life happens, but it still counts against the weekly targets below.")
    else:
        lines.append("No plan for today.")
        lines.append("DONE: No activity recorded")
        lines.append("ADHERENCE VERDICT: No prescribed session today -- nothing to compare against.")
    lines.append("")

    # ── Days since last session ──
    if last_activity_date:
        days_off = (today_date - last_activity_date).days
        lines.append(f"Days since last session: **{days_off}**")
        if days_off <= 2:
            lines.append("Normal recovery window.")
        elif days_off <= 4:
            lines.append(f"{days_off} days off. Check in with how you are feeling -- illness, travel, or planned rest?")
        else:
            lines.append(f"{days_off} days without running. If unplanned, ease back with a short Z2 session tomorrow.")
        lines.append("")

    # ── Week Progress ──
    if week_progress:
        wp = week_progress
        lines.append("## Week Progress")
        lines.append(f"Target: **{wp['target_km']:.0f} km** / **{wp['target_vert']:.0f}m** vert ({wp['planned_sessions']} run sessions)")
        lines.append(f"Done: **{wp['actual_km']:.1f} km** / **{wp['actual_vert']:.0f}m** vert ({wp['actual_sessions']} sessions)")
        lines.append(f"Status: **{wp['status']}** -- {wp['km_pct']:.0f}% of km target (day {wp['days_elapsed']}/{wp['days_total']})")
        lines.append("")

    # ── Tomorrow ──
    lines.append("## Tomorrow")
    if tomorrow_plan:
        tp = tomorrow_plan
        if tp["session_type"] == "rest":
            lines.append(f"**REST DAY.** {tp['description']}")
        elif tp["session_type"] == "strength":
            lines.append(f"**{tp['session_name']}**")
            lines.append(f"{tp['description']}")
        else:
            t_km = f"{tp['target_km']:.0f} km" if tp['target_km'] else ""
            t_vert = f", {tp['target_vert_m']:.0f}m vert" if tp['target_vert_m'] else ""
            t_zone = f", {tp['target_hr_zone']}" if tp['target_hr_zone'] else ""
            lines.append(f"**{tp['session_name']}** -- {t_km}{t_vert}{t_zone}, RPE {tp['target_rpe']}")
            lines.append(f"{tp['description']}")
            lines.append(f"\"{tp['effort_description']}\"")
    else:
        lines.append("No plan data for tomorrow.")
    lines.append("")

    # ── Phase Progress ──
    if phase_status:
        ps = phase_status
        lines.append("## Phase Progress")
        lines.append(f"**{ps['phase']}** (Week {ps['completed_weeks']} of {ps['total_weeks']}): **{ps['avg_compliance']:.0f}% compliance**")
        lines.append("")

    # ── Recovery / Rest day guidance ──
    lines.append("## Recovery Prescription")
    if plan and plan["session_type"] == "rest":
        lines.append("- Rest day as prescribed. Well done.")
        lines.append("- 15-20min mobility work (hip flexors, glutes, calves)")
        lines.append("- Hydration: 2-3L water")
        lines.append("- Sleep 8hrs tonight to maximise adaptation")
    else:
        lines.append("- 15-20min mobility work (hip flexors, glutes, calves)")
        lines.append("- Hydration: 2-3L water")
        lines.append("- Sleep 8hrs tonight")
    lines.append("")

    # ── Race Countdown ──
    lines.append("## Race Countdown")
    lines.append(f"**{days_to_race} days to UTCT PT55.**")
    if plan and plan["session_type"] == "rest":
        lines.append("Rest is part of the plan. Adaptation happens during recovery, not during training.")
    elif plan and plan["session_type"] not in ("rest", "strength"):
        lines.append("Consistency is the single biggest predictor of race-day performance. Every missed session adds up.")
    lines.append("")

    return "\n".join(lines)


# ── Entry point ───────────────────────────────────────────────────────────────
@functions_framework.http
def garmin_daily_feedback(request):
    """HTTP Cloud Function entry point -- triggered by Cloud Scheduler."""
    try:
        client = load_garmin_client()
        recent = get_recent_activities(client, days=2)

        # Save all recent activities to BQ (deduped)
        for act in get_recent_activities(client, days=3):
            try:
                save_session_to_bq(act)
            except Exception as e:
                print(f"BQ save failed for activity: {e}")

        # Read training history for context
        training_context = None
        try:
            history = get_training_history(weeks=4)
            training_context = format_training_context(history)
        except Exception as e:
            print(f"BQ history read failed: {e}")

        # Get plan data
        today_date = datetime.today().date()
        plan = None
        tomorrow_plan = None
        week_progress = None
        phase_status = None
        try:
            plan = get_todays_plan(today_date)
            tomorrow_plan = get_tomorrows_plan(today_date)
            week_progress = get_week_progress(today_date)
            phase_status = get_phase_status(today_date)
        except Exception as e:
            print(f"Plan query failed: {e}")

        if not recent:
            # No activity -- rest day or missed session
            all_acts = client.get_activities(0, 5)
            last_date = None
            if all_acts:
                try:
                    last_date = datetime.fromisoformat((all_acts[0].get("startTimeLocal") or "")[:19]).date()
                except:
                    pass
            feedback = build_rest_day_feedback(
                today_date, last_date, plan, tomorrow_plan,
                week_progress, phase_status
            )
        else:
            # Activity found -- full analysis
            latest = sorted(recent, key=lambda x: x.get("startTimeLocal") or "", reverse=True)[0]
            all_recent_3d = get_recent_activities(client, days=3)

            # Key the adherence comparison to the ACTIVITY's own date, not
            # today's. get_recent_activities(days=2) can surface yesterday's
            # session on a day when today itself is prescribed rest -- scoring
            # it against today's plan produced confidently wrong verdicts
            # ("you ran on a rest day" for a run that was actually yesterday
            # and correctly taken). `plan` (today's) is passed through
            # separately as today_plan so today's real status still shows.
            try:
                activity_date = datetime.fromisoformat((latest.get("startTimeLocal") or "")[:19]).date()
            except Exception:
                activity_date = today_date
            if activity_date == today_date:
                activity_plan = plan
            else:
                try:
                    activity_plan = get_todays_plan(activity_date)
                except Exception as e:
                    print(f"Activity-date plan query failed: {e}")
                    activity_plan = None

            feedback = build_plan_aware_feedback(
                latest, all_recent_3d, today_date, activity_plan, tomorrow_plan,
                week_progress, phase_status, training_context,
                activity_date=activity_date, today_plan=plan, garmin_client=client
            )

        save_tokens_if_refreshed()

        today_label = datetime.today().strftime("%a %d %b")
        subject = f"Training Feedback -- {today_label}"
        email_sent = send_email(subject, feedback)

        print(feedback)
        if not email_sent:
            # Non-200 makes the failure visible in Cloud Logging / the
            # function's own error metrics instead of a silently-dropped
            # email reading as success (was: swallowed exception +
            # unconditional 200). NOTE: garmin-daily-feedback-7am's retryCount
            # is pinned to 0 (see A3 / 2026-08-25 memory entry) -- Scheduler
            # will NOT retry this; a genuine failure just waits for tomorrow's
            # scheduled run.
            return ("Email send failed -- see function logs", 502)
        return ("OK", 200)

    except Exception as e:
        print(f"Fatal error: {e}")
        # Raw exception text stays server-side only (Cloud Logging) -- the
        # HTTP response is generic so internal details (stack traces, BQ/
        # secret resource names, etc.) never leak to whatever can reach
        # this endpoint. Consistent with the 502 pattern above.
        return ("Internal error, see logs", 500)
