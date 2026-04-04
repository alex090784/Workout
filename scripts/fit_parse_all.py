#!/usr/bin/env python3
"""
Parse all FIT files from TrainingPeaks export into rich JSON dataset
Extracts: summary, per-km laps, running economy metrics, HR drift, power
"""
import gzip, os, json
from fitparse import FitFile
from datetime import datetime
from collections import defaultdict

EXPORT_DIR = "/Users/alexct/Downloads/WorkoutFileExport-de Clermont-Tonnerre-Alexis-2025-03-29-2026-03-29"
OUTPUT     = "/Users/alexct/fit_all_sessions.json"

files = sorted([f for f in os.listdir(EXPORT_DIR) if f.endswith(".FIT.gz") and f.startswith("tp-")])
print(f"Found {len(files)} FIT files\n")

sessions = []

for fname in files:
    fpath = os.path.join(EXPORT_DIR, fname)
    try:
        with gzip.open(fpath, 'rb') as gz:
            raw = gz.read()
        fit = FitFile(raw)

        # ── Session summary ───────────────────────────────────────────────────
        session = {}
        for msg in fit.get_messages("session"):
            for f in msg.fields:
                if f.value is not None:
                    session[f.name] = f.value

        if not session:
            continue

        start = session.get("start_time")
        if not start:
            continue

        dist_m   = session.get("total_distance", 0) or 0
        dur_s    = session.get("total_elapsed_time", 0) or 0
        ascent_m = session.get("total_ascent", 0) or 0
        avg_hr   = session.get("avg_heart_rate")
        max_hr   = session.get("max_heart_rate")
        calories = session.get("total_calories", 0)
        te       = session.get("total_training_effect")
        power    = session.get("avg_power")
        norm_pwr = session.get("normalized_power")
        cadence  = session.get("avg_running_cadence", 0)
        if cadence: cadence = cadence * 2  # convert to spm
        v_osc    = session.get("avg_vertical_oscillation")
        stance   = session.get("avg_stance_time")
        step_len = session.get("avg_step_length")
        v_ratio  = session.get("avg_vertical_ratio")

        dist_km  = round(dist_m / 1000, 2)
        dur_min  = round(dur_s / 60, 1)
        pace     = round(dur_min / dist_km, 2) if dist_km > 0 else None
        m_per_km = round(ascent_m / dist_km, 1) if dist_km > 0 else 0
        speed_kmh = round(dist_km / (dur_min / 60), 2) if dur_min > 0 else 0

        # ── Per-km laps ───────────────────────────────────────────────────────
        laps = []
        for msg in fit.get_messages("lap"):
            lap = {}
            for f in msg.fields:
                if f.value is not None:
                    lap[f.name] = f.value
            lap_dist = (lap.get("total_distance") or 0)
            lap_time = (lap.get("total_elapsed_time") or 0)
            if lap_dist > 0:
                laps.append({
                    "km":         round(lap_dist / 1000, 2),
                    "pace":       round(lap_time / 60 / (lap_dist / 1000), 2) if lap_dist > 0 else None,
                    "avg_hr":     lap.get("avg_heart_rate"),
                    "max_hr":     lap.get("max_heart_rate"),
                    "ascent_m":   lap.get("total_ascent", 0),
                    "speed_ms":   lap.get("enhanced_avg_speed"),
                })

        # ── Per-second records for HR drift & power analysis ─────────────────
        records = []
        for msg in fit.get_messages("record"):
            rec = {}
            for f in msg.fields:
                if f.value is not None:
                    rec[f.name] = f.value
            if rec:
                records.append({
                    "t":    rec.get("timestamp"),
                    "hr":   rec.get("heart_rate"),
                    "spd":  rec.get("enhanced_speed"),
                    "alt":  rec.get("enhanced_altitude"),
                    "pwr":  rec.get("power"),
                    "cad":  rec.get("cadence"),
                    "vosc": rec.get("vertical_oscillation"),
                    "st":   rec.get("stance_time"),
                    "slen": rec.get("step_length"),
                })

        # ── Aerobic decoupling (HR drift vs pace in 2nd half) ─────────────────
        decoupling = None
        hrs  = [r["hr"]  for r in records if r.get("hr")  and r.get("spd")]
        spds = [r["spd"] for r in records if r.get("hr")  and r.get("spd")]
        if len(hrs) >= 20:
            mid = len(hrs) // 2
            h1, s1 = sum(hrs[:mid]) / mid,  sum(spds[:mid]) / mid
            h2, s2 = sum(hrs[mid:]) / len(hrs[mid:]), sum(spds[mid:]) / len(spds[mid:])
            if s1 > 0 and s2 > 0 and h1 > 0:
                eff1 = s1 / h1
                eff2 = s2 / h2
                decoupling = round((eff1 - eff2) / eff1 * 100, 1)  # % drift

        # ── HR zone time distribution (Friel LT-based) ───────────────────────
        LT = 176
        zones = {"Z1":0,"Z2":0,"Z3":0,"Z4":0,"Z5":0}
        for r in records:
            hr = r.get("hr")
            if hr:
                if hr < 141:         zones["Z1"] += 1
                elif hr < 158:       zones["Z2"] += 1
                elif hr < 167:       zones["Z3"] += 1
                elif hr < 178:       zones["Z4"] += 1
                else:                zones["Z5"] += 1
        total_pts = sum(zones.values())
        zone_pct = {z: round(v/total_pts*100, 1) for z,v in zones.items()} if total_pts else {}

        s = {
            "file":       fname,
            "date":       start.strftime("%Y-%m-%d") if hasattr(start,"strftime") else str(start)[:10],
            "time":       start.strftime("%H:%M")    if hasattr(start,"strftime") else str(start)[11:16],
            "dist_km":    dist_km,
            "dur_min":    dur_min,
            "ascent_m":   round(ascent_m, 0),
            "m_per_km":   m_per_km,
            "avg_pace":   pace,
            "speed_kmh":  speed_kmh,
            "avg_hr":     avg_hr,
            "max_hr":     max_hr,
            "calories":   calories,
            "training_effect": round(te, 1) if te else None,
            "avg_power":  power,
            "norm_power": norm_pwr,
            "cadence_spm": int(cadence) if cadence else None,
            "vert_osc_mm": round(v_osc, 1) if v_osc else None,
            "stance_ms":  round(stance, 1) if stance else None,
            "step_len_mm": round(step_len, 1) if step_len else None,
            "vert_ratio": round(v_ratio, 2) if v_ratio else None,
            "decoupling_pct": decoupling,
            "zone_pct":   zone_pct,
            "laps":       laps,
            "n_records":  len(records),
        }
        sessions.append(s)
        print(f"✓ {s['date']}  {s['dist_km']}km  +{s['ascent_m']}m  HR:{avg_hr}  PWR:{power}W")

    except Exception as e:
        print(f"✗ {fname}: {e}")

sessions.sort(key=lambda x: x["date"])

with open(OUTPUT, "w") as f:
    json.dump(sessions, f, indent=2, default=str)

print(f"\n✅ Parsed {len(sessions)} sessions → {OUTPUT}")
