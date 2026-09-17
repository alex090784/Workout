#!/usr/bin/env python3
"""One-time backfill: stamp training-plan-sync's identity tag (external_id)
onto every intervals.icu event created by the 2026-09-17 full rebuild.

WHY THIS EXISTS: Rune's re-check of training-plan-sync found that trusting
"the lone event on this date" as an unconditional match (regardless of name)
was unsafe -- it couldn't tell a legitimate restructure-driven session-type
change apart from a manually-added personal entry or a stale orphan. The fix
makes resolve_existing_event() require a persisted identity tag
(external_id = "training-plan-sync:<plan_date>") before trusting a match.
That tag is set automatically on every future create/update, but the 256
events already sitting on intervals.icu from the 2026-09-17 rebuild predate
the tagging scheme and have none -- without this backfill, EVERY one of them
would show as "UNTAGGED" on the next sync run and be skipped entirely,
effectively making the sync inert until the plan drifted far enough to need
CREATEs for genuinely new dates.

SAFE TO RUN ONCE, VERIFIED BEFORE EACH RUN: this script re-verifies the full
BQ<->intervals.icu 1:1 match (same date, same session_name) for every event
before tagging it, and refuses to tag anything that doesn't match exactly.
It only ever PUTs a single field (external_id) -- never touches name,
description, or workout_doc.

Usage: python3 backfill_sync_tags.py            # dry run, prints what it would tag
       python3 backfill_sync_tags.py --confirm  # actually PUT the tags
"""
import sys
import time

import requests
from google.cloud import bigquery, secretmanager

PROJECT_ID = "abm2020"
BQ_PROJECT = "abmtest-429810"
BQ_PLAN = f"{BQ_PROJECT}.garmin_training.training_plan"
ICU_ATHLETE_ID = "i624738"
ICU_BASE = f"https://intervals.icu/api/v1/athlete/{ICU_ATHLETE_ID}"
HEADERS = {"Content-Type": "application/json", "User-Agent": "Mozilla/5.0 (backfill_sync_tags)"}
SYNC_TAG_PREFIX = "training-plan-sync:"


def get_secret(secret_id):
    client = secretmanager.SecretManagerServiceClient()
    name = f"projects/{PROJECT_ID}/secrets/{secret_id}/versions/latest"
    return client.access_secret_version(request={"name": name}).payload.data.decode("utf-8")


def main():
    confirm = "--confirm" in sys.argv

    bq_client = bigquery.Client(project=BQ_PROJECT)
    rows = list(bq_client.query(
        f"SELECT plan_date, session_name FROM `{BQ_PLAN}` WHERE plan_date >= CURRENT_DATE()"
    ).result())
    bq_by_date = {r.plan_date.isoformat(): r.session_name for r in rows}
    print(f"BQ rows (>= today): {len(bq_by_date)}")

    auth = ("API_KEY", get_secret("intervals-api-key"))
    window_start = min(bq_by_date)
    window_end = max(bq_by_date)
    r = requests.get(f"{ICU_BASE}/events", params={"oldest": window_start, "newest": window_end},
                      auth=auth, headers=HEADERS, timeout=30)
    r.raise_for_status()
    icu_events = r.json()
    print(f"ICU events in range: {len(icu_events)}")

    icu_by_date = {}
    dupes = []
    for e in icu_events:
        d = e["start_date_local"][:10]
        if d in icu_by_date:
            dupes.append(d)
        icu_by_date[d] = e

    if dupes:
        print(f"REFUSING: duplicate ICU dates found ({dupes}) -- not a safe 1:1 state, fix first.")
        sys.exit(1)

    to_tag, skip_untagged_mismatch, already_tagged = [], [], []
    for plan_date, session_name in bq_by_date.items():
        e = icu_by_date.get(plan_date)
        if e is None:
            print(f"SKIP {plan_date}: no ICU event exists yet (will be CREATEd by the sync itself, already tagged then)")
            continue
        if e.get("external_id"):
            already_tagged.append(plan_date)
            continue
        if e.get("name") != session_name:
            skip_untagged_mismatch.append((plan_date, session_name, e.get("name")))
            continue
        to_tag.append((plan_date, e["id"]))

    print(f"\nAlready tagged: {len(already_tagged)}")
    print(f"Name mismatch (NOT tagged, needs manual review): {len(skip_untagged_mismatch)}")
    for m in skip_untagged_mismatch:
        print("  ", m)
    print(f"To tag now: {len(to_tag)}")

    if not confirm:
        print("\nDRY RUN -- pass --confirm to actually PUT the tags.")
        return

    ok, fail = 0, 0
    for plan_date, event_id in to_tag:
        tag = f"{SYNC_TAG_PREFIX}{plan_date}"
        resp = requests.put(f"{ICU_BASE}/events/{event_id}", json={"external_id": tag},
                             auth=auth, headers=HEADERS, timeout=30)
        if resp.status_code == 200 and resp.json().get("external_id") == tag:
            ok += 1
        else:
            fail += 1
            print(f"FAILED to tag {plan_date} (event {event_id}): {resp.status_code} {resp.text[:200]}")
        time.sleep(0.1)

    print(f"\nTagged: {ok}, failed: {fail}")


if __name__ == "__main__":
    main()
