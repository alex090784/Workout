#!/usr/bin/env python3
"""
Explore one FIT file to see what data is available
"""
import gzip
import os
from fitparse import FitFile

EXPORT_DIR = "/Users/alexct/Downloads/WorkoutFileExport-de Clermont-Tonnerre-Alexis-2025-03-29-2026-03-29"

# Pick the first tp- file
files = sorted([f for f in os.listdir(EXPORT_DIR) if f.endswith(".FIT.gz") and f.startswith("tp-")])
sample = os.path.join(EXPORT_DIR, files[0])
print(f"Inspecting: {files[0]}\n")

with gzip.open(sample, 'rb') as gz:
    raw = gz.read()

fit = FitFile(raw)

# Show all message types available
msg_types = set()
for msg in fit.get_messages():
    msg_types.add(msg.name)
print(f"Message types: {sorted(msg_types)}\n")

# Show session summary fields
print("=== SESSION ===")
for msg in fit.get_messages("session"):
    for field in msg.fields:
        if field.value is not None:
            print(f"  {field.name}: {field.value}")

# Show first 5 record (per-second data) fields
print("\n=== RECORD (first 3 data points) ===")
count = 0
for msg in fit.get_messages("record"):
    if count >= 3:
        break
    print(f"  --- point {count+1} ---")
    for field in msg.fields:
        if field.value is not None:
            print(f"    {field.name}: {field.value}")
    count += 1

# Show laps if any
print("\n=== LAPS ===")
lap_count = 0
for msg in fit.get_messages("lap"):
    lap_count += 1
    if lap_count <= 3:
        for field in msg.fields:
            if field.value is not None and field.name in (
                "start_time","total_distance","total_elapsed_time",
                "avg_heart_rate","max_heart_rate","avg_speed","total_ascent"
            ):
                print(f"  {field.name}: {field.value}")
        print()
print(f"Total laps: {lap_count}")
