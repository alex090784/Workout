#!/usr/bin/env python3
"""Deep analysis of FIT data — power, running economy, HR drift, decoupling trends"""
import json
from datetime import datetime
from collections import defaultdict
import statistics

with open("/Users/alexct/fit_all_sessions.json") as f:
    sessions = json.load(f)

def hdr(t): print(f"\n{'='*60}\n  {t}\n{'='*60}")
def fmt_pace(p):
    if not p or p > 20: return "N/A"
    return f"{int(p)}:{int((p%1)*60):02d}/km"

# ── 1. RUNNING POWER TRENDS ────────────────────────────────────────────────
hdr("1. RUNNING POWER (Watts) — Monthly Trends")
monthly_pwr = defaultdict(list)
for s in sessions:
    if s.get("avg_power"):
        monthly_pwr[s["date"][:7]].append(s["avg_power"])

print(f"{'Month':<10} {'Avg W':>7} {'Min W':>7} {'Max W':>7} {'Samples':>8}")
print("-"*40)
for m in sorted(monthly_pwr):
    v = monthly_pwr[m]
    print(f"{m:<10} {statistics.mean(v):>7.0f} {min(v):>7.0f} {max(v):>7.0f} {len(v):>8}")

# Power efficiency (watts per km/h)
print("\n  Power efficiency trend (W per km/h — lower = more efficient):")
monthly_eff = defaultdict(list)
for s in sessions:
    if s.get("avg_power") and s.get("speed_kmh") and s["speed_kmh"] > 0:
        monthly_eff[s["date"][:7]].append(s["avg_power"] / s["speed_kmh"])
print(f"{'Month':<10} {'W/kmh':>8}")
for m in sorted(monthly_eff):
    print(f"{m:<10} {statistics.mean(monthly_eff[m]):>8.1f}")

# ── 2. RUNNING ECONOMY METRICS ─────────────────────────────────────────────
hdr("2. RUNNING ECONOMY METRICS")
econ = [(s["date"], s["vert_osc_mm"], s["stance_ms"], s["step_len_mm"],
         s["cadence_spm"], s["vert_ratio"])
        for s in sessions if s.get("vert_osc_mm")]

print(f"\n{'Metric':<28} {'Early avg':>10} {'Recent avg':>11} {'Change':>8}")
print("-"*60)

early  = [e for e in econ if e[0] < "2025-07"]
recent = [e for e in econ if e[0] >= "2026-01"]

metrics = [
    ("Vertical oscillation (mm)", 1, "lower=better"),
    ("Stance time (ms)",          2, "lower=better"),
    ("Step length (mm)",          3, "higher=better"),
    ("Cadence (spm)",             4, "higher=better"),
    ("Vertical ratio (%)",        5, "lower=better"),
]
for name, idx, note in metrics:
    e_vals = [x[idx] for x in early  if x[idx]]
    r_vals = [x[idx] for x in recent if x[idx]]
    if e_vals and r_vals:
        e_avg = statistics.mean(e_vals)
        r_avg = statistics.mean(r_vals)
        diff  = r_avg - e_avg
        arrow = "↑" if diff > 0 else "↓"
        print(f"  {name:<26} {e_avg:>10.1f} {r_avg:>11.1f} {arrow}{abs(diff):>6.1f}  ({note})")

# ── 3. AEROBIC DECOUPLING ANALYSIS ─────────────────────────────────────────
hdr("3. AEROBIC DECOUPLING (HR drift vs pace in 2nd half)")
print("  < 5% = aerobically efficient | > 5% = fatigue or heat stress")
print()
coupled   = [s for s in sessions if s.get("decoupling_pct") is not None and abs(s["decoupling_pct"]) < 5]
decoupled = [s for s in sessions if s.get("decoupling_pct") is not None and s["decoupling_pct"] >= 5]
neg_decouple = [s for s in sessions if s.get("decoupling_pct") is not None and s["decoupling_pct"] < -5]

print(f"  Well coupled (<5%):   {len(coupled)} sessions ({len(coupled)/len([s for s in sessions if s.get('decoupling_pct') is not None])*100:.0f}%)")
print(f"  Decoupled (>5%):      {len(decoupled)} sessions")
print(f"  Negative drift (<-5%): {len(neg_decouple)} sessions (went harder in 2nd half)")

print("\n  Monthly avg decoupling:")
monthly_dec = defaultdict(list)
for s in sessions:
    if s.get("decoupling_pct") is not None:
        monthly_dec[s["date"][:7]].append(s["decoupling_pct"])
for m in sorted(monthly_dec):
    avg = statistics.mean(monthly_dec[m])
    flag = " ⚠️" if avg > 5 else " ✅"
    print(f"  {m}: {avg:+.1f}%{flag}")

print("\n  Most decoupled sessions (fatigue signals):")
worst = sorted([s for s in sessions if s.get("decoupling_pct")], key=lambda x: x["decoupling_pct"], reverse=True)[:8]
for s in worst:
    print(f"    {s['date']}  {s['dist_km']}km  +{s['ascent_m']:.0f}m  HR:{s['avg_hr']}  decouple:{s['decoupling_pct']:+.1f}%")

# ── 4. HR ZONE DISTRIBUTION OVER TIME ─────────────────────────────────────
hdr("4. HR ZONE DISTRIBUTION — Monthly")
print(f"{'Month':<10} {'Z1%':>5} {'Z2%':>5} {'Z3%':>5} {'Z4%':>5} {'Z5%':>5} {'Aerobic%':>9}")
print("-"*50)
for m in sorted(set(s["date"][:7] for s in sessions)):
    month_sessions = [s for s in sessions if s["date"][:7] == m and s.get("zone_pct")]
    if not month_sessions:
        continue
    z = {z: statistics.mean([s["zone_pct"].get(z,0) for s in month_sessions]) for z in ["Z1","Z2","Z3","Z4","Z5"]}
    aerobic = z["Z1"] + z["Z2"] + z["Z3"]
    print(f"{m:<10} {z['Z1']:>5.0f} {z['Z2']:>5.0f} {z['Z3']:>5.0f} {z['Z4']:>5.0f} {z['Z5']:>5.0f} {aerobic:>9.0f}%")

# ── 5. CADENCE ANALYSIS ────────────────────────────────────────────────────
hdr("5. CADENCE (steps per minute)")
print("  Target for trail running: 170–185 spm")
cad_sessions = [s for s in sessions if s.get("cadence_spm") and s["cadence_spm"] > 100]
if cad_sessions:
    monthly_cad = defaultdict(list)
    for s in cad_sessions:
        monthly_cad[s["date"][:7]].append(s["cadence_spm"])
    print(f"{'Month':<10} {'Avg spm':>8} {'Status':>15}")
    for m in sorted(monthly_cad):
        avg = statistics.mean(monthly_cad[m])
        status = "✅ good" if 170 <= avg <= 185 else ("⬆️ too high" if avg > 185 else "⬇️ too low")
        print(f"  {m:<10} {avg:>8.0f} {status:>15}")

# ── 6. POWER-TO-PACE EFFICIENCY (fitness proxy) ────────────────────────────
hdr("6. POWER EFFICIENCY — Fitness Progression Proxy")
print("  Watts per pace unit (lower = same power, faster pace = more fit)")
monthly_pp = defaultdict(list)
for s in sessions:
    if s.get("avg_power") and s.get("avg_pace") and 4 < s["avg_pace"] < 15:
        monthly_pp[s["date"][:7]].append(s["avg_power"] * s["avg_pace"])  # W × min/km
print(f"{'Month':<10} {'W×pace':>10} {'Trend':>10}")
prev = None
for m in sorted(monthly_pp):
    val = statistics.mean(monthly_pp[m])
    trend = ""
    if prev:
        diff = val - prev
        trend = f"{'better' if diff < -5 else 'worse' if diff > 5 else 'stable'} ({diff:+.0f})"
    print(f"  {m:<10} {val:>10.0f} {trend}")
    prev = val

# ── 7. BEST SESSIONS BY POWER ZONE ────────────────────────────────────────
hdr("7. HIGHEST POWER OUTPUTS")
top_pwr = sorted([s for s in sessions if s.get("avg_power")], key=lambda x: x["avg_power"], reverse=True)[:10]
print(f"{'Date':<12} {'Dist':>6} {'Vert':>6} {'HR':>5} {'Avg W':>7} {'Norm W':>7}")
print("-"*50)
for s in top_pwr:
    print(f"  {s['date']:<10} {s['dist_km']:>6.1f} {s['ascent_m']:>6.0f} "
          f"{s['avg_hr'] or '-':>5} {s['avg_power']:>7} {s.get('norm_power') or '-':>7}")

# ── 8. LONG RUN QUALITY (decoupling on runs >20km) ────────────────────────
hdr("8. LONG RUN QUALITY (>20km)")
long_runs = sorted([s for s in sessions if s["dist_km"] >= 20], key=lambda x: x["date"])
print(f"{'Date':<12} {'Km':>6} {'Vert':>6} {'HR':>5} {'Pace':>8} {'Decouple':>10} {'Power':>7}")
print("-"*60)
for s in long_runs:
    d = s.get("decoupling_pct")
    d_str = f"{d:+.1f}%" if d is not None else "N/A"
    flag = " ⚠️" if d and d > 5 else ""
    print(f"  {s['date']:<10} {s['dist_km']:>6.1f} {s['ascent_m']:>6.0f} "
          f"{s['avg_hr'] or '-':>5} {fmt_pace(s['avg_pace']):>8} {d_str:>10}{flag} {s.get('avg_power') or '-':>7}")

# ── 9. MUT GEORGE READINESS SCORE ─────────────────────────────────────────
hdr("9. MUT GEORGE READINESS ASSESSMENT")
recent = [s for s in sessions if s["date"] >= "2026-01-01"]
if recent:
    avg_pwr_recent = statistics.mean([s["avg_power"] for s in recent if s.get("avg_power")])
    avg_hr_recent  = statistics.mean([s["avg_hr"] for s in recent if s.get("avg_hr")])
    long_recent    = [s for s in recent if s["dist_km"] >= 20]
    avg_decouple   = statistics.mean([s["decoupling_pct"] for s in recent if s.get("decoupling_pct") is not None])
    avg_cad        = statistics.mean([s["cadence_spm"] for s in recent if s.get("cadence_spm") and s["cadence_spm"] > 100])

    print(f"  Recent avg power (Jan–Mar 2026): {avg_pwr_recent:.0f}W")
    print(f"  Recent avg HR:                   {avg_hr_recent:.0f} bpm")
    print(f"  Long runs (>20km) since Jan:     {len(long_recent)}")
    print(f"  Avg aerobic decoupling:          {avg_decouple:+.1f}%  {'✅' if abs(avg_decouple) < 5 else '⚠️'}")
    print(f"  Avg cadence:                     {avg_cad:.0f} spm")

    # Compare to peak period
    peak = [s for s in sessions if "2025-08" <= s["date"][:7] <= "2025-10"]
    if peak:
        peak_pwr = statistics.mean([s["avg_power"] for s in peak if s.get("avg_power")])
        print(f"\n  vs Peak period (Aug–Oct 2025):")
        print(f"  Peak avg power:  {peak_pwr:.0f}W  |  Current: {avg_pwr_recent:.0f}W  ({avg_pwr_recent-peak_pwr:+.0f}W)")

    print(f"\n  Verdict:")
    if avg_pwr_recent >= 285 and abs(avg_decouple) < 5:
        print("  ✅ Strong aerobic base, good decoupling — on track for MUT George")
    elif avg_pwr_recent >= 260:
        print("  🟡 Solid base but room to sharpen — focus on Z3/Z4 quality sessions")
    else:
        print("  ⚠️  Power below peak levels — prioritise volume and vert in next 4 weeks")
