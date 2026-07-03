#!/usr/bin/env python3
"""
Populate the garmin_training.training_plan BQ table with the 13-week
Otter African Trail Run 2026 training plan.

91 rows (13 weeks x 7 days), 29 Jun - 24 Sep 2026.
Source: /Users/alexct/training_plans/otter_2026_plan.md (revised volumes).
"""

from datetime import date, timedelta
from google.cloud import bigquery

PROJECT = "alexct-training"
TABLE = f"{PROJECT}.garmin_training.training_plan"

DAYS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]

# Weekly targets (revised)
WEEKS = [
    # (week_num, start_date, phase, km, vert)
    (1,  date(2026, 6, 29), "Base",  40, 1400),
    (2,  date(2026, 7, 6),  "Base",  45, 1700),
    (3,  date(2026, 7, 13), "Base",  50, 2000),
    (4,  date(2026, 7, 20), "Base",  38, 1300),
    (5,  date(2026, 7, 27), "Build", 55, 2200),
    (6,  date(2026, 8, 3),  "Build", 60, 2600),
    (7,  date(2026, 8, 10), "Build", 65, 2800),
    (8,  date(2026, 8, 17), "Build", 48, 1800),
    (9,  date(2026, 8, 24), "Peak",  63, 2800),
    (10, date(2026, 8, 31), "Peak",  68, 3000),
    (11, date(2026, 9, 7),  "Peak",  55, 2400),
    (12, date(2026, 9, 14), "Taper", 35, 1100),
    (13, date(2026, 9, 21), "Race",  15, 400),
]

# Each day: (session_type, session_name, target_km, target_vert, duration_min,
#            hr_zone, hr_max, rpe, description, effort_description, is_key)

def week1():
    return [
        ("easy_trail", "Easy trail run", 8, 350, 55, "Z1-Z2", 150, 3,
         "Table Mountain lower contour paths. Z1-Z2 only, cap 150 bpm. Walk all climbs above 150.",
         "Finish feeling like you could do it again.", False),
        ("strength", "Strength A + Core", None, None, 40, None, None, 6,
         "Foundation strength session. Core circuit x2.",
         "Feel the work, do not chase fatigue.", False),
        ("easy_road", "Easy road run", 9, 0, 50, "Z1-Z2", 148, 3,
         "Sea Point promenade or similar. Z1-Z2, target 140-148 bpm. Cadence focus: 160-165 spm.",
         "Phone call voice.", True),
        ("rest", "REST", None, None, 15, None, None, 0,
         "Full rest. Mobility routine only (15 min).",
         "No effort.", False),
        ("easy_trail", "Trail run - vertical focus", 9, 550, 65, "Z1-Z2", 155, 5,
         "Constantia Nek to Woodhead Reservoir via Skeleton Gorge staircase. Hike up (Z2 max), controlled descent.",
         "Steady, sustainable climbing.", False),
        ("strength", "Strength B + Core", None, None, 40, None, None, 6,
         "Foundation strength session. Core circuit x2.",
         "Same as Tuesday.", False),
        ("long_run", "Long run (trail)", 14, 500, 90, "Z2", 157, 5,
         "Newlands Forest or Silvermine. Z2 throughout, walk uphills to stay in zone. Conversational pace.",
         "Finish tired but able to walk normally within 30 min.", True),
    ]

def week2():
    return [
        ("easy_trail", "Easy trail run", 9, 400, 60, "Z1-Z2", 150, 3,
         "Same controlled effort as week 1. Z2 ceiling.",
         "Finish feeling like you could do it again.", False),
        ("strength", "Strength A + Core", None, None, 40, None, None, 6,
         "Foundation strength. Progress to slightly heavier loads if week 1 was comfortable. Core circuit x2.",
         "Feel the work, do not chase fatigue.", False),
        ("easy_road", "Easy road run + strides", 10, 0, 55, "Z1-Z2", 148, 4,
         "10 km road, Z1-Z2. After: 6x100m strides on flat grass. Smooth, fast, relaxed at ~90% sprint speed.",
         "RPE 3-4 for run, RPE 7 for strides only.", True),
        ("rest", "REST", None, None, 15, None, None, 0,
         "Mobility only.",
         "No effort.", False),
        ("easy_trail", "Trail run - technical focus", 10, 550, 70, "Z2", 155, 5,
         "Rocky, rooty single-track (India Venster, Platteklip side trails, Tokai). Focus on foot placement, reading trail 3-5m ahead.",
         "Mentally sharp, physically controlled.", False),
        ("strength", "Strength B + Core", None, None, 45, None, None, 6,
         "Foundation strength. Core circuit x3 (add a round).",
         "Feel the work, do not chase fatigue.", False),
        ("long_run", "Long run (trail)", 16, 750, 100, "Z2", 157, 5,
         "Silvermine reservoir loop or Hout Bay to Chapman's Peak. Z2, walk climbs. Practise eating/drinking on the move.",
         "Tired in the second half. That is the point.", True),
    ]

def week3():
    return [
        ("easy_trail", "Easy trail run", 9, 400, 60, "Z1-Z2", 150, 3,
         "Z1-Z2 controlled effort.",
         "Finish feeling like you could do it again.", False),
        ("strength", "Strength A + Core", None, None, 45, None, None, 6,
         "Foundation strength, full progression (8-12 kg dumbbells, 20-24 kg KB). Core circuit x3.",
         "Genuinely challenged by final set.", False),
        ("tempo", "Tempo intervals", 11, 100, 60, "Z3-Z4", 170, 7,
         "Warm up 2 km easy. 4x5 min at Z3/low Z4 (160-170 bpm) with 2 min walk/jog recovery. Cool down 2 km.",
         "Uncomfortable but controlled. Short sentences only.", True),
        ("rest", "REST", None, None, 15, None, None, 0,
         "Mobility.",
         "No effort.", False),
        ("easy_trail", "Trail run - descent practice", 11, 650, 75, "Z2", 155, 5,
         "Route with significant descent (500m+ downhill in second half). India Venster or Skeleton Gorge descent. Short choppy steps, forward lean, soft knees.",
         "RPE 4-5 on climb, RPE 6 on descent focus.", False),
        ("strength", "Strength B + Core", None, None, 45, None, None, 6,
         "Foundation strength. Add single-leg balance work: 3x30 sec each leg, eyes closed. Core x3.",
         "Genuinely challenged by final set.", False),
        ("long_run", "Long run (trail)", 19, 950, 120, "Z2", 160, 5,
         "Route with at least one 500m+ climb. Z2 on flats/descents, Z3 on climbs. Nutrition: 200 cal between km 8-14. Target 300 cal/hour.",
         "Tired in the second half. That is the point. Not destroyed.", True),
    ]

def week4():
    return [
        ("easy_trail", "Easy trail run (recovery)", 7, 300, 50, "Z1", 145, 2,
         "Pure recovery pace. Z1 target, cap 145 bpm.",
         "Barely a workout.", False),
        ("strength", "Strength A (reduced) + Core", None, None, 30, None, None, 4,
         "Drop all sets to 2x (from 3x). Core circuit x2. Recovery week.",
         "Do not progress.", False),
        ("easy_road", "Easy road run + strides", 9, 0, 50, "Z1-Z2", 150, 3,
         "Z1-Z2. 4x100m strides (reduced from 6).",
         "Phone call voice.", True),
        ("rest", "REST", None, None, 20, None, None, 0,
         "Mobility + foam roll (extended 20 min session).",
         "No effort.", False),
        ("easy_trail", "Easy trail run - technical", 8, 400, 55, "Z1-Z2", 150, 3,
         "Light technical work. Focus on enjoyment.",
         "Finish feeling like you could do it again.", False),
        ("rest", "REST", None, None, 0, None, None, 0,
         "Full rest day. Sleep in. Walk if you want.",
         "No effort.", False),
        ("long_run", "Long run (moderate)", 14, 600, 85, "Z2", 155, 4,
         "Easy effort. Shorter and flatter than last week intentionally.",
         "Phone call voice. Finish feeling good.", True),
    ]

def week5():
    return [
        ("easy_trail", "Easy trail run", 9, 450, 60, "Z1-Z2", 150, 3,
         "Recovery from recovery week. Legs should feel fresh.",
         "Finish feeling like you could do it again.", False),
        ("strength", "Strength A (Build) + Core", None, None, 45, None, None, 7,
         "Build-phase strength protocol: Pistol squat progressions, single-leg RDL, box jump step-downs, walking lunges, heel drops. Core x3.",
         "New exercises -- form over load. Genuinely challenging.", False),
        ("hill_repeats", "Hill repeats", 13, 650, 75, "Z4", 175, 8,
         "Warm up 2 km. 5x hill repeats on 200-250m climb at Z4 (167-175 bpm), 3-4 min per rep. Jog/walk down recovery. Cool down 2 km.",
         "This should hurt. Legs burning, breathing heavy. Last rep hardest.", True),
        ("rest", "REST", None, None, 15, None, None, 0,
         "Mobility.",
         "No effort.", False),
        ("easy_trail", "Trail run - Otter simulation", 13, 650, 85, "Z2-Z3", 165, 5,
         "Most technical trail available. Scramble sections, rocky descents. Race shoes. Race pack with 2L water and nutrition. 300 cal/hour practice.",
         "Technical focus. Controlled.", False),
        ("strength", "Strength B (Build) + Core", None, None, 45, None, None, 7,
         "Build-phase strength session. Core x3.",
         "Genuinely challenging.", False),
        ("long_run", "Long run (trail, vertical focus)", 20, 1100, 140, "Z2", 160, 6,
         "Route with sustained climbing. Elevation density 55+ m/km. Z2 on flats/descents, Z3/Z4 on climbs acceptable. 300 cal/hour from km 8.",
         "Big but controlled. Tired in second half.", True),
    ]

def week6():
    return [
        ("easy_trail", "Easy trail run + core", 10, 450, 65, "Z1-Z2", 150, 3,
         "Z1-Z2. Core circuit x2 post-run.",
         "Finish feeling like you could do it again.", False),
        ("strength", "Strength A (Build)", None, None, 45, None, None, 7,
         "Full build-phase strength session.",
         "Genuinely challenging.", False),
        ("threshold", "Threshold run (sustained)", 12, 100, 65, "Z4", 175, 8,
         "Warm up 2 km. 20 min continuous at Z4 (167-175 bpm) on rolling trail/road. Cool down 2 km. If cannot sustain, drop to 2x10 min with 3 min easy.",
         "Hard. Short sentences between breaths.", True),
        ("rest", "REST", None, None, 15, None, None, 0,
         "Mobility + extended foam roll.",
         "No effort.", False),
        ("easy_trail", "Trail run - double vertical", 12, 800, 80, "Z2-Z3", 165, 6,
         "Short but steep. Up-down-up: climb 400m, descend, climb 400m. Simulates Otter's repeated climb/descent.",
         "Second climb on loaded legs is the real training.", False),
        ("strength", "Strength B (Build) + Core", None, None, 45, None, None, 7,
         "Build-phase strength. Core x3 on balance pad.",
         "Genuinely challenging.", False),
        ("long_run", "Long run (trail)", 24, 1300, 160, "Z2", 160, 6,
         "Biggest run of block. Mountain trail with mixed terrain. At least one 600m+ sustained climb. Full race kit. 300 cal/hour.",
         "Big session. Tired in second half. Not destroyed.", True),
    ]

def week7():
    return [
        ("easy_trail", "Easy trail run", 10, 400, 65, "Z1-Z2", 150, 3,
         "Active recovery from big Sunday.",
         "Finish feeling like you could do it again.", False),
        ("strength", "Strength A (Build) + Core", None, None, 45, None, None, 7,
         "Build-phase strength. Core x3.",
         "Genuinely challenging.", False),
        ("prologue_sim", "Prologue-specific session", 9, 250, 50, "Z4-Z5", 185, 9,
         "Warm up 2 km. 5 km time trial on technical trail -- simulates Day 1 prologue. Z4-Z5 (170-185 bpm). All-out controlled effort. Cool down 2 km. Record time.",
         "Nauseous at the finish. That is correct.", True),
        ("rest", "REST", None, None, 15, None, None, 0,
         "Extended mobility. Focus on ankles and hips.",
         "No effort.", False),
        ("hill_repeats", "STAIR REPEATS + Steps simulation", 14, 900, 95, "Z3-Z4", 175, 8,
         "DEDICATED STAIR SESSION. Skeleton Gorge/Platteklip/Kasteelspoort. 5x repeats of 50-80m vert: climb Z3-Z4, descend with max control. Walk recovery 2-3 min. Focus on quad-loading descents.",
         "By rep 5 your quads should be on fire.", False),
        ("strength", "Strength B (Build) + Core", None, None, 45, None, None, 7,
         "Build-phase strength. Core x3.",
         "Genuinely challenging.", False),
        ("long_run", "Long run (peak build)", 28, 1500, 190, "Z2", 160, 6,
         "Key long run of build phase. Technical, mountainous, 54 m/km density. Table Mountain traverse. Full race kit and nutrition. Munchie Point rehearsal at km 14.",
         "Long and steady, not fast. Tired but managed.", True),
    ]

def week8():
    return [
        ("easy_trail", "Easy trail run", 8, 350, 55, "Z1", 145, 2,
         "Pure Z1 recovery.",
         "Barely a workout.", False),
        ("strength", "Strength (maintenance) + Core", None, None, 35, None, None, 5,
         "Reduce all sets to 2x8. Core x2. Maintenance, not progress.",
         "Maintenance. Do not try to progress.", False),
        ("easy_road", "Easy road run + strides", 9, 0, 50, "Z1-Z2", 150, 4,
         "Z1-Z2. 6x100m strides. Keep it smooth and fast, not hard.",
         "RPE 3-4 for run, RPE 7 for strides.", True),
        ("rest", "REST", None, None, 15, None, None, 0,
         "Mobility + foam roll.",
         "No effort.", False),
        ("easy_trail", "Easy trail run", 12, 550, 80, "Z2", 155, 5,
         "Technical terrain but easy effort. Enjoy the trails.",
         "Steady, sustainable. Not pushing.", False),
        ("rest", "REST", None, None, 0, None, None, 0,
         "Full rest.",
         "No effort.", False),
        ("long_run", "Long run (moderate)", 19, 900, 120, "Z2", 155, 4,
         "Z2, relaxed. No race simulation, no pack. Just run.",
         "Phone call voice. Finish feeling good.", True),
    ]

def week9():
    return [
        ("easy_trail", "Easy trail run + core", 9, 400, 60, "Z1-Z2", 150, 3,
         "Shake out from recovery week. Core x3 on balance pad post-run.",
         "Finish feeling like you could do it again.", False),
        ("strength", "Strength (maintenance) + Core", None, None, 35, None, None, 5,
         "2x8 all exercises. Core x3 on balance pad. Maintenance.",
         "Maintenance. Do not try to progress.", False),
        ("vo2max", "VO2max intervals", 11, 550, 60, "Z5", 188, 9,
         "Warm up 2 km. 6x3 min at Z5 (178-188 bpm) on uphill trail with 3 min walk/jog recovery. Cool down 2 km.",
         "By rep 4-5 you should be questioning your life choices.", True),
        ("rest", "REST", None, None, 15, None, None, 0,
         "Mobility. Ice bath or cold shower (10 min) if legs feel heavy.",
         "No effort.", False),
        ("prologue_sim", "Prologue simulation (Day 1)", 5, 200, 30, "Z4-Z5", 185, 9,
         "5 km time trial on technical trail, Z4-Z5. Race shoes and kit. Record time and compare to week 7. Simulates Day 1 evening.",
         "All-out controlled effort. Nauseous at the finish.", False),
        ("race_sim", "Race simulation (Day 2)", 32, 1900, 240, "Z2-Z3", 165, 7,
         "KEY SESSION. Start 12-16 hours after prologue. 30-32 km, 1700-1900m vert. Sustained climbing, technical descents, steps. Full race kit. Munchie Point rehearsal at km 15-16. 300 cal/hour.",
         "RPE 5-6 first half, RPE 7-8 second half. Dauwalter territory.", True),
        ("easy_trail", "Recovery walk or easy jog", 4, 0, 40, "Z1", 135, 1,
         "Flat walk or very easy jog. Z1 only, cap 135 bpm. Assess body after back-to-back.",
         "Walk. Stiffness is expected. Sharp pain is a red flag.", False),
    ]

def week10():
    return [
        ("easy_trail", "Easy trail run", 10, 450, 65, "Z1-Z2", 150, 3,
         "Z1-Z2. Recover from the back-to-back weekend.",
         "Finish feeling like you could do it again.", False),
        ("strength", "Strength (maintenance) + Core", None, None, 35, None, None, 5,
         "2x8 all exercises. Core x3. Maintenance.",
         "Maintenance. Do not try to progress.", False),
        ("threshold", "Threshold hill repeats", 14, 750, 80, "Z4", 175, 8,
         "Warm up 2 km. 6x4 min uphill at Z4 (167-175 bpm) on trail, jog/walk down recovery. Cool down 2 km. Hardest interval session of the plan. 24 min total Z4 work.",
         "Legs burning, breathing heavy. Last rep should feel close to failure.", True),
        ("rest", "REST", None, None, 15, None, None, 0,
         "Mobility + foam roll.",
         "No effort.", False),
        ("hill_repeats", "STAIR REPEATS + descending under fatigue", 14, 800, 95, "Z3-Z4", 175, 8,
         "6x repeats of 50-80m vert. Climb Z3-Z4, descend with max control. Then big climb (500m+) and descend on technical trail. Run with MAX-WEATHER compulsory kit.",
         "Quads on fire by rep 6.", False),
        ("rest", "REST or easy walk", None, None, 30, None, None, 1,
         "Full rest preferred. If restless: 30 min walk.",
         "Walk if you want. Nothing more.", False),
        ("long_run", "Long run (final big one)", 32, 1800, 210, "Z2", 160, 6,
         "Second-longest run. Different route from week 9. COLD WATER IMMERSION: include river or dam crossing. Full race kit and nutrition. 300 cal/hour.",
         "Final big one. Run with confidence.", True),
    ]

def week11():
    return [
        ("easy_trail", "Easy trail run + core", 9, 400, 60, "Z1-Z2", 150, 3,
         "Core x3 on balance pad post-run.",
         "Finish feeling like you could do it again.", False),
        ("strength", "Strength (final session)", None, None, 30, None, None, 4,
         "LAST strength session before race week. 2x6 on all exercises, light loads.",
         "Leave feeling better than when you arrived.", False),
        ("prologue_sim", "Prologue dress rehearsal", 5, 200, 30, "Z4-Z5", 185, 9,
         "5 km time-trial on technical trail. Race shoes, race kit, race effort. Compare to weeks 7 and 9.",
         "Nauseous at the finish.", True),
        ("rest", "REST", None, None, 15, None, None, 0,
         "Mobility + visualisation.",
         "No effort.", False),
        ("hill_repeats", "STAIR REPEATS (abbreviated) + trail run", 14, 650, 90, "Z3", 170, 7,
         "Final stair session: 4x repeats at Z3 (not Z4, reduced intensity). Then continue: 14 km total, Z2, relaxed.",
         "Reduced intensity. 4 reps not 6.", False),
        ("rest", "REST", None, None, 0, None, None, 0,
         "Full rest.",
         "No effort.", False),
        ("long_run", "Long run (last pre-taper)", 22, 1000, 140, "Z2", 157, 5,
         "Shorter and easier than weeks 9-10. Z2 throughout. 300 cal/hour from km 5 onwards. Practice race-morning routine.",
         "Controlled and confident. Not a test, a rehearsal.", True),
    ]

def week12():
    return [
        ("easy_trail", "Easy trail run", 8, 350, 55, "Z1-Z2", 150, 3,
         "Z1-Z2. Short and controlled. WEATHER KIT PREPARATION: prepare min-weather and max-weather compulsory kit configs.",
         "Taper pace. Embarrassingly easy.", False),
        ("strength", "Core only (no strength)", None, None, 25, None, None, 3,
         "Core circuit x2. 10 min mobility. No weights.",
         "Light. Maintenance only.", False),
        ("sharpener", "Sharpener session", 9, 200, 50, "Z4-Z5", 180, 8,
         "Warm up 2 km. 4x2 min at Z4-Z5 (170-180 bpm) uphill trail. Full recovery 3-4 min between reps. Cool down 2 km. Do NOT add extra reps.",
         "Short, sharp, go home. RPE 7-8 on intervals only.", True),
        ("rest", "REST", None, None, 15, None, None, 0,
         "Mobility + foam roll. Begin packing race bag.",
         "No effort.", False),
        ("easy_trail", "Easy trail run", 9, 350, 60, "Z1-Z2", 150, 3,
         "Last trail run before travel. Z1-Z2. Include a few 30-second pickups to keep legs responsive.",
         "Taper pace.", False),
        ("easy_trail", "Easy jog or walk", 5, 0, 35, "Z1", 140, 1,
         "Z1 or 30-min walk. Nothing more.",
         "Walk. Nothing more.", False),
        ("rest", "REST", None, None, 0, None, None, 0,
         "Full rest. Sleep. Hydrate. Finalise logistics.",
         "No effort.", True),
    ]

def week13():
    return [
        ("easy_trail", "Travel day / easy shakeout", 4, 0, 30, "Z1", 140, 2,
         "If at race venue: 4 km easy jog on nearby trails. If travelling: walk and stretch.",
         "Barely a workout.", False),
        ("activation", "Activation run + strides", 3, 0, 25, "Z1", 145, 3,
         "3 km easy jog + 4x80m strides on flat ground. Z1 jog, strides at race pace feel. Core circuit x1 (light). Final kit check.",
         "RPE 2-3 for jog, RPE 6 for strides.", False),
        ("race", "RACE DAY 1: PROLOGUE", 5, 200, 35, "Z4-Z5", 185, 9,
         "4.8 km technical time trial. Controlled start Z4, settle into threshold Z4 170-177 bpm. Final 800m open to Z5 if legs feel good.",
         "Race effort. Controlled start, not all-out. Nauseous at the finish is correct.", True),
        ("race", "RACE DAY 2: MAIN RACE", 42, 2600, 390, "Z2-Z4", 177, 9,
         "42 km, 2600 m vert. Target 6:00-6:30. Km 0-10 Z2 (145-155). Km 10-20 Z2-Z3 (150-165). Km 20-30 effort by feel. Km 30-42 everything you have. 300 cal/hour.",
         "RPE 5 first 10km, RPE 7 km 10-30, RPE 9+ km 30-42. Leave nothing.", True),
        ("rest", "Post-race recovery", None, None, 0, None, None, 0,
         "Recover. Walk. Celebrate. You finished the Otter.",
         "No running. You earned this.", False),
        ("rest", "Post-race recovery", None, None, 0, None, None, 0,
         "Recover.",
         "No running.", False),
        ("rest", "Post-race recovery", None, None, 0, None, None, 0,
         "Recover.",
         "No running.", False),
    ]

WEEK_FUNCTIONS = [
    week1, week2, week3, week4, week5, week6, week7,
    week8, week9, week10, week11, week12, week13,
]


def build_rows():
    rows = []
    for week_info, week_func in zip(WEEKS, WEEK_FUNCTIONS):
        wn, start, phase, w_km, w_vert = week_info
        days = week_func()
        for i, day_data in enumerate(days):
            (stype, sname, tkm, tvert, tdur, tzone, thr_max, trpe,
             desc, effort, is_key) = day_data
            plan_date = start + timedelta(days=i)
            dow = DAYS[i]
            rows.append({
                "plan_date": plan_date.isoformat(),
                "week_number": wn,
                "phase": phase,
                "day_of_week": dow,
                "session_type": stype,
                "session_name": sname,
                "target_km": tkm,
                "target_vert_m": tvert,
                "target_duration_min": tdur,
                "target_hr_zone": tzone,
                "target_hr_max": thr_max,
                "target_rpe": trpe,
                "week_target_km": float(w_km),
                "week_target_vert": float(w_vert),
                "description": desc,
                "effort_description": effort,
                "is_key_session": is_key,
            })
    return rows


def main():
    client = bigquery.Client(project=PROJECT)

    # Clear existing rows (idempotent re-run)
    client.query(f"DELETE FROM `{TABLE}` WHERE TRUE").result()
    print("Cleared existing rows.")

    rows = build_rows()
    print(f"Built {len(rows)} rows.")

    errors = client.insert_rows_json(TABLE, rows)
    if errors:
        print(f"BQ insert errors: {errors}")
    else:
        print(f"Inserted {len(rows)} rows into {TABLE}")

    # Verify
    result = client.query(f"SELECT COUNT(*) as cnt FROM `{TABLE}`").result()
    for row in result:
        print(f"Verified: {row.cnt} rows in table.")


if __name__ == "__main__":
    main()
