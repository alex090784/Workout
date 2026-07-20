#!/usr/bin/env python3
"""
Push per-session suggested route locations/links into intervals.icu workout events.

Reads route_location/route_url from BigQuery (alexct-training.garmin_training.training_plan)
for every non-rest running session from 2026-07-08 onward, matches each to the intervals.icu
calendar event on the same date, and appends
    Suggested route: <location> — <url>
to the event's description (idempotent — skips events that already contain the URL).

CREDENTIALS: intervals.icu API key. Get it from intervals.icu → Settings → Developer.
Provide it one of two ways:
    export INTERVALS_API_KEY=xxxxxxxx        # env var
    python3 push_routes_to_intervals.py --key xxxxxxxx

Athlete: i624738 (override with --athlete).
Auth model: HTTP Basic  username="API_KEY"  password=<api key>.
"""
import argparse, base64, json, os, subprocess, sys, urllib.request, urllib.error

ATHLETE = "0"  # intervals.icu: use "0" (=me) with a personal API key; explicit id i624738 returns 403
OLDEST, NEWEST = "2026-07-08", "2026-11-21"
BASE = "https://intervals.icu/api/v1"
BQ_TABLE = "alexct-training.garmin_training.training_plan"

def bq_rows():
    q = (f"SELECT CAST(plan_date AS STRING) d, route_location loc, route_url url "
         f"FROM `{BQ_TABLE}` WHERE plan_date >= '{OLDEST}' AND route_url IS NOT NULL "
         f"ORDER BY plan_date")
    out = subprocess.check_output(
        ["bq", "query", "--use_legacy_sql=false", "--format=json", "--max_rows=500", q])
    return json.loads(out)

def api(method, path, key, body=None):
    auth = base64.b64encode(f"API_KEY:{key}".encode()).decode()
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(f"{BASE}{path}", data=data, method=method)
    req.add_header("Authorization", f"Basic {auth}")
    req.add_header("Content-Type", "application/json")
    req.add_header("User-Agent", "aria-garmin-coach/1.0")
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.loads(r.read().decode() or "null")

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--key", default=os.environ.get("INTERVALS_API_KEY"))
    ap.add_argument("--athlete", default=ATHLETE)
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args()
    if not a.key:
        sys.exit("ERROR: no intervals.icu API key. Set INTERVALS_API_KEY or pass --key.")

    plan = {r["d"]: r for r in bq_rows()}
    print(f"BQ: {len(plan)} plan dates with a route link.")

    events = api("GET", f"/athlete/{a.athlete}/events?oldest={OLDEST}&newest={NEWEST}", a.key)
    print(f"intervals.icu: {len(events)} events in range.")

    updated = skipped = nomatch = 0
    for ev in events:
        d = (ev.get("start_date_local") or "")[:10]
        if ev.get("category") != "WORKOUT" or ev.get("type") != "Run" or d not in plan:
            continue
        row = plan[d]
        desc = ev.get("description") or ""
        if row["url"] in desc:
            skipped += 1
            continue
        line = f"Suggested route: {row['loc']} — {row['url']}"
        new_desc = (desc + ("\n\n" if desc else "") + line)
        if a.dry_run:
            print(f"  [dry] {d} ev{ev['id']}: + {line}")
            updated += 1
            continue
        api("PUT", f"/athlete/{a.athlete}/events/{ev['id']}", a.key,
            {"description": new_desc})
        print(f"  {d} ev{ev['id']}: updated")
        updated += 1

    for d in plan:
        if not any((e.get("start_date_local") or "")[:10] == d
                   and e.get("category") == "WORKOUT" for e in events):
            nomatch += 1
    print(f"\nDONE. updated={updated} already-had-link={skipped} plan-dates-with-no-event={nomatch}")

if __name__ == "__main__":
    main()
