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
table incrementally, not buffered in memory and lost on a crash.

KEYING RULE (do not weaken this): the diff is keyed on plan_date, resolved
FRESH against intervals.icu on every run -- never by a remembered/cached
event_id. The 2026-09-17 full rebuild proved event_id-based patching breaks
the moment a plan restructure moves a session to a different day.

REVISION HISTORY:
  2026-09-17 v1 (rev 00001-sef): first deploy.
  2026-09-17 v2 (this version): Rune's functional review before the first
  scheduled run found two CRITICAL defects and several IMPORTANT gaps. Fixed
  here -- see inline comments tagged [RUNE-CRITICAL-1], [RUNE-CRITICAL-2],
  [RUNE-3] etc. Scheduler was PAUSED the moment the CRITICALs were reported
  and stays paused until this version is deployed and re-verified.
  [RUNE-CRITICAL-1]: fetch_icu_events() used to do
  `{e["start_date_local"][:10]: e for e in r.json()}` -- a dict comprehension
  that silently collapses multiple events on the same date to whichever the
  API happened to list last, and the main loop never refreshed that snapshot
  after a mutation. Verified against real data before fixing: every one of
  the 287 rows in training_plan has a UNIQUE plan_date (queried directly,
  0 duplicates) -- so this was LATENT, not already triggered, and the 10
  earlier debugging invocations did not corrupt anything (independently
  reconfirmed against the live intervals.icu calendar itself, not the audit
  log, immediately after the report: 46/46 dates in the 45-day window match
  BQ 1:1, zero duplicate ICU dates, zero name mismatches, the one interval
  row re-checked still carries its correct RepeatGroupDTO structure). Still a
  real defect -- fixed properly below rather than left "safe for now."
  [RUNE-CRITICAL-2]: audit rows were built in memory and written ONCE, after
  the whole loop finished -- a crash mid-run left zero audit evidence for a
  run that may already have mutated the calendar, precisely the failure this
  job exists to prevent. Fixed: an IN_PROGRESS run row is written BEFORE the
  loop starts, each event's audit row is flushed immediately after that date
  is processed (not batched), and a second, final run row (same run_id,
  seq=1) is written at the end. A run_id whose only row has seq=0 and no
  seq=1 companion is itself the diagnostic signal of a crash mid-run.
"""
import hashlib
import json
import os
import re
import smtplib
import traceback
import uuid
from datetime import date, datetime, timedelta, timezone
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from zoneinfo import ZoneInfo

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

# [RUNE-4] the plan is authored in Alexis's local time, not the container's
# implicit timezone. Cloud Functions containers default to UTC, so this was
# "correct" so far only by coincidence (Cape Town is UTC+2 and the cron fires
# at 02:00 UTC, well clear of local midnight). Resolve explicitly instead of
# relying on that coincidence continuing to hold (DST doesn't apply in RSA,
# but Alexis travels -- see cape_town_route_library.md travel windows -- and
# a future schedule-time change would silently break this again).
ATHLETE_TZ = ZoneInfo("Africa/Johannesburg")

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

# [RUNE-6, cheap second layer] log the canonical file's sha256 at cold start
# so drift between this deploy directory's copy and the canonical
# shared/session_parser.py is at least OBSERVABLE in logs even though the
# real gate is now a build-time step (see Makefile). Computed once per
# container, not per request.
try:
    _PARSER_SHA256 = hashlib.sha256(
        open(os.path.join(os.path.dirname(__file__), "session_parser.py"), "rb").read()
    ).hexdigest()
    print(f"[cold-start] session_parser.py sha256: {_PARSER_SHA256}")
except Exception as _e:
    print(f"[cold-start] WARNING: could not hash session_parser.py: {_e}")


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
        return True
    except Exception as e:
        print(f"ALERT EMAIL FAILED TO SEND: {e}")
        return False


# ── BQ ────────────────────────────────────────────────────────────────────────
def get_bq_client():
    return bigquery.Client(project=BQ_PROJECT)


def fetch_plan_rows(client, window_start, window_end):
    """Returns (rows, dup_warnings). dup_warnings lists any plan_date that
    appears more than once in this window -- [RUNE-CRITICAL-1] fix also
    covers the BQ side: a genuine duplicate must never silently produce two
    CREATEs for the same calendar slot. Confirmed live 2026-09-17: 287/287
    training_plan rows have a unique plan_date today, so this branch is a
    guard against future data-quality regressions, not a currently-live case."""
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
    by_date = {}
    for r in rows:
        by_date.setdefault(r.plan_date.isoformat(), []).append(r)

    out = []
    dup_warnings = []
    for plan_date_str, rs in by_date.items():
        if len(rs) > 1:
            dup_warnings.append(
                f"{plan_date_str}: {len(rs)} training_plan rows share this date "
                f"({[r.session_type for r in rs]}) -- BQ data-integrity problem, "
                f"none of them processed this run to avoid guessing which is canonical."
            )
            continue
        r = rs[0]
        out.append({
            "plan_date": plan_date_str,
            "session_type": r.session_type,
            "session_name": r.session_name,
            "target_km": float(r.target_km) if r.target_km is not None else None,
            "target_duration_min": int(r.target_duration_min) if r.target_duration_min is not None else None,
            "target_hr_zone": r.target_hr_zone,
            "target_hr_max": r.target_hr_max,
            "description": r.description,
        })
    return out, dup_warnings


def write_run_row(client, run_row):
    """[RUNE-CRITICAL-2] one row per call -- used for BOTH the pre-loop
    IN_PROGRESS marker (seq=0) and the post-loop final row (seq=1). A run_id
    with a seq=0 row and no seq=1 companion is diagnostic of a mid-run crash.
    Returns True/False so the final-write failure path can escalate (see
    [RUNE-5] in the main handler)."""
    errors = client.insert_rows_json(AUDIT_RUNS, [run_row])
    if errors:
        print(f"WARNING: failed to write run audit row (seq={run_row.get('seq')}): {errors}")
        return False
    return True


def write_event_row(client, event_row):
    """[RUNE-CRITICAL-2] flush immediately, one row at a time, instead of
    buffering the whole run's events in memory. A crash after row 30 of 46
    still leaves rows 1-30 on record."""
    errors = client.insert_rows_json(AUDIT_EVENTS, [event_row])
    if errors:
        print(f"WARNING: failed to write event audit row ({event_row.get('plan_date')}): {errors}")


# ── intervals.icu ─────────────────────────────────────────────────────────────
def icu_auth():
    return ("API_KEY", get_secret("intervals-api-key"))


def fetch_icu_events(auth, window_start, window_end):
    """[RUNE-CRITICAL-1] returns date -> LIST of events, never collapsing
    same-date events into a single winner. Callers must resolve ambiguity
    explicitly (see resolve_existing_event) rather than silently picking
    "whichever the API listed last"."""
    r = requests.get(f"{ICU_BASE}/events",
                      params={"oldest": window_start, "newest": window_end},
                      auth=auth, headers=ICU_HEADERS, timeout=30)
    r.raise_for_status()
    by_date = {}
    for e in r.json():
        by_date.setdefault(e["start_date_local"][:10], []).append(e)
    return by_date


def icu_create(auth, payload):
    r = requests.post(f"{ICU_BASE}/events", json=payload, auth=auth, headers=ICU_HEADERS, timeout=30)
    r.raise_for_status()
    return r.json()


def icu_update(auth, event_id, payload):
    r = requests.put(f"{ICU_BASE}/events/{event_id}", json=payload, auth=auth, headers=ICU_HEADERS, timeout=30)
    r.raise_for_status()
    return r.json()


def resolve_existing_event(date_events, target_name):
    """[RUNE-CRITICAL-1] Given every intervals.icu event currently on this
    date (0, 1, or more) and the name we intend to write, decide which one
    (if any) this BQ row corresponds to. Returns (existing_event_or_None,
    anomaly_note_or_None). NEVER silently picks a winner among multiple
    un-attributable events -- that was exactly the defect (row A diffs
    against the wrong cached event, overwrites row B's content, row B then
    reports SKIP against stale data)."""
    if not date_events:
        return None, None
    if len(date_events) == 1:
        return date_events[0], None
    # More than one event already exists on this date. If exactly one of
    # them already has the exact name we're about to write, that's an
    # unambiguous match (e.g. a re-run after a partial previous write).
    exact = [e for e in date_events if e.get("name") == target_name]
    if len(exact) == 1:
        others = len(date_events) - 1
        return exact[0], (
            f"{others} OTHER unmatched event(s) also exist on this date "
            f"(ids: {[e['id'] for e in date_events if e is not exact[0]]}) -- "
            f"left untouched, not auto-deleted. Investigate manually."
        )
    # Genuinely ambiguous -- do not guess.
    return None, (
        f"AMBIGUOUS: {len(date_events)} events exist on this date and none "
        f"(or more than one) matches the target name exactly "
        f"(ids: {[e['id'] for e in date_events]}) -- skipped, not written."
    )


# ── DSL builder (structured interval workouts) ───────────────────────────────
# [DSL LESSON 1] A bare zone label in the intervals.icu step DSL (e.g. "Z4")
# defaults to a POWER-zone target, not heart rate, because Run sport-settings
# define both power_zones and hr_zones. Alexis has no running power meter, so
# a bare zone label silently produces a meaningless target. Every branch below
# that returns a zone token MUST include the explicit "HR" suffix -- do not
# add a new branch that returns a bare "Z_" without it.
# [DSL LESSON 2] This athlete's intervals.icu HR zones (Run: LTHR 172, max_hr
# 190) match the BQ plan's Z2-Z4 bpm bands almost exactly, but zones 5+ are
# compressed into a near-useless band (Z5 is a single bpm wide on this
# config). A plan row prescribing e.g. 178-186bpm cannot be represented as a
# zone label -- use "%LTHR" instead.
def hr_target_for_row(desc, target_hr_zone):
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


def sanitize_prose(text):
    """[CYRUS-IMPORTANT] intervals.icu parses the ENTIRE description field
    into workout_doc.steps -- not just the DSL block we deliberately append.
    A coach-authored line in BQ's free-text `description` that happens to
    start with "-" would be read as an additional structured step and pushed
    to the watch with an unintended HR/power target. None of the 28 current
    interval rows trigger this (checked), and BQ is first-party, but there is
    no guard against a future authoring change doing it by accident. Checked
    the full intervals.icu event schema (captured live, multiple real GETs,
    2026-09-17) for a separate non-parsed notes field -- there isn't one;
    `description` is the only text field and it is always parsed. So: strip
    the trigger character from any line that would otherwise be read as a
    step, on EVERY event (not just interval rows -- the same field is parsed
    for every session type, so an easy/rest day's prose is just as exposed).
    Meaning-preserving: a dash-led bullet still reads as a bullet, just with
    a visually near-identical bullet character instead of a literal hyphen,
    so it can never be mistaken for an intervals.icu step-DSL line."""
    lines = (text or "").split("\n")
    out = []
    for line in lines:
        stripped = line.lstrip()
        indent = line[:len(line) - len(stripped)]
        if stripped.startswith("-"):
            stripped = "\u2022" + stripped[1:]  # bullet, not a step-triggering hyphen
        out.append(indent + stripped)
    return "\n".join(out)


def build_target_event(row):
    """Returns (payload, detail_note). payload is exactly what we want this
    date's intervals.icu event to look like -- CREATE posts it as-is, UPDATE
    PUTs it over whatever currently exists, SKIP means it already matches."""
    plan_date = row["plan_date"]
    session_type = row["session_type"]
    icu_type = TYPE_MAP.get(session_type, "Run")
    category = "NOTE" if session_type == "rest" else "WORKOUT"
    desc = sanitize_prose(row["description"])
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


# [MINOR-7, verified 2026-09-17 against real GET /events responses across
# multiple live create/update round-trips this session] every one of these
# fields echoes back unchanged and under the same name -- name, description,
# type, category, moving_time, distance_target all confirmed present and
# stable. If intervals.icu ever renames/drops one of these, the symptom is
# "every row re-UPDATEs daily forever" (wasted calls, not corruption) --
# check this list first if that shows up in the audit table.
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

    # [RUNE-4] resolve the athlete's LOCAL date, not the container's implicit
    # timezone -- the plan is authored in Africa/Johannesburg local time.
    window_start = datetime.now(ATHLETE_TZ).date()
    window_end = window_start + timedelta(days=WINDOW_DAYS)

    bq_client = get_bq_client()

    # [RUNE-CRITICAL-2] write the IN_PROGRESS marker BEFORE any mutation.
    # A run_id stuck at seq=0 with no seq=1 companion is itself the
    # diagnostic signal of a crash mid-run.
    write_run_row(bq_client, {
        "run_id": run_id, "started_at": started_at.isoformat(), "finished_at": None,
        "status": "IN_PROGRESS", "dry_run": dry_run, "seq": 0,
        "window_start": window_start.isoformat(), "window_end": window_end.isoformat(),
        "rows_checked": None, "created": None, "updated": None, "skipped": None,
        "errors": None, "error_message": None, "warnings": None, "orphans": None,
    })

    created = updated = skipped = errors = 0
    warnings = []
    error_message = None
    processed_dates = set()
    orphan_dates = []

    try:
        plan_rows, dup_warnings = fetch_plan_rows(bq_client, window_start, window_end)
        warnings.extend(dup_warnings)

        # [RUNE-9] a 45-day window in an active training block should never
        # legitimately be empty. Zero rows is indistinguishable from "nothing
        # scheduled" vs "the query silently broke" -- flag it, don't stay quiet.
        if not plan_rows:
            warnings.append(
                f"BQ returned ZERO training_plan rows for {window_start}..{window_end}. "
                f"An active training block should never be empty for 45 days -- "
                f"treat as a probable query/schema regression, not 'nothing scheduled'."
            )

        auth = icu_auth()
        icu_by_date = fetch_icu_events(auth, window_start.isoformat(), window_end.isoformat())

        for row in plan_rows:
            plan_date = row["plan_date"]
            session_type = row["session_type"]
            processed_dates.add(plan_date)
            try:
                target, detail = build_target_event(row)
                date_events = icu_by_date.get(plan_date, [])
                existing, anomaly = resolve_existing_event(date_events, target["name"])
                if anomaly:
                    warnings.append(f"{plan_date}: {anomaly}")

                # [CYRUS-MINOR] existing["id"] comes straight from the
                # intervals.icu response and gets interpolated into the
                # update URL and written to the audit table -- shape-check
                # it before trusting it, rather than assuming the API always
                # returns a well-formed integer id.
                if existing is not None and not isinstance(existing.get("id"), int):
                    raise ValueError(
                        f"intervals.icu event on {plan_date} has a malformed/missing 'id' "
                        f"field ({existing.get('id')!r}) -- refusing to use it as an update target"
                    )

                if existing is None and anomaly is not None:
                    # Ambiguous multi-event date -- do not create or update,
                    # already logged as a warning above.
                    action = "ANOMALY"
                    icu_event_id = None
                else:
                    action = diff_action(existing, target)
                    icu_event_id = existing["id"] if existing else None
                    if not dry_run:
                        if action == "CREATE":
                            result = icu_create(auth, target)
                            icu_event_id = result.get("id")
                            icu_by_date[plan_date] = [result]  # [RUNE-CRITICAL-1] refresh
                        elif action == "UPDATE":
                            result = icu_update(auth, existing["id"], target)
                            icu_event_id = result.get("id")
                            # refresh in place, keep any untouched sibling anomalies
                            icu_by_date[plan_date] = [
                                result if e["id"] == existing["id"] else e
                                for e in date_events
                            ]

                if action == "CREATE":
                    created += 1
                elif action == "UPDATE":
                    updated += 1
                elif action == "SKIP":
                    skipped += 1
                # ANOMALY counted in neither -- surfaced via warnings + audit action

                if detail and action != "ANOMALY":
                    pass  # detail already carries assumption notes, written below
                write_event_row(bq_client, {
                    "run_id": run_id, "logged_at": datetime.now(timezone.utc).isoformat(),
                    "plan_date": plan_date, "session_type": session_type,
                    "action": action, "icu_event_id": icu_event_id,
                    "detail": detail if action != "ANOMALY" else anomaly, "dry_run": dry_run,
                })
            except Exception as row_err:
                errors += 1
                print(f"ERROR processing {plan_date} ({session_type}): {row_err}")
                write_event_row(bq_client, {
                    "run_id": run_id, "logged_at": datetime.now(timezone.utc).isoformat(),
                    "plan_date": plan_date, "session_type": session_type,
                    "action": "ERROR", "icu_event_id": None,
                    "detail": str(row_err), "dry_run": dry_run,
                })

        # [RUNE-3] orphan detection: an intervals.icu event on a date with no
        # BQ counterpart in this window (e.g. a plan row deleted after a
        # restructure) is otherwise invisible -- the loop above only ever
        # iterates BQ rows. Auto-delete is a legitimate deferral; silent
        # invisibility is not.
        orphan_dates = [d for d in icu_by_date if d not in processed_dates]
        for d in orphan_dates:
            for e in icu_by_date[d]:
                warnings.append(
                    f"ORPHAN: intervals.icu event {e['id']} ({e.get('name')!r}) on {d} "
                    f"has no corresponding training_plan row in this window -- not deleted, flagged only."
                )
                write_event_row(bq_client, {
                    "run_id": run_id, "logged_at": datetime.now(timezone.utc).isoformat(),
                    "plan_date": d, "session_type": None,
                    "action": "ORPHAN", "icu_event_id": e.get("id"),
                    "detail": f"no BQ row for this date in window; event name={e.get('name')!r}",
                    "dry_run": dry_run,
                })

        status = "SUCCESS" if errors == 0 else "PARTIAL_FAILURE"

    except Exception as top_err:
        status = "FAILURE"
        error_message = f"{top_err}\n{traceback.format_exc()}"
        print(f"TOP-LEVEL FAILURE: {error_message}")

    finished_at = datetime.now(timezone.utc)
    warnings_text = "\n".join(warnings) if warnings else None
    run_row_final = {
        "run_id": run_id, "started_at": started_at.isoformat(), "finished_at": finished_at.isoformat(),
        "status": status, "dry_run": dry_run, "seq": 1,
        "window_start": window_start.isoformat(), "window_end": window_end.isoformat(),
        "rows_checked": created + updated + skipped + errors,
        "created": created, "updated": updated, "skipped": skipped, "errors": errors,
        "error_message": error_message, "warnings": warnings_text, "orphans": len(orphan_dates),
    }

    # [RUNE-5] the audit write is the one guarantee this job makes -- its own
    # failure must never be swallowed into a print() while the run still
    # reports SUCCESS/200. If the FINAL row fails to write, force an alert
    # regardless of what `status` says, and force a non-2xx response.
    final_write_ok = write_run_row(bq_client, run_row_final)
    if not final_write_ok:
        send_alert_email(
            "AUDIT WRITE FAILED (run otherwise completed)",
            f"training-plan-sync run {run_id} finished with status={status} but the FINAL "
            f"audit row failed to write to {AUDIT_RUNS}. Per-row event audit is flushed "
            f"incrementally and should still be intact for run_id={run_id}, but the run "
            f"summary itself is missing/incomplete. Investigate BQ write permissions/quota.\n\n"
            f"{json.dumps(run_row_final, default=str)}"
        )
        status = "FAILURE"  # escalate -- the one guarantee failed

    print(json.dumps(run_row_final, default=str))

    if status != "SUCCESS" or warnings:
        if status == "SUCCESS":
            subject = f"completed with {len(warnings)} warning(s)"
        else:
            subject = "FAILED" if status == "FAILURE" else f"PARTIAL FAILURE ({errors} row errors)"
        send_alert_email(
            subject,
            f"training-plan-sync run {run_id}.\n\n"
            f"Status: {status}\ndry_run: {dry_run}\n"
            f"Window: {window_start} -> {window_end}\n"
            f"created={created} updated={updated} skipped={skipped} errors={errors} "
            f"orphans={len(orphan_dates)}\n\n"
            f"error_message:\n{error_message or '(none)'}\n\n"
            f"warnings:\n{warnings_text or '(none)'}"
        )

    if status != "SUCCESS":
        # [CYRUS-MINOR] the endpoint is IAM-private and Cyrus confirmed no
        # secret can leak via these strings (auth is passed as a tuple to
        # requests, never embedded in exception text), but the raw traceback
        # still has no business in an HTTP response body. Full detail goes to
        # Cloud Logging (print above), the BQ audit row, and the alert email
        # -- the caller (Cloud Scheduler) only needs enough to know it failed.
        public_body = {
            "run_id": run_id, "status": status,
            "created": created, "updated": updated, "skipped": skipped, "errors": errors,
            "detail": "See Cloud Logging / intervals_sync_runs / alert email for full detail.",
        }
        return (json.dumps(public_body), 500)

    return (json.dumps(run_row_final, default=str), 200)
