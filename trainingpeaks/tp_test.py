#!/usr/bin/env python3
"""
TrainingPeaks unofficial API test
Authenticates and pulls planned + completed workouts
"""
import requests
import json
import getpass
from datetime import datetime, timedelta

email    = input("TrainingPeaks email: ")
password = getpass.getpass("TrainingPeaks password: ")

print("\nAuthenticating...")

# ── Step 1: Authenticate ─────────────────────────────────────────────────────
auth_url = "https://oauth.trainingpeaks.com/OAuth/token"
payload = {
    "grant_type":  "password",
    "client_id":   "trainingpeaks",
    "username":    email,
    "password":    password,
    "scope":       "trainingpeaks.v1"
}
r = requests.post(auth_url, data=payload)

if r.status_code != 200:
    print(f"Auth failed: {r.status_code} — {r.text}")
    exit(1)

data       = r.json()
token      = data.get("access_token")
athlete_id = data.get("UserId") or data.get("userId")
print(f"Login successful. Athlete ID: {athlete_id}")

headers = {"Authorization": f"Bearer {token}"}

# ── Step 2: Get athlete profile ──────────────────────────────────────────────
profile_url = f"https://tpapi.trainingpeaks.com/fitness/v1/athletes/{athlete_id}"
profile = requests.get(profile_url, headers=headers)
print(f"\nProfile status: {profile.status_code}")
if profile.status_code == 200:
    p = profile.json()
    print(f"Name: {p.get('firstName')} {p.get('lastName')}")
    print(f"Timezone: {p.get('timezone')}")

# ── Step 3: Pull workouts (last 7 days + next 30 days) ──────────────────────
start = (datetime.today() - timedelta(days=7)).strftime("%Y-%m-%d")
end   = (datetime.today() + timedelta(days=30)).strftime("%Y-%m-%d")

workouts_url = f"https://tpapi.trainingpeaks.com/fitness/v1/athletes/{athlete_id}/workouts/{start}/{end}"
print(f"\nFetching workouts {start} → {end}...")
wr = requests.get(workouts_url, headers=headers)
print(f"Workouts status: {wr.status_code}")

if wr.status_code == 200:
    workouts = wr.json()
    print(f"Found {len(workouts)} workouts\n")

    for w in workouts[:10]:  # Show first 10
        planned_date = w.get("workoutDay", "")[:10]
        title        = w.get("title") or w.get("workoutTypeValueId") or "Untitled"
        sport        = w.get("workoutTypeValueId", "")
        completed    = w.get("completed", False)
        tss_planned  = w.get("tssPlanned")
        dist_planned = round((w.get("distancePlanned") or 0) / 1000, 1)
        dur_planned  = round((w.get("totalTimePlanned") or 0) / 3600, 1)
        desc         = (w.get("description") or "")[:100]

        status = "✓ done" if completed else "○ planned"
        print(f"  {planned_date}  [{status}]  {title}")
        print(f"    Sport: {sport}  |  {dist_planned}km  |  {dur_planned}hrs  |  TSS: {tss_planned}")
        if desc:
            print(f"    Notes: {desc}")
        print()

    # Save full dump
    with open("tp_workouts_raw.json", "w") as f:
        json.dump(workouts, f, indent=2)
    print(f"Full data saved to tp_workouts_raw.json")

else:
    print(f"Error: {wr.text}")

# ── Step 4: Try metrics / fitness data ──────────────────────────────────────
metrics_url = f"https://tpapi.trainingpeaks.com/fitness/v1/athletes/{athlete_id}/metrics/{start}/{end}"
mr = requests.get(metrics_url, headers=headers)
print(f"\nMetrics status: {mr.status_code}")
if mr.status_code == 200:
    metrics = mr.json()
    print(f"Metrics entries: {len(metrics)}")
    if metrics:
        sample = metrics[-1]
        print(f"Latest: CTL={sample.get('chronicalTrainingLoad')}, "
              f"ATL={sample.get('acuteTrainingLoad')}, "
              f"TSB={sample.get('trainingStressBalance')}")
