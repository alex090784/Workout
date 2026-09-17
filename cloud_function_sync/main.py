#!/usr/bin/env python3
"""training-plan-sync -- Cloud Function (2nd gen), europe-west1, project abm2020.

Keeps Alexis's intervals.icu calendar in sync with the BQ training plan
(abmtest-429810.garmin_training.training_plan), which is the sole source of
truth. intervals.icu is the relay that pushes structured workouts on to
Garmin Connect (its own nightly job, ~6-day lookahead) -- this function never
talks to Garmin directly.

WHY THIS EXISTS (2026-09-17 architecture review, Kai): the previous state of
the world was a single undocumented, unscheduled, ad hoc push to intervals.icu
on 2026-08-16 that nobody logged anywhere. It went stale for a month with zero
visibility before Alexis noticed intervals.icu "hadn't changed" after a BQ plan
restructure. This function exists specifically to make that failure mode
impossible: it runs daily, it fails LOUDLY (alert email + non-2xx response) if
it can't do its job, and every single row it touches is written to a BQ audit
table, not a comment in a memory file only Kai remembers to check.

KEYING RULE (do not weaken this): the diff is keyed on (plan_date, session_type)
from BQ, resolved fresh against intervals.icu by DATE on every run -- never by
a remembered/cached intervals.icu event_id. The 2026-09-17 full rebuild proved
event_id-based patching breaks the moment a plan restructure moves a session
to a different day (a Tuesday that held "Strength A" under the old plan held a
Threshold run under the new one -- patching the old event by ID would have
silently married the wrong content to the wrong day). Always resolve "what,
if anything, currently sits on this date" fresh; never trust a stored ID.

DSL LESSONS (expensive to discover during the 2026-09-17 rebuild -- do not
rediscover them):
  1. A bare zone label in the intervals.icu step DSL (e.g. "Z4") defaults to
     a POWER-zone target, not heart rate, because Run sport-settings define
     both power_zones and hr_zones. Alexis has no running power meter, so a
     bare zone label silently produces a meaningless target. ALWAYS write the
     explicit "Z4 HR" (or "Z4-Z5 HR" for a zone range) suffix.
  2. This athlete's intervals.icu HR zones (Run: LTHR 172, max_hr 190) match
     the BQ plan's Z2-Z4 bpm bands almost exactly, but zones 5+ are compressed
     into a near-useless band (Z5 is a single bpm wide on this config). A plan
     row prescribing e.g. 178-186bpm cannot be represented as a zone label --
     use "%LTHR" instead (e.g. 178/172=103%, 186/172=108% -> "103-108% LTHR").
     See hr_target_for_row() below.
"""
import json
import os
import re
import smtplib
import traceback
import uuid
from datetime import date, datetime, timedelta, timezone
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

import functions_framework
import requests
from google.cloud import bigquery, secretmanager

from session_parser import INTERVAL_SESSION_TYPES, _parse_session_structure, parse_recovery_minutes

# ── Config ───────────────────────────────────────────────────────────────────
PROJECT_ID   = "abm2020"
BQ_PROJECT   = "abmtest-429810"
BQ_DATASET   = "garmin_training"
BQ_PLAN      = f"{BQ_PROJECT}.{BQ_DATASET}.training_plan"
AUDIT_RUNS   = f"{BQ_PROJECT}.{BQ_DATASET}.intervals_sync_runs"
AUDIT_EVENTS = f"{BQ_PROJECT}.{BQ_DATASET}.intervals_sync_events"

ICU_ATHLETE_ID = "i624738"           # Alex0907 -- not sensitive, matches existing convention
ICU_BASE       = f"https://intervals.icu/api/v1/athlete/{ICU_ATHLETE_ID}"
ICU_HEADERS    = {"Content-Type": "application/json", "User-Agent": "Mozilla/5.0 (training-plan-sync)"}

WINDOW_DAYS = 45
LTHR = 172  # intervals.icu Run sport-settings, confirmed live 2026-09-17

TYPE_MAP = {
    "strength": "WeightTraining", "activation": "Run", "bike": "Ride",
    "mtb": "MountainBikeRide", "easy_trail": "Run", "long_run": "Run",
    "recce": "Run", "threshold": "Run", "vo2max": "Run", "hill_repeats": "Run",
    "sharpener": "Run", "downhill": "Run", "race": "Run", "rest": None,
}

# Text-parsing exceptions confirmed by manual read of all 28 interval rows at
# rebuild time (2026-09-17) -- recovery duration not stated as a number in the
# plan text. Both are judgment calls, not parsed facts; flagged in the audit
# `detail` column whenever hit, never silently baked in.
HILL_JOG_DOWN_NO_TIME = {"2027-03-20", "2027-03-28"}       # "jog down recovery", no minutes
SHARPENER_FULL_RECOVERY_NO_TIME = {"2026-11-10"}            # "full recovery", no minutes
CHECKPOINT_SINGLE_EFFORT = {"2027-03-12"}                   # 1x90min continuous, not a rep set

REP_BPM_RE = re.compile(r'@\s*Z\d(?:-Z\d)?\s*\(([\d]+)-([\d]+)\)')


# ── Secret Manager ────────────────────────────────────────────────────────────
def get_secret(secret_id):
    client = secretmanager.SecretManagerServiceClient()
    name = f"projects/{PROJECT_ID}/secrets/{secret_id}/versions/latest"
    return client.access_secret_version(request={"name": name}).payload.data.decode("utf-8")


# ── Failure alerting (fail LOUDLY -- this is the entire point of this function) ──
def send_alert_email(subject, body):
    """Best-effort. If this itself fails, the caller still returns non-2xx --
    an unsent alert email must never be mistaken for a successful run."""
    try:
        user = get_secret("garmin-gmail-user")
        app_password = get_secret("garmin-gmail-app-password")
        msg = MIMEMultipart()
        msg["From"] = user
        msg["To"] = user
        msg["Subject"] = f"[training-plan-sync] {subject}"
        msg.attach(MIMEText(body, "plain"))
        with smtplib.SMTP("smtp.gmail.com", 587) as server:
            server.starttls()
            server.login(user, app_password)
            server.send_message(msg)
        print("Alert email sent.")
    except Exception as e:
        print(f"ALERT EMAIL FAILED TO SEND: {e}")


# ── BQ ────────────────────────────────────────────────────────────────────────
def get_bq_client():
    return bigquery.Client(project=BQ_PROJECT)


def fetch_plan_rows(client, window_start, window_end):
    q = f"""
        SELECT plan_date, session_type, session_name, target_km, target_duration_min,
               target_hr_zone, target_hr_max, description
        FROM `{BQ_PLAN}`
        WHERE plan_date >= @window_start AND plan_date <= @window_end
        ORDER BY plan_date
    """
    job_config = bigquery.QueryJobConfig(query_parameters=[
        bigquery.ScalarQueryParameter("window_start", "DATE", window_start),
        bigquery.ScalarQueryParameter("window_end", "DATE", window_end),
    ])
    rows = list(client.query(q, job_config=job_config).result())
    out = []
    for r in rows:
        out.append({
            "plan_date": r.plan_date.isoformat(),
            "session_type": r.session_type,
            "session_name": r.session_name,
            "target_km": float(r.target_km) if r.target_km is not None else None,
            "target_duration_min": int(r.target_duration_min) if r.target_duration_min is not None else None,
            "target_hr_zone": r.target_hr_zone,
            "target_hr_max": r.target_hr_max,
            "description": r.description,
        })
    return out


def write_audit(client, run_row, event_rows):
    errors = client.insert_rows_json(AUDIT_RUNS, [run_row])
    if errors:
        print(f"WARNING: failed to write run audit row: {errors}")
    if event_rows:
        errors = client.insert_rows_json(AUDIT_EVENTS, event_rows)
        if errors:
            print(f"WARNING: failed to write {len(event_rows)} event audit rows: {errors}")


# ── intervals.icu ─────────────────────────────────────────────────────────────
def icu_auth():
    return ("API_KEY", get_secret("intervals-api-key"))


def fetch_icu_events(auth, window_start, window_end):
    r = requests.get(f"{ICU_BASE}/events",
                      params={"oldest": window_start, "newest": window_end},
                      auth=auth, headers=ICU_HEADERS, timeout=30)
    r.raise_for_status()
    return {e["start_date_local"][:10]: e for e in r.json()}


def icu_create(auth, payload):
    r = requests.post(f"{ICU_BASE}/events", json=payload, auth=auth, headers=ICU_HEADERS, timeout=30)
    r.raise_for_status()
    return r.json()


def icu_update(auth, event_id, payload):
    r = requests.put(f"{ICU_BASE}/events/{event_id}", json=payload, auth=auth, headers=ICU_HEADERS, timeout=30)
    r.raise_for_status()
    return r.json()


# ── DSL builder (structured interval workouts) ───────────────────────────────
def hr_target_for_row(desc, target_hr_zone):
    """LESSON 1: always the explicit '... HR' suffix -- see module docstring.
    LESSON 2: Z5+ is compressed on this athlete's config -- use %LTHR there."""
    if target_hr_zone in ("Z3-Z4", "Z4"):
        return "Z4 HR"
    if target_hr_zone == "Z4-Z5":
        return "Z4-Z5 HR"
    if target_hr_zone == "Z5":
        m = REP_BPM_RE.search(desc)
        lo, hi = (int(m.group(1)), int(m.group(2))) if m else (178, 186)
        return f"{round(lo / LTHR * 100)}-{round(hi / LTHR * 100)}% LTHR"
    return "Z4 HR"  # shouldn't be reached for INTERVAL_SESSION_TYPES rows


def recovery_minutes(desc, plan_date, rep_minutes):
    rec = parse_recovery_minutes(desc)
    if rec is not None:
        return rec, None
    if plan_date in HILL_JOG_DOWN_NO_TIME:
        return float(rep_minutes), "assumed recovery = climb duration ('jog down recovery', no time stated)"
    if plan_date in SHARPENER_FULL_RECOVERY_NO_TIME:
        return 3.0, "assumed 3min recovery, matching sibling 2026-11-03 sharpener row ('full recovery', no time stated)"
    return None, "no recovery duration found and no exception rule matched"


def build_dsl(row):
    desc = row["description"] or ""
    plan_date = row["plan_date"]
    struct = _parse_session_structure(desc)
    warmup_km, cooldown_km = struct["warmup_km"], struct["cooldown_km"]
    rep_count, rep_minutes = struct["rep_count"], struct["rep_minutes"]

    if warmup_km is None or cooldown_km is None or rep_minutes is None:
        return None, "missing warmup_km/cooldown_km/rep_minutes -- cannot build structured DSL"

    hr_target = hr_target_for_row(desc, row["target_hr_zone"])
    lines = [f"- Warmup {warmup_km:g}km Z1 HR", ""]
    assumption_note = None

    if plan_date in CHECKPOINT_SINGLE_EFFORT or rep_count == 1:
        lines.append(f"- {rep_minutes}m {hr_target}")
    else:
        rec_min, note = recovery_minutes(desc, plan_date, rep_minutes)
        assumption_note = note if note and rec_min is not None else None
        if rec_min is None:
            return None, note
        rec_str = f"{rec_min:g}m" if rec_min == int(rec_min) else f"{int(rec_min*60)}s"
        lines.append(f"Main Set {rep_count}x")
        lines.append(f"- {rep_minutes}m {hr_target}")
        lines.append(f"- {rec_str} Z1 HR")

    lines += ["", f"- Cooldown {cooldown_km:g}km Z1 HR"]
    return "\n".join(lines), assumption_note


def build_target_event(row):
    """Returns (payload, detail_note). payload is exactly what we want this
    date's intervals.icu event to look like -- CREATE posts it as-is, UPDATE
    PUTs it over whatever currently exists, SKIP means it already matches."""
    plan_date = row["plan_date"]
    session_type = row["session_type"]
    icu_type = TYPE_MAP.get(session_type, "Run")
    category = "NOTE" if session_type == "rest" else "WORKOUT"
    desc = row["description"] or ""
    detail = None

    if session_type in INTERVAL_SESSION_TYPES:
        dsl, note = build_dsl(row)
        if dsl:
            desc = desc.rstrip() + "\n\n" + dsl
            detail = note  # may be an assumption note, or None
        else:
            detail = f"FELL BACK TO PROSE (no DSL): {note}"

    payload = {
        "start_date_local": f"{plan_date}T07:00:00",
        "category": category,
        "name": row["session_name"],
        "description": desc,
    }
    if icu_type:
        payload["type"] = icu_type
    if category == "WORKOUT" and session_type not in INTERVAL_SESSION_TYPES:
        if row.get("target_duration_min"):
            payload["moving_time"] = int(row["target_duration_min"] * 60)
        if row.get("target_km"):
            payload["distance_target"] = row["target_km"] * 1000
    return payload, detail


COMPARE_KEYS = ("name", "description", "type", "category", "moving_time", "distance_target")


def diff_action(existing, target):
    if existing is None:
        return "CREATE"
    for k in COMPARE_KEYS:
        if k not in target:
            continue
        if existing.get(k) != target.get(k):
            return "UPDATE"
    return "SKIP"


# ── Main entry point ──────────────────────────────────────────────────────────
@functions_framework.http
def training_plan_sync(request):
    run_id = str(uuid.uuid4())
    started_at = datetime.now(timezone.utc)
    dry_run = str(request.args.get("dry_run", "false")).lower() in ("1", "true", "yes")

    window_start = date.today()
    window_end = window_start + timedelta(days=WINDOW_DAYS)

    created = updated = skipped = errors = 0
    event_rows = []
    error_message = None

    try:
        bq_client = get_bq_client()
        plan_rows = fetch_plan_rows(bq_client, window_start, window_end)
        # Defensive belt-and-suspenders: never act on anything before today,
        # even though the SQL WHERE clause already enforces it.
        plan_rows = [r for r in plan_rows if date.fromisoformat(r["plan_date"]) >= window_start]

        auth = icu_auth()
        icu_by_date = fetch_icu_events(auth, window_start.isoformat(), window_end.isoformat())

        for row in plan_rows:
            plan_date = row["plan_date"]
            session_type = row["session_type"]
            try:
                target, detail = build_target_event(row)
                existing = icu_by_date.get(plan_date)
                action = diff_action(existing, target)

                icu_event_id = existing["id"] if existing else None
                if not dry_run:
                    if action == "CREATE":
                        result = icu_create(auth, target)
                        icu_event_id = result.get("id")
                    elif action == "UPDATE":
                        result = icu_update(auth, existing["id"], target)
                        icu_event_id = result.get("id")

                if action == "CREATE":
                    created += 1
                elif action == "UPDATE":
                    updated += 1
                else:
                    skipped += 1

                event_rows.append({
                    "run_id": run_id, "logged_at": datetime.now(timezone.utc).isoformat(),
                    "plan_date": plan_date, "session_type": session_type,
                    "action": action, "icu_event_id": icu_event_id,
                    "detail": detail, "dry_run": dry_run,
                })
            except Exception as row_err:
                errors += 1
                print(f"ERROR processing {plan_date} ({session_type}): {row_err}")
                event_rows.append({
                    "run_id": run_id, "logged_at": datetime.now(timezone.utc).isoformat(),
                    "plan_date": plan_date, "session_type": session_type,
                    "action": "ERROR", "icu_event_id": None,
                    "detail": str(row_err), "dry_run": dry_run,
                })

        status = "SUCCESS" if errors == 0 else "PARTIAL_FAILURE"

    except Exception as top_err:
        status = "FAILURE"
        error_message = f"{top_err}\n{traceback.format_exc()}"
        print(f"TOP-LEVEL FAILURE: {error_message}")

    finished_at = datetime.now(timezone.utc)
    run_row = {
        "run_id": run_id, "started_at": started_at.isoformat(), "finished_at": finished_at.isoformat(),
        "status": status, "dry_run": dry_run,
        "window_start": window_start.isoformat(), "window_end": window_end.isoformat(),
        "rows_checked": created + updated + skipped + errors,
        "created": created, "updated": updated, "skipped": skipped, "errors": errors,
        "error_message": error_message,
    }

    # Write audit trail even on failure -- best-effort, wrapped so a BQ write
    # problem on top of everything else doesn't crash the alerting path below.
    try:
        write_audit(get_bq_client(), run_row, event_rows)
    except Exception as audit_err:
        print(f"AUDIT WRITE FAILED: {audit_err}")

    print(json.dumps(run_row, default=str))

    if status != "SUCCESS":
        subject = "FAILED" if status == "FAILURE" else f"PARTIAL FAILURE ({errors} row errors)"
        send_alert_email(
            subject,
            f"training-plan-sync run {run_id} did not complete cleanly.\n\n"
            f"Status: {status}\ndry_run: {dry_run}\n"
            f"Window: {window_start} -> {window_end}\n"
            f"created={created} updated={updated} skipped={skipped} errors={errors}\n\n"
            f"error_message:\n{error_message or '(see per-row errors in intervals_sync_events)'}"
        )
        return (json.dumps(run_row, default=str), 500)

    return (json.dumps(run_row, default=str), 200)
