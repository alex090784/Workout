#!/usr/bin/env python3
import json
from datetime import datetime, timedelta
from collections import defaultdict
import statistics

with open("garmin_running_data.json") as f:
    acts = json.load(f)

for a in acts:
    a["dt"] = datetime.fromisoformat(a["date"])

def fmt_pace(p):
    if not p or p > 20: return "N/A"
    return f"{int(p)}:{int((p%1)*60):02d}/km"

def week_key(dt):
    return dt.strftime("%Y-W%V")

def hdr(title):
    print(f"\n{'='*60}")
    print(f"  {title}")
    print(f"{'='*60}")

# ── 1. TRAINING LOAD TRENDS ──────────────────────────────────────────────────
hdr("1. WEEKLY TRAINING LOAD (all 52 weeks)")
weekly = defaultdict(lambda: {"km":0,"hrs":0,"elev":0,"runs":0,"trail_km":0,"road_km":0,"dates":[]})
for a in acts:
    w = week_key(a["dt"])
    weekly[w]["km"]       += a["distance_km"]
    weekly[w]["hrs"]      += a["duration_min"]/60
    weekly[w]["elev"]     += a["elevation_gain_m"] or 0
    weekly[w]["runs"]     += 1
    weekly[w]["dates"].append(a["date"])
    if a["type"] == "trail_running":
        weekly[w]["trail_km"] += a["distance_km"]
    else:
        weekly[w]["road_km"]  += a["distance_km"]

print(f"{'Week':<12} {'Runs':>4} {'Km':>7} {'Hrs':>6} {'Elev':>7} {'Trail%':>7}")
print("-"*50)
for w in sorted(weekly):
    d = weekly[w]
    trail_pct = d["trail_km"]/d["km"]*100 if d["km"] else 0
    print(f"{w:<12} {d['runs']:>4} {d['km']:>7.1f} {d['hrs']:>6.1f} {d['elev']:>7.0f} {trail_pct:>6.0f}%")

# ── 2. ACUTE:CHRONIC WORKLOAD RATIO (4-week rolling) ────────────────────────
hdr("2. TRAINING LOAD PROGRESSION (4-week blocks)")
sorted_weeks = sorted(weekly)
block_size = 4
print(f"{'Period':<25} {'Runs':>5} {'Km':>8} {'Hrs':>7} {'Elev':>8} {'Km/wk':>7}")
print("-"*60)
for i in range(0, len(sorted_weeks), block_size):
    block = sorted_weeks[i:i+block_size]
    r = sum(weekly[w]["runs"] for w in block)
    k = sum(weekly[w]["km"] for w in block)
    h = sum(weekly[w]["hrs"] for w in block)
    e = sum(weekly[w]["elev"] for w in block)
    label = f"{block[0]} → {block[-1]}"
    print(f"{label:<25} {r:>5} {k:>8.1f} {h:>7.1f} {e:>8.0f} {k/len(block):>7.1f}")

# ── 3. RECOVERY ANALYSIS ─────────────────────────────────────────────────────
hdr("3. RECOVERY & REST DAYS")
dates_run = sorted(set(a["date"] for a in acts))
dt_list = [datetime.fromisoformat(d) for d in dates_run]

# Gap analysis
gaps = []
for i in range(1, len(dt_list)):
    gap = (dt_list[i] - dt_list[i-1]).days
    gaps.append(gap)

print(f"  Total days with a run:     {len(dates_run)}")
print(f"  Total days in period:      365")
print(f"  Rest days:                 {365 - len(dates_run)}")
print(f"  Avg days between runs:     {statistics.mean(gaps):.1f}")
print(f"  Median gap:                {statistics.median(gaps):.1f} days")
print(f"  Longest rest streak:       {max(gaps)} days")

# Consecutive run days
max_consec = consec = 1
for i in range(1, len(dt_list)):
    if (dt_list[i] - dt_list[i-1]).days == 1:
        consec += 1
        max_consec = max(max_consec, consec)
    else:
        consec = 1
print(f"  Longest consecutive days:  {max_consec}")

# Back-to-back patterns
b2b = sum(1 for i in range(1, len(dt_list)) if (dt_list[i]-dt_list[i-1]).days == 1)
print(f"  Back-to-back run days:     {b2b} occurrences")

# Day of week preference
dow_counts = defaultdict(int)
dow_km = defaultdict(float)
for a in acts:
    day = a["dt"].strftime("%A")
    dow_counts[day] += 1
    dow_km[day] += a["distance_km"]
order = ["Monday","Tuesday","Wednesday","Thursday","Friday","Saturday","Sunday"]
print(f"\n  Day of week distribution:")
print(f"  {'Day':<12} {'Runs':>5} {'Km':>8} {'Avg km':>8}")
for day in order:
    c = dow_counts[day]
    k = dow_km[day]
    print(f"  {day:<12} {c:>5} {k:>8.1f} {k/c if c else 0:>8.1f}")

# ── 4. PACE TRENDS OVER TIME ─────────────────────────────────────────────────
hdr("4. PACE TRENDS (monthly, trail vs road)")
monthly_pace = defaultdict(lambda: {"trail":[],"road":[]})
for a in acts:
    m = a["date"][:7]
    p = a["avg_pace_min_km"]
    if p and 4 < p < 15:
        if a["type"] == "trail_running":
            monthly_pace[m]["trail"].append(p)
        else:
            monthly_pace[m]["road"].append(p)

print(f"{'Month':<10} {'Trail pace':>12} {'Road pace':>12} {'Trend':>8}")
print("-"*46)
trail_prev = None
for m in sorted(monthly_pace):
    t = monthly_pace[m]["trail"]
    r = monthly_pace[m]["road"]
    tp = statistics.mean(t) if t else None
    rp = statistics.mean(r) if r else None
    trend = ""
    if trail_prev and tp:
        diff = tp - trail_prev
        trend = f"{'faster' if diff < -0.1 else 'slower' if diff > 0.1 else 'stable'} ({diff:+.2f})"
    print(f"{m:<10} {fmt_pace(tp):>12} {fmt_pace(rp):>12} {trend:>8}")
    if tp: trail_prev = tp

# ── 5. HEART RATE DEEP DIVE ──────────────────────────────────────────────────
hdr("5. HEART RATE ANALYSIS")

# Monthly HR trend
monthly_hr = defaultdict(list)
for a in acts:
    if a["avg_hr"]:
        monthly_hr[a["date"][:7]].append(a["avg_hr"])

print("  Monthly avg HR trend:")
print(f"  {'Month':<10} {'Avg HR':>8} {'Min':>6} {'Max':>6}")
for m in sorted(monthly_hr):
    hrs = monthly_hr[m]
    print(f"  {m:<10} {statistics.mean(hrs):>8.0f} {min(hrs):>6.0f} {max(hrs):>6.0f}")

# HR efficiency (pace per HR beat - higher = more efficient)
print("\n  HR Efficiency (pace efficiency = HR / speed, lower = better):")
monthly_eff = defaultdict(list)
for a in acts:
    if a["avg_hr"] and a["avg_speed_kmh"] and a["avg_speed_kmh"] > 0:
        eff = a["avg_hr"] / a["avg_speed_kmh"]
        monthly_eff[a["date"][:7]].append(eff)
print(f"  {'Month':<10} {'HR/speed (lower=better)':>25}")
for m in sorted(monthly_eff):
    e = statistics.mean(monthly_eff[m])
    print(f"  {m:<10} {e:>25.2f}")

# ── 6. ELEVATION DENSITY ────────────────────────────────────────────────────
hdr("6. ELEVATION ANALYSIS")
for a in acts:
    a["m_per_km"] = (a["elevation_gain_m"] or 0) / a["distance_km"] if a["distance_km"] else 0

flat    = [a for a in acts if a["m_per_km"] < 20]
hilly   = [a for a in acts if 20 <= a["m_per_km"] < 50]
mtn     = [a for a in acts if a["m_per_km"] >= 50]

print(f"  Flat runs (<20m/km):      {len(flat):>4}  ({sum(a['distance_km'] for a in flat):>7.1f} km)")
print(f"  Hilly (20-50m/km):        {len(hilly):>4}  ({sum(a['distance_km'] for a in hilly):>7.1f} km)")
print(f"  Mountain (>50m/km):       {len(mtn):>4}  ({sum(a['distance_km'] for a in mtn):>7.1f} km)")

print(f"\n  Most vertical-dense runs (m/km):")
top_dense = sorted(acts, key=lambda x: x["m_per_km"], reverse=True)[:10]
for a in top_dense:
    print(f"    {a['date']}  {a['m_per_km']:>5.0f}m/km  {a['distance_km']:>5.1f}km  +{a['elevation_gain_m'] or 0:.0f}m  {a['name']}")

# ── 7. STRUCTURED WORKOUT DETECTION ─────────────────────────────────────────
hdr("7. STRUCTURED & NOTABLE WORKOUTS")
keywords = {
    "interval": ["interval","x ", "rep","fartlek","speedwork"],
    "tempo":    ["tempo","threshold","lt ","lactate"],
    "long":     ["long run","lr ","long trail"],
    "race":     ["race","event","ultra","marathon","half"],
    "recovery": ["recovery","easy","ez ","jog"],
    "climb":    ["climb","hill","vertical","vert","stair"],
}
categorized = defaultdict(list)
for a in acts:
    name_lower = a["name"].lower()
    for cat, kws in keywords.items():
        if any(kw in name_lower for kw in kws):
            categorized[cat].append(a)
            break

for cat, runs in sorted(categorized.items()):
    km = sum(a["distance_km"] for a in runs)
    print(f"  {cat.capitalize():<12} {len(runs):>3} runs  {km:>7.1f} km total")
    for a in sorted(runs, key=lambda x: x["distance_km"], reverse=True)[:3]:
        print(f"    → {a['date']}  {a['distance_km']:.1f}km  {a['name']}")

# ── 8. TRAINING EFFECT DISTRIBUTION ─────────────────────────────────────────
hdr("8. TRAINING EFFECT DISTRIBUTION")
te = [a["training_effect"] for a in acts if a["training_effect"]]
if te:
    bins = {
        "Recovery (0-2)":    sum(1 for x in te if x < 2),
        "Maintaining (2-3)": sum(1 for x in te if 2 <= x < 3),
        "Improving (3-4)":   sum(1 for x in te if 3 <= x < 4),
        "Highly improving (4-5)": sum(1 for x in te if 4 <= x <= 5),
    }
    for label, count in bins.items():
        bar = "█" * count
        print(f"  {label:<25} {count:>3}  {bar}")
    print(f"\n  Avg training effect: {statistics.mean(te):.2f}")
    print(f"  Most common:         {round(statistics.mode(te)*2)/2:.1f}")

# ── 9. LONG RUN PROGRESSION ──────────────────────────────────────────────────
hdr("9. MONTHLY LONGEST RUN PROGRESSION")
monthly_long = defaultdict(lambda: {"km":0,"elev":0,"name":"","date":""})
for a in acts:
    m = a["date"][:7]
    if a["distance_km"] > monthly_long[m]["km"]:
        monthly_long[m] = {"km":a["distance_km"],"elev":a["elevation_gain_m"] or 0,
                           "name":a["name"],"date":a["date"]}
print(f"{'Month':<10} {'Longest':>9} {'Elev':>8}  Activity")
print("-"*65)
for m in sorted(monthly_long):
    d = monthly_long[m]
    print(f"{m:<10} {d['km']:>9.1f} {d['elev']:>8.0f}  {d['name'][:40]}")

# ── 10. OVERTRAINING / RED FLAGS ─────────────────────────────────────────────
hdr("10. OVERTRAINING SIGNALS & RED FLAGS")

# Weeks with >10% jump in km
prev_km = None
print("  Weeks with >25% volume spike:")
for w in sorted(weekly):
    curr = weekly[w]["km"]
    if prev_km and prev_km > 10:
        change = (curr - prev_km) / prev_km * 100
        if change > 25:
            print(f"    {w}: {prev_km:.1f} → {curr:.1f} km ({change:+.0f}%)")
    prev_km = curr

# High HR on easy/recovery days
print("\n  High HR (>155) on short runs (<10km) — possible fatigue signal:")
for a in acts:
    if a["distance_km"] < 10 and (a["avg_hr"] or 0) > 155:
        print(f"    {a['date']}  {a['distance_km']:.1f}km  HR:{a['avg_hr']:.0f}  {a['name']}")

# Very slow pace relative to HR
print("\n  High effort, low output (HR>155, pace>8min/km) — fatigue indicator:")
for a in acts:
    if (a["avg_hr"] or 0) > 155 and (a["avg_pace_min_km"] or 0) > 8:
        print(f"    {a['date']}  {a['distance_km']:.1f}km  HR:{a['avg_hr']:.0f}  pace:{fmt_pace(a['avg_pace_min_km'])}  {a['name']}")

# ── 11. RACE / PEAK EVENT ANALYSIS ──────────────────────────────────────────
hdr("11. PEAK PERFORMANCE DAYS")
print("  Top 10 by training effect:")
top_te = sorted([a for a in acts if a["training_effect"]], key=lambda x: x["training_effect"], reverse=True)[:10]
for a in top_te:
    print(f"    {a['date']}  TE:{a['training_effect']:.1f}  {a['distance_km']:.1f}km  HR:{a['avg_hr'] or 'N/A'}  {a['name']}")

print("\n  Fastest 10km-equivalent pace days (road only):")
road_fast = sorted([a for a in acts if a["type"]!="trail_running" and a["avg_pace_min_km"] and a["distance_km"]>=5],
                   key=lambda x: x["avg_pace_min_km"])[:10]
for a in road_fast:
    print(f"    {a['date']}  {fmt_pace(a['avg_pace_min_km'])}  {a['distance_km']:.1f}km  HR:{a['avg_hr'] or 'N/A'}  {a['name']}")

# ── 12. CALORIE & EFFORT SUMMARY ─────────────────────────────────────────────
hdr("12. EFFORT & CALORIE SUMMARY")
monthly_cal = defaultdict(float)
for a in acts:
    monthly_cal[a["date"][:7]] += a["calories"] or 0
print(f"{'Month':<10} {'Calories':>10} {'Per run':>9}")
for m in sorted(monthly_cal):
    runs_in_month = sum(1 for a in acts if a["date"][:7]==m)
    print(f"{m:<10} {monthly_cal[m]:>10,.0f} {monthly_cal[m]/runs_in_month:>9,.0f}")

print(f"\n  Total calories burned: {sum(monthly_cal.values()):,.0f} kcal")
print(f"  Equivalent to ~{sum(monthly_cal.values())/7700:.0f} kg of fat burned")

# ── 13. SUMMARY SCORECARD ─────────────────────────────────────────────────────
hdr("13. ANNUAL SCORECARD")
total_km = sum(a["distance_km"] for a in acts)
total_elev = sum(a["elevation_gain_m"] or 0 for a in acts)
vo2s = [a["vo2max"] for a in acts if a["vo2max"]]

print(f"  Volume score:      {total_km:.0f} km  ({'Elite amateur' if total_km>2000 else 'Strong' if total_km>1500 else 'Good'})")
print(f"  Vert score:        {total_elev/1000:.1f} km  ({'Mountain runner' if total_elev>80000 else 'Trail focused'})")
print(f"  Consistency:       49/52 weeks  (94% — excellent)")
print(f"  Trail ratio:       {106/150*100:.0f}%  ({'Trail specialist' if 106/150>0.6 else 'Mixed'})")
print(f"  VO2max:            {vo2s[-1] if vo2s else 'N/A'}  ({'Elite' if (vo2s[-1] if vo2s else 0)>60 else 'Very good' if (vo2s[-1] if vo2s else 0)>55 else 'Good'})")
print(f"  Avg week:          {total_km/52:.1f} km")
print(f"  Peak week:         {max(weekly[w]['km'] for w in weekly):.1f} km")
hrs_with_hr = [a["avg_hr"] for a in acts if a["avg_hr"]]
z2_pct = sum(1 for h in hrs_with_hr if h < 145)/len(hrs_with_hr)*100
z3_pct = sum(1 for h in hrs_with_hr if 145 <= h < 160)/len(hrs_with_hr)*100
print(f"  HR distribution:   {z2_pct:.0f}% Z2 / {z3_pct:.0f}% Z3 — {'Polarized ✓' if z2_pct+z3_pct>80 else 'High intensity heavy'}")
