#!/usr/bin/env python3
import json
from datetime import datetime, timedelta
from collections import defaultdict

with open("garmin_running_data.json") as f:
    activities = json.load(f)

print(f"Total activities loaded: {len(activities)}")
print(f"Date range: {activities[0]['date']} → {activities[-1]['date']}\n")

# ── Overall totals ──────────────────────────────────────────────────────────
total_km     = sum(a["distance_km"] for a in activities)
total_hrs    = sum(a["duration_min"] for a in activities) / 60
total_elev   = sum(a["elevation_gain_m"] or 0 for a in activities)
total_cal    = sum(a["calories"] or 0 for a in activities)
n_trail      = sum(1 for a in activities if a["type"] == "trail_running")
n_road       = len(activities) - n_trail

print("=== OVERALL TOTALS (12 months) ===")
print(f"  Activities:        {len(activities)}  ({n_trail} trail / {n_road} road)")
print(f"  Distance:          {total_km:.1f} km")
print(f"  Time:              {total_hrs:.1f} hrs")
print(f"  Elevation gain:    {total_elev/1000:.1f} km")
print(f"  Calories:          {total_cal:,.0f} kcal")
print(f"  Avg distance/run:  {total_km/len(activities):.1f} km")
print(f"  Avg km/week:       {total_km/52:.1f} km")
print()

# ── Monthly breakdown ───────────────────────────────────────────────────────
monthly = defaultdict(lambda: {"km": 0, "hrs": 0, "elev": 0, "runs": 0})
for a in activities:
    m = a["date"][:7]
    monthly[m]["km"]   += a["distance_km"]
    monthly[m]["hrs"]  += a["duration_min"] / 60
    monthly[m]["elev"] += a["elevation_gain_m"] or 0
    monthly[m]["runs"] += 1

print("=== MONTHLY BREAKDOWN ===")
print(f"{'Month':<10} {'Runs':>5} {'Km':>8} {'Hours':>7} {'Elev(m)':>9}")
print("-" * 45)
for m in sorted(monthly):
    d = monthly[m]
    print(f"{m:<10} {d['runs']:>5} {d['km']:>8.1f} {d['hrs']:>7.1f} {d['elev']:>9.0f}")
print()

# ── Weekly breakdown (last 12 weeks) ───────────────────────────────────────
weekly = defaultdict(lambda: {"km": 0, "hrs": 0, "elev": 0, "runs": 0})
for a in activities:
    d = datetime.fromisoformat(a["date"])
    week = d.strftime("%Y-W%V")
    weekly[week]["km"]   += a["distance_km"]
    weekly[week]["hrs"]  += a["duration_min"] / 60
    weekly[week]["elev"] += a["elevation_gain_m"] or 0
    weekly[week]["runs"] += 1

recent_weeks = sorted(weekly)[-16:]
print("=== LAST 16 WEEKS ===")
print(f"{'Week':<12} {'Runs':>5} {'Km':>8} {'Hours':>7} {'Elev(m)':>9}")
print("-" * 47)
for w in recent_weeks:
    d = weekly[w]
    print(f"{w:<12} {d['runs']:>5} {d['km']:>8.1f} {d['hrs']:>7.1f} {d['elev']:>9.0f}")
print()

# ── Longest runs ────────────────────────────────────────────────────────────
print("=== TOP 10 LONGEST RUNS ===")
top_long = sorted(activities, key=lambda x: x["distance_km"], reverse=True)[:10]
for a in top_long:
    print(f"  {a['date']}  {a['distance_km']:>6.1f} km  {a['duration_min']:>6.1f} min  "
          f"+{a['elevation_gain_m'] or 0:>5.0f}m  [{a['type']}]  {a['name']}")
print()

# ── Biggest elevation runs ───────────────────────────────────────────────────
print("=== TOP 10 MOST ELEVATION ===")
top_elev = sorted(activities, key=lambda x: x["elevation_gain_m"] or 0, reverse=True)[:10]
for a in top_elev:
    print(f"  {a['date']}  {a['distance_km']:>6.1f} km  +{a['elevation_gain_m'] or 0:>5.0f}m  "
          f"[{a['type']}]  {a['name']}")
print()

# ── Heart rate analysis ──────────────────────────────────────────────────────
hrs = [a["avg_hr"] for a in activities if a["avg_hr"]]
if hrs:
    print("=== HEART RATE ===")
    print(f"  Avg HR across all runs: {sum(hrs)/len(hrs):.0f} bpm")
    print(f"  Min avg HR:             {min(hrs):.0f} bpm")
    print(f"  Max avg HR:             {max(hrs):.0f} bpm")
    # HR zones (rough)
    z2 = sum(1 for h in hrs if h < 145)
    z3 = sum(1 for h in hrs if 145 <= h < 160)
    z4 = sum(1 for h in hrs if 160 <= h < 175)
    z5 = sum(1 for h in hrs if h >= 175)
    print(f"  Zone 2 (<145):  {z2} runs ({z2/len(hrs)*100:.0f}%)")
    print(f"  Zone 3 (145-159): {z3} runs ({z3/len(hrs)*100:.0f}%)")
    print(f"  Zone 4 (160-174): {z4} runs ({z4/len(hrs)*100:.0f}%)")
    print(f"  Zone 5 (175+):  {z5} runs ({z5/len(hrs)*100:.0f}%)")
    print()

# ── VO2max trend ─────────────────────────────────────────────────────────────
vo2 = [(a["date"], a["vo2max"]) for a in activities if a["vo2max"]]
if vo2:
    print("=== VO2MAX TREND ===")
    # Show quarterly snapshots
    quarters = {}
    for date, v in vo2:
        q = date[:4] + "-Q" + str((int(date[5:7])-1)//3 + 1)
        quarters[q] = v
    for q in sorted(quarters):
        print(f"  {q}: {quarters[q]:.0f}")
    print(f"  Latest: {vo2[-1][1]:.0f}  (as of {vo2[-1][0]})")
    print()

# ── Pace analysis ────────────────────────────────────────────────────────────
paces = [a["avg_pace_min_km"] for a in activities if a["avg_pace_min_km"] and a["avg_pace_min_km"] < 15]
if paces:
    avg_pace = sum(paces)/len(paces)
    print("=== PACE ===")
    def fmt_pace(p):
        return f"{int(p)}:{int((p%1)*60):02d} /km"
    print(f"  Overall avg pace: {fmt_pace(avg_pace)}")
    trail_paces = [a["avg_pace_min_km"] for a in activities
                   if a["type"]=="trail_running" and a["avg_pace_min_km"] and a["avg_pace_min_km"]<15]
    road_paces  = [a["avg_pace_min_km"] for a in activities
                   if a["type"]!="trail_running" and a["avg_pace_min_km"] and a["avg_pace_min_km"]<15]
    if trail_paces:
        print(f"  Avg trail pace:   {fmt_pace(sum(trail_paces)/len(trail_paces))}")
    if road_paces:
        print(f"  Avg road pace:    {fmt_pace(sum(road_paces)/len(road_paces))}")
    print()

# ── Training consistency ─────────────────────────────────────────────────────
print("=== CONSISTENCY ===")
all_weeks = sorted(weekly)
if all_weeks:
    active_weeks = len(all_weeks)
    total_weeks = max(52, active_weeks)
    print(f"  Weeks with at least 1 run: {active_weeks}/52")
    km_vals = [weekly[w]["km"] for w in all_weeks]
    print(f"  Highest week:  {max(km_vals):.1f} km")
    print(f"  Lowest week:   {min(km_vals):.1f} km")
    print(f"  Median week:   {sorted(km_vals)[len(km_vals)//2]:.1f} km")
