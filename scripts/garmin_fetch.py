#!/usr/bin/env python3
"""
Fetch trail running activities from Garmin Connect for the past year.
Usage: python3 garmin_fetch.py
"""

import json
import getpass
from datetime import datetime, timedelta
from garminconnect import Garmin

def fetch_running_activities():
    email = input("Garmin email: ")
    password = getpass.getpass("Garmin password: ")

    print("\nLogging in...")
    client = Garmin(email, password)
    client.login()
    print("Login successful.\n")

    # Date range: last 12 months
    end_date = datetime.today()
    start_date = end_date - timedelta(days=365)

    print(f"Fetching activities from {start_date.date()} to {end_date.date()}...")

    # Fetch all activities in batches
    all_activities = []
    start = 0
    limit = 100

    while True:
        batch = client.get_activities(start, limit)
        if not batch:
            break
        all_activities.extend(batch)
        start += limit
        if len(batch) < limit:
            break

    # Filter to running activities within the date range
    running_types = {
        "running", "trail_running", "track_running",
        "ultra_run", "obstacle_run", "virtual_run"
    }

    filtered = []
    for act in all_activities:
        act_type = act.get("activityType", {}).get("typeKey", "").lower()
        act_date_str = act.get("startTimeLocal", "")
        if not act_date_str:
            continue
        try:
            act_date = datetime.fromisoformat(act_date_str[:19])
        except ValueError:
            continue

        if act_type in running_types and start_date <= act_date <= end_date:
            filtered.append({
                "id": act.get("activityId"),
                "name": act.get("activityName"),
                "date": act_date_str[:10],
                "type": act_type,
                "distance_km": round((act.get("distance") or 0) / 1000, 2),
                "duration_min": round((act.get("duration") or 0) / 60, 1),
                "elevation_gain_m": act.get("elevationGain"),
                "avg_hr": act.get("averageHR"),
                "max_hr": act.get("maxHR"),
                "avg_pace_min_km": round(
                    (act.get("duration") or 0) / 60 / ((act.get("distance") or 1) / 1000), 2
                ) if act.get("distance") else None,
                "calories": act.get("calories"),
                "avg_speed_kmh": round((act.get("averageSpeed") or 0) * 3.6, 2),
                "training_effect": act.get("aerobicTrainingEffect"),
                "vo2max": act.get("vO2MaxValue"),
            })

    # Sort by date
    filtered.sort(key=lambda x: x["date"])

    output_file = "garmin_running_data.json"
    with open(output_file, "w") as f:
        json.dump(filtered, f, indent=2)

    print(f"\nFound {len(filtered)} running activities.")
    print(f"Data saved to: {output_file}")

    # Quick summary
    if filtered:
        total_km = sum(a["distance_km"] for a in filtered)
        total_min = sum(a["duration_min"] for a in filtered)
        total_elev = sum(a["elevation_gain_m"] or 0 for a in filtered)
        print(f"\nQuick summary:")
        print(f"  Total distance:     {total_km:.1f} km")
        print(f"  Total time:         {total_min/60:.1f} hours")
        print(f"  Total elevation:    {total_elev:.0f} m")
        print(f"  Avg per week:       {total_km / 52:.1f} km/week")

if __name__ == "__main__":
    fetch_running_activities()
