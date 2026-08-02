#!/usr/bin/env python3
"""
Daily Garmin Connect session analyser — GCP Cloud Function version
Plan-aware training feedback for the Otter African Trail Run 2026.

Pulls yesterday's activity, compares against the 13-week training plan in BQ,
and generates coaching feedback with effort-intensity verdicts.

Inspired by: Jason Koop (ultrarunning), Joe Friel (triathlete's bible),
             Steve Magness (science of running), Maffetone (aerobic base)
"""

import json
import os
import re
import smtplib
import random
import time
import functions_framework
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from datetime import datetime, timedelta, date, timezone
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

# Race date: Otter Day 2 main race
RACE_DATE    = date(2026, 9, 24)
PLAN_START   = date(2026, 6, 29)

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
def _refresh_with_backoff(gc, max_attempts=3):
    """
    Pre-check token expiry and force a refresh before returning the client.
    Uses exponential backoff (10/20/40s) to handle Garmin 429 rate limits.
    Raises RuntimeError with '429' in the message if all attempts fail on rate-limit.
    """
    tok = gc.oauth2_token
    now = datetime.now(timezone.utc)
    exp = datetime.fromtimestamp(tok.expires_at, tz=timezone.utc)
    if not tok.expired:
        print(f"Access token valid until {exp} — no exchange needed.")
        return

    print(f"Access token expired at {exp}. Attempting refresh with backoff...")
    delay = 10
    for attempt in range(1, max_attempts + 1):
        try:
            gc.connectapi("/userprofile-service/userprofile/personal-information")
            print(f"Token refreshed successfully on attempt {attempt}.")
            return
        except Exception as e:
            err = str(e)
            if "429" in err:
                if attempt < max_attempts:
                    print(f"429 rate-limit on attempt {attempt}. Waiting {delay}s...")
                    time.sleep(delay)
                    delay *= 2
                else:
                    raise RuntimeError(f"429: Garmin rate-limit after {max_attempts} attempts. Try again in ~1hr.")
            else:
                raise  # non-429 errors propagate immediately


def load_garmin_client():
    """Load garth tokens from Secret Manager into /tmp, pre-check expiry, return authenticated client."""
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

    # Pre-check and refresh before handing client to callers — prevents silent 429s
    # inside get_activities() where the error is harder to catch and classify.
    _refresh_with_backoff(garth.client)

    return client


def save_tokens_if_refreshed():
    """Save refreshed garth tokens back to Secret Manager, only if the token changed."""
    try:
        # Read what's currently in SM to compare
        current_sm = get_secret("garmin-oauth2-token")
        garth.save(TOKEN_DIR)  # write current in-memory tokens to /tmp
        with open(f"{TOKEN_DIR}/oauth2_token.json") as f:
            new_token = f.read()

        # Skip writing a new SM version if the access token is identical
        current_at = json.loads(current_sm).get("access_token", "")
        new_at = json.loads(new_token).get("access_token", "")
        if current_at == new_at:
            print("Token unchanged — skipping Secret Manager write.")
            return

        update_secret("garmin-oauth2-token", new_token)
        print("Tokens saved to Secret Manager (new version created).")
    except Exception as e:
        print(f"Token save warning: {e}")

# ── Email ─────────────────────────────────────────────────────────────────────
def send_email(subject, markdown_body):
    try:
        gmail_user = get_secret("garmin-gmail-user")
        app_password = get_secret("garmin-gmail-app-password")
        recipient = gmail_user
        html = markdown_to_html(markdown_body)
        msg = MIMEMultipart("alternative")
        msg["Subject"] = subject
        msg["From"]    = f"Coach Aria <{gmail_user}>"
        msg["To"]      = recipient
        msg.attach(MIMEText(markdown_body, "plain"))
        msg.attach(MIMEText(html, "html"))
        with smtplib.SMTP_SSL("smtp.gmail.com", 465) as smtp:
            smtp.login(gmail_user, app_password)
            smtp.sendmail(gmail_user, recipient, msg.as_string())
        print("Email sent successfully")
    except Exception as e:
        print(f"Email failed: {e}")

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
        elif line.startswith("EFFORT VERDICT:"):
            # Special styling for effort verdicts
            if "NAILED IT" in line:
                html_lines.append(f'<p style="color:#2d6a4f;font-weight:700;font-size:15px;margin:10px 0;padding:8px;background:#e8f5e9;border-radius:6px">{line}</p>')
            elif "TOO EASY" in line or "NOT HARD ENOUGH" in line:
                html_lines.append(f'<p style="color:#e65100;font-weight:700;font-size:15px;margin:10px 0;padding:8px;background:#fff3e0;border-radius:6px">{line}</p>')
            elif "TOO HARD" in line:
                html_lines.append(f'<p style="color:#c62828;font-weight:700;font-size:15px;margin:10px 0;padding:8px;background:#ffebee;border-radius:6px">{line}</p>')
            else:
                html_lines.append(f'<p style="font-weight:700;margin:10px 0;padding:8px;background:#f5f5f5;border-radius:6px">{line}</p>')
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

# Expected HR ranges per session type for effort comparison
SESSION_HR_TARGETS = {
    "easy_trail":    {"min": 120, "max": 150, "zone": "Z1-Z2"},
    "easy_road":     {"min": 120, "max": 150, "zone": "Z1-Z2"},
    "long_run":      {"min": 135, "max": 160, "zone": "Z2"},
    "tempo":         {"min": 158, "max": 170, "zone": "Z3-Z4"},
    "threshold":     {"min": 167, "max": 178, "zone": "Z4"},
    "hill_repeats":  {"min": 160, "max": 178, "zone": "Z3-Z4"},
    "vo2max":        {"min": 175, "max": 192, "zone": "Z5"},
    "prologue_sim":  {"min": 170, "max": 188, "zone": "Z4-Z5"},
    "race_sim":      {"min": 145, "max": 168, "zone": "Z2-Z3"},
    "sharpener":     {"min": 165, "max": 180, "zone": "Z4-Z5"},
    "activation":    {"min": 120, "max": 145, "zone": "Z1"},
    "race":          {"min": 155, "max": 185, "zone": "Z2-Z5"},
}

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
    """Write a Garmin activity to BQ. Skips if activity_id already exists."""
    client = get_bq_client()
    activity_id = a.get("activityId")
    if not activity_id:
        return

    q = f"SELECT 1 FROM `{BQ_TABLE}` WHERE activity_id = {activity_id} LIMIT 1"
    result = list(client.query(q).result())
    if result:
        print(f"Activity {activity_id} already in BQ, skipping")
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

    row = {
        "activity_id": activity_id,
        "activity_name": a.get("activityName", "Unnamed"),
        "activity_type": a.get("activityType", {}).get("typeKey", "unknown"),
        "start_time": a.get("startTimeLocal", "")[:19].replace("T", " "),
        "distance_km": dist_km,
        "duration_min": dur_min,
        "elevation_gain_m": elev_m,
        "avg_hr": avg_hr,
        "max_hr": max_hr_val,
        "avg_pace_min_km": avg_pace,
        "aerobic_training_effect": a.get("aerobicTrainingEffect"),
        "vo2max": a.get("vO2MaxValue"),
        "calories": a.get("calories"),
        "elevation_density_m_km": m_per_km,
        "hr_zone": zone,
        "efficiency_index": efficiency,
        "inserted_at": datetime.utcnow().isoformat(),
    }

    errors = client.insert_rows_json(BQ_TABLE, [row])
    if errors:
        print(f"BQ insert error: {errors}")
    else:
        print(f"Saved activity {activity_id} to BQ")

# ── Plan queries ─────────────────────────────────────────────────────────────

def get_todays_plan(today_date):
    """Query BQ for today's planned session. Returns dict or None."""
    client = get_bq_client()
    q = f"""
    SELECT plan_date, week_number, phase, day_of_week, session_type, session_name,
           target_km, target_vert_m, target_duration_min, target_hr_zone,
           target_hr_max, target_rpe, week_target_km, week_target_vert,
           description, effort_description, is_key_session
    FROM `{BQ_PLAN}`
    WHERE plan_date = '{today_date.isoformat()}'
    LIMIT 1
    """
    rows = list(client.query(q).result())
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
    WHERE plan_date <= '{today_date.isoformat()}'
      AND plan_date >= DATE_SUB('{today_date.isoformat()}', INTERVAL 6 DAY)
    GROUP BY week_number, phase, week_target_km, week_target_vert
    ORDER BY week_number DESC
    LIMIT 1
    """
    plan_rows = list(client.query(q_plan).result())
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
    WHERE DATE(start_time) >= '{week_start.isoformat()}'
      AND DATE(start_time) <= '{today_date.isoformat()}'
    """
    actual_rows = list(client.query(q_actual).result())
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
    WHERE plan_date = '{today_date.isoformat()}'
    LIMIT 1
    """
    phase_rows = list(client.query(q_phase).result())
    if not phase_rows:
        return None
    current_phase = phase_rows[0].phase

    # Get all weeks in this phase
    q_weeks = f"""
    SELECT week_number, week_target_km, week_target_vert,
           MIN(plan_date) as week_start, MAX(plan_date) as week_end
    FROM `{BQ_PLAN}`
    WHERE phase = '{current_phase}'
    GROUP BY week_number, week_target_km, week_target_vert
    ORDER BY week_number
    """
    week_rows = list(client.query(q_weeks).result())

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
        WHERE DATE(start_time) >= '{wr.week_start.isoformat()}'
          AND DATE(start_time) <= '{wr.week_end.isoformat()}'
        """
        ar = list(client.query(q_actual).result())[0]

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


# ── Effort intensity comparison ──────────────────────────────────────────────

def assess_effort_intensity(plan, avg_hr, max_hr_act):
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
                f"Push harder next time -- the Otter climbs will not be forgiving. "
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


# ── Training history ─────────────────────────────────────────────────────────

def get_training_history(weeks=4):
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
        dt_str = a.get("startTimeLocal", "")[:19]
        try:
            dt = datetime.fromisoformat(dt_str)
            if dt >= cutoff:
                recent.append(a)
        except:
            pass
    return recent

# ── Main analysis (plan-aware) ───────────────────────────────────────────────

def build_plan_aware_feedback(a, all_recent, today_date, plan, tomorrow_plan,
                               week_progress, phase_status, training_context):
    """Build the full plan-aware feedback email."""
    name      = a.get("activityName", "Unnamed")
    dt_str    = a.get("startTimeLocal", "")[:19]
    dt        = datetime.fromisoformat(dt_str)
    act_type  = a.get("activityType", {}).get("typeKey", "running")
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

    # ── Header ──
    week_num = plan["week_number"] if plan else "?"
    phase = plan["phase"] if plan else "Pre-plan"
    lines.append(f"# Daily Training Feedback -- {dt.strftime('%A %d %B %Y')}")
    lines.append(f"*Week {week_num} of 13 | {phase} | **{days_to_race} days to Otter***")
    lines.append("")

    # ── Plan vs Actual ──
    lines.append("## Today: Plan vs Actual")
    if plan:
        p_km = f"{plan['target_km']:.0f} km" if plan['target_km'] else "N/A"
        p_vert = f"{plan['target_vert_m']:.0f}m vert" if plan['target_vert_m'] else "N/A"
        p_zone = plan['target_hr_zone'] or "N/A"
        p_rpe = plan['target_rpe'] or "N/A"
        lines.append(f"PLANNED: {plan['session_name']}, {p_km}, {p_vert}, {p_zone}, RPE {p_rpe}")
    else:
        lines.append("PLANNED: No plan for today (outside plan dates)")

    lines.append(f"DONE: {name}, {dist_km} km, +{elev_m:.0f}m vert, avg HR {avg_hr:.0f} ({actual_zone})" if avg_hr else f"DONE: {name}, {dist_km} km, +{elev_m:.0f}m vert")

    # ── Effort verdict ──
    if plan and plan["session_type"] not in ("rest", "strength"):
        verdict, explanation = assess_effort_intensity(plan, avg_hr, max_hr_act)
        if verdict:
            lines.append(f"EFFORT VERDICT: {verdict}")
            if explanation:
                lines.append(explanation)
    elif plan and plan["session_type"] == "rest":
        lines.append(f"EFFORT VERDICT: Today was a REST day. You ran anyway. Was this a planned swap? If so, make sure you take the rest day elsewhere this week.")
    elif plan and plan["session_type"] == "strength":
        lines.append(f"EFFORT VERDICT: Today was a STRENGTH day in the plan. The run is bonus volume -- make sure you still do the strength work.")
    lines.append("")

    # ── Session Analysis ──
    lines.append("## Session Analysis")
    lines.append(f"**{name}**")
    lines.append(f"- Type: {act_type.replace('_', ' ').title()}")
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
    if plan and plan["session_type"] in ("vo2max", "prologue_sim", "race_sim", "threshold"):
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
    lines.append(f"**{days_to_race} days to the Otter African Trail Run.**")
    if days_to_race > 60:
        lines.append(f"Building the foundation. Consistency now pays dividends in September.")
    elif days_to_race > 30:
        lines.append(f"Deep in the work. Every quality session is a deposit into race-day fitness.")
    elif days_to_race > 14:
        lines.append(f"Peak phase. Trust the process. The hay is almost in the barn.")
    elif days_to_race > 7:
        lines.append(f"Taper time. Less is more. You will feel restless -- that means it is working.")
    elif days_to_race > 1:
        lines.append(f"Race week. Trust the work. You are ready.")
    else:
        lines.append(f"Race day. Leave nothing. The Otter rewards preparation.")
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

    lines = []
    lines.append(f"# Daily Training Feedback -- {today_date.strftime('%A %d %B %Y')}")
    lines.append(f"*Week {week_num} of 13 | {phase} | **{days_to_race} days to Otter***")
    lines.append("")

    # ── Plan vs Actual ──
    lines.append("## Today: Plan vs Actual")
    if plan:
        if plan["session_type"] == "rest":
            lines.append(f"PLANNED: {plan['session_name']} -- {plan['description']}")
            lines.append(f"DONE: No activity recorded")
            lines.append(f"EFFORT VERDICT: NAILED IT -- rest was prescribed. {plan['effort_description']}")
        elif plan["session_type"] == "strength":
            lines.append(f"PLANNED: {plan['session_name']}")
            lines.append(f"DONE: No Garmin activity recorded")
            lines.append(f"Did you do the strength session? It will not appear in Garmin data.")
            lines.append(f"Reminder: {plan['description']}")
            lines.append(f"Effort target: RPE {plan['target_rpe']} -- \"{plan['effort_description']}\"")
        else:
            p_km = f"{plan['target_km']:.0f} km" if plan['target_km'] else "N/A"
            p_vert = f"{plan['target_vert_m']:.0f}m vert" if plan['target_vert_m'] else "N/A"
            lines.append(f"PLANNED: {plan['session_name']}, {p_km}, {p_vert}, RPE {plan['target_rpe']}")
            lines.append(f"DONE: Nothing recorded")
            is_key = plan.get("is_key_session", False)
            if is_key:
                lines.append(f"MISSED SESSION -- this was a KEY SESSION. {plan['session_name']} is one of the two critical sessions this week (quality Wednesday + long Sunday). Missing it creates a gap in your preparation that is hard to recover from. Can you reschedule within 48 hours?")
            else:
                lines.append(f"MISSED SESSION -- {plan['session_name']} was on the plan today. Life happens, but track the impact on your weekly targets below.")
    else:
        lines.append("No plan for today.")
        lines.append("DONE: No activity recorded")
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
    lines.append(f"**{days_to_race} days to the Otter African Trail Run.**")
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
                    last_date = datetime.fromisoformat(all_acts[0].get("startTimeLocal","")[:19]).date()
                except:
                    pass
            feedback = build_rest_day_feedback(
                today_date, last_date, plan, tomorrow_plan,
                week_progress, phase_status
            )
        else:
            # Activity found -- full analysis
            latest = sorted(recent, key=lambda x: x.get("startTimeLocal",""), reverse=True)[0]
            all_recent_3d = get_recent_activities(client, days=3)
            feedback = build_plan_aware_feedback(
                latest, all_recent_3d, today_date, plan, tomorrow_plan,
                week_progress, phase_status, training_context
            )

        save_tokens_if_refreshed()

        today_label = datetime.today().strftime("%a %d %b")
        subject = f"Training Feedback -- {today_label}"
        send_email(subject, feedback)

        print(feedback)
        return ("OK", 200)

    except Exception as e:
        err = str(e)
        print(f"Fatal error: {err}")
        if "429" in err:
            # Return 429 so Cloud Scheduler knows to back off and retry later
            return (f"Rate-limited by Garmin: {err}", 429)
        return (f"Error: {err}", 500)
