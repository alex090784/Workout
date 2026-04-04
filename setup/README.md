# Garmin Training Analysis System
**Setup date:** 29 March 2026
**Athlete:** Alexis de Clermont-Tonnerre (Garmin: alexisclermont@gmail.com)
**Next race:** MUT George — end of May 2026 (~42km, ~2000m+)

---

## What Was Built

### 1. Garmin Data Fetch (`~/garmin_fetch.py`)
One-time script that pulled 12 months of activity summaries from Garmin Connect API.
- Output: `~/garmin_running_data.json` (150 activities, Mar 2025–Mar 2026)
- Run: `~/garmin_venv/bin/python3 ~/garmin_fetch.py`

### 2. Annual Training Analysis (`~/garmin_analyse.py` + `~/garmin_deep_analyse.py`)
Full 12-month statistical breakdown of training data.
- Run: `~/garmin_venv/bin/python3 ~/garmin_analyse.py`

### 3. FIT File Parser (`~/fit_parse_all.py`)
Parses all 173 raw FIT files from TrainingPeaks export into rich JSON.
- Input: `~/Downloads/WorkoutFileExport-de Clermont-Tonnerre-Alexis-2025-03-29-2026-03-29/`
- Output: `~/fit_all_sessions.json` (172 sessions with per-second HR, power, cadence, GPS)
- Run: `~/garmin_venv/bin/python3 ~/fit_parse_all.py`

### 4. FIT Deep Analysis (`~/fit_deep_analysis.py`)
Advanced analysis using FIT data: running power, decoupling, economy metrics, zone distribution.
- Run: `~/garmin_venv/bin/python3 ~/fit_deep_analysis.py`

### 5. Daily Feedback Script (`~/garmin_daily_feedback.py`) ⭐ MAIN AUTOMATION
Runs every day at 7am, pulls latest Garmin activity, generates coaching feedback, sends email.
- Sends to: alexisclermont@gmail.com
- Saves to: `~/garmin_daily_log.md`
- Cron log: `~/garmin_cron.log`
- Run manually: `~/garmin_venv/bin/python3 ~/garmin_daily_feedback.py`

### 6. MUT George 9-Week Training Plan (`~/MUT_George_9week_plan.txt`)
Full day-by-day training plan from 30 Mar → 30 May 2026.
- Phases: Build (wk 1–3) → Peak (wk 4–6) → Taper (wk 7–8) → Race week
- Peak volume: ~95km / ~4200m vert (week of Apr 27)
- Race target: 4h30–4h50

---

## File Map

```
~/
├── garmin_venv/                    Python virtual environment
│   └── bin/python3                 Use this to run all scripts
├── garmin_fetch.py                 One-time Garmin API data pull
├── garmin_running_data.json        12-month activity summaries (API)
├── garmin_analyse.py               Basic annual analysis
├── garmin_deep_analyse.py          Deep annual analysis
├── fit_parse_all.py                FIT file bulk parser
├── fit_all_sessions.json           Rich per-session FIT data (172 sessions)
├── fit_deep_analysis.py            Advanced FIT analysis
├── fit_explore.py                  FIT file structure explorer
├── garmin_daily_feedback.py        ⭐ Daily coaching feedback (runs via cron)
├── garmin_save_session.py          One-time Garmin token saver
├── garmin_daily_log.md             Cumulative daily feedback archive
├── garmin_cron.log                 Cron job output log
├── MUT_George_9week_plan.txt       Full race prep training plan
├── tp_test.py                      TrainingPeaks API test (failed — TP blocks unofficial API)
├── tp_test2.py                     TP auth attempt v2 (failed)
├── tp_find_clientid.py             TP client ID scraper (inconclusive)
│
~/.garth/                           Garmin OAuth session tokens (auto-refreshes)
│   ├── oauth1_token.json
│   └── oauth2_token.json           Expires ~28 April 2026 → re-run garmin_save_session.py
│
~/.garmin_email_config              Gmail credentials (chmod 600, owner-only)
```

---

## Cron Job

Runs daily at 7am SAST (South Africa Standard Time):
```
0 7 * * * /Users/alexct/garmin_venv/bin/python3 /Users/alexct/garmin_daily_feedback.py >> /Users/alexct/garmin_cron.log 2>&1
```

Manage:
```bash
crontab -l                    # view
crontab -e                    # edit
```

---

## Maintenance

### Garmin token refresh (~every 30 days)
Tokens expire around **28 April 2026**. Run:
```bash
~/garmin_venv/bin/python3 ~/garmin_save_session.py
```

### If cron stops working
```bash
cat ~/garmin_cron.log          # check for errors
~/garmin_venv/bin/python3 ~/garmin_daily_feedback.py   # test manually
```

### Update FIT dataset after new training export
1. Download new export from TrainingPeaks → Activities → Export
2. Replace the export folder
3. Run: `~/garmin_venv/bin/python3 ~/fit_parse_all.py`

---

## Athlete Profile & Key Findings

### 12-Month Stats (Mar 2025 – Mar 2026)
| Metric | Value |
|--------|-------|
| Total distance | 1,979 km |
| Total elevation | 85,200 m |
| Total time | 223 hrs |
| Activities | 150 (106 trail / 44 road) |
| Avg km/week | 38 km |
| Peak week | 79.5 km |
| Consistency | 49/52 weeks (94%) |

### Physiological Profile
| Metric | Value | Notes |
|--------|-------|-------|
| VO2max (Garmin) | 55 | Likely underestimated for trail runners |
| Lactate threshold HR | 176 bpm | From Garmin profile |
| Est. true max HR | ~198 bpm | Back-calculated from LT |
| Avg running power | 296W (Jan–Mar 2026) | +14W above Aug–Oct 2025 peak |

### HR Zones (Friel LT-based, anchored on LT=176)
| Zone | BPM | Purpose |
|------|-----|---------|
| Z1 | <141 | Recovery |
| Z2 | 141–158 | Aerobic base (most runs) |
| Z3 | 158–167 | Tempo |
| Z4 | 167–178 | Threshold |
| Z5 | 178+ | VO2max |

### Key Strengths
- Excellent aerobic base (avg decoupling Jan–Mar 2026: -2.9%)
- Running power above peak despite lower volume
- 94% weekly consistency — elite level
- Proper polarized training distribution (86% aerobic in best months)

### Key Weaknesses / Watch Points
- Volume spikes: regularly breaks the 10% rule — biggest injury risk
- March 2026 showing 24% Z4 time — easy days not easy enough pre-race
- VO2max plateaued at 55 — needs 1 proper VO2max session/week to push higher
- Garmin tokens expire ~28 April — must refresh or daily emails stop

---

## TrainingPeaks Notes
- Account linked to Garmin Connect (activities auto-sync both ways)
- Username: Alex0907
- **API access failed** — TP uses PKCE browser-based OAuth, blocks unofficial access
- Workaround: using Garmin Connect API directly for all analysis

---

## MUT George 2026 — Race Plan
- **Date:** ~30 May 2026
- **Course:** ~42km, ~2000m elevation, George mountain terrain
- **Target:** 4h30–4h50
- **Benchmark:** May 2025 George run = 5h58m | Oct 2025 similar effort = 4h49m
- **Race strategy:** Cap HR at 155 for first 15km. Allow Z3/Z4 on climbs in middle third. Race on feel last 12km.
- **Nutrition:** Gel every 40–45min from km 10
- **Consider:** Poles for George vert (saves 8–12% leg fatigue on climbs)

---

## Coaching Framework Used
Analysis inspired by:
- **Jason Koop** — Training Essentials for Ultrarunning (load, polarization)
- **Joe Friel** — Triathlete's Training Bible (LT-based zones, decoupling)
- **Steve Magness** — Science of Running (fatigue signals, HR efficiency)
- **Maffetone** — aerobic base development, Z2 training
- **Kilian Jornet** — mountain-specific training philosophy
