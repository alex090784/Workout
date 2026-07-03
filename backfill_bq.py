#!/usr/bin/env python3
"""
One-time backfill: pull ~6 months of Garmin activities and insert into BigQuery.
Uses local garth tokens (~/.garth/).

Usage:
    ~/garmin_venv/bin/python3 ~/projects/garmin/backfill_bq.py
"""

import os
from datetime import datetime, timedelta
from garminconnect import Garmin
from google.cloud import bigquery
from google.cloud import secretmanager
import garth

BQ_PROJECT = "abmtest-429810"
BQ_TABLE = f"{BQ_PROJECT}.garmin_training.training_sessions"
GARTH_DIR = "/tmp/.garth_backfill"
SECRET_PROJECT = "abm2020"

# HR Zones (Friel LT-based, LT=176)
ZONES = {
    "Z1": (0,   141),
    "Z2": (141, 158),
    "Z3": (158, 167),
    "Z4": (167, 178),
    "Z5": (178, 999),
}

def hr_zone(hr):
    if not hr:
        return None
    for z, (lo, hi) in ZONES.items():
        if lo <= hr < hi:
            return z
    return "Z5"

def get_secret(secret_id):
    client = secretmanager.SecretManagerServiceClient()
    name = f"projects/{SECRET_PROJECT}/secrets/{secret_id}/versions/latest"
    response = client.access_secret_version(request={"name": name})
    return response.payload.data.decode("utf-8")

def main():
    # Load garth tokens from Secret Manager
    os.makedirs(GARTH_DIR, exist_ok=True)
    oauth2 = get_secret("garmin-oauth2-token")
    oauth1 = get_secret("garmin-oauth1-token")
    with open(f"{GARTH_DIR}/oauth2_token.json", "w") as f:
        f.write(oauth2)
    with open(f"{GARTH_DIR}/oauth1_token.json", "w") as f:
        f.write(oauth1)

    garth.resume(GARTH_DIR)
    client = Garmin()
    client.garth = garth.client

    bq = bigquery.Client(project=BQ_PROJECT)

    # Get existing activity IDs to skip
    print("Checking existing activities in BQ...")
    existing = set()
    for row in bq.query(f"SELECT activity_id FROM `{BQ_TABLE}`").result():
        existing.add(row.activity_id)
    print(f"Found {len(existing)} existing activities in BQ")

    # Pull activities — Garmin API returns max 100 per call
    print("Fetching activities from Garmin Connect...")
    all_activities = []
    start = 0
    batch_size = 100
    cutoff = datetime.now() - timedelta(days=365)

    while True:
        batch = client.get_activities(start, batch_size)
        if not batch:
            break
        for a in batch:
            dt_str = a.get("startTimeLocal", "")[:19]
            try:
                dt = datetime.fromisoformat(dt_str)
                if dt < cutoff:
                    break
                all_activities.append(a)
            except:
                pass
        else:
            start += batch_size
            continue
        break  # inner break hit cutoff

    print(f"Fetched {len(all_activities)} activities from last 6 months")

    # Insert into BQ
    rows_to_insert = []
    skipped = 0
    for a in all_activities:
        activity_id = a.get("activityId")
        if not activity_id or activity_id in existing:
            skipped += 1
            continue

        dist_km = round((a.get("distance") or 0) / 1000, 2)
        dur_min = round((a.get("duration") or 0) / 60, 1)
        elev_m = round(a.get("elevationGain") or 0, 0)
        avg_hr = a.get("averageHR")
        max_hr_val = a.get("maxHR")
        avg_pace = round((a.get("duration") or 0) / 60 / ((a.get("distance") or 1) / 1000), 2) if a.get("distance") else None
        m_per_km = round(elev_m / dist_km, 1) if dist_km else 0
        zone = hr_zone(avg_hr)
        speed_kmh = 60 / avg_pace if avg_pace and avg_pace > 0 else None
        efficiency = round(avg_hr / speed_kmh, 2) if avg_hr and speed_kmh else None

        rows_to_insert.append({
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
        })

    print(f"Skipped {skipped} (already in BQ or no ID)")
    print(f"Inserting {len(rows_to_insert)} new activities...")

    if rows_to_insert:
        # Insert in batches of 50
        for i in range(0, len(rows_to_insert), 50):
            batch = rows_to_insert[i:i+50]
            errors = bq.insert_rows_json(BQ_TABLE, batch)
            if errors:
                print(f"⚠️  Errors in batch {i//50 + 1}: {errors}")
            else:
                print(f"✅ Batch {i//50 + 1}: inserted {len(batch)} rows")

    print(f"\nDone! Total activities in BQ: {len(existing) + len(rows_to_insert)}")

if __name__ == "__main__":
    main()
