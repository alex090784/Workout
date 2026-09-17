"""Canonical parser for the training_plan free-text `description` field.

SINGLE SOURCE OF TRUTH. Two Cloud Functions depend on this module:
  - cloud_function/main.py            (garmin-daily-feedback -- reads INTERVAL_SESSION_TYPES
                                        and _parse_session_structure() to isolate work reps
                                        from warm-up/cool-down/recovery in Garmin lap data)
  - cloud_function_sync/main.py       (training-plan-sync -- reads the same two symbols plus
                                        parse_recovery_minutes() to build intervals.icu's
                                        structured workout DSL from the same description text)

Do NOT copy/paste or reimplement any of this logic a second time. Two parsers reading the
same free-text field is the single most common failure mode surfaced across this project's
history (Rune/Aria review rounds, 2026-09-16, and the intervals.icu architecture review,
2026-09-17) -- a change made in one copy silently doesn't apply to the other, and a plan
authoring convention that changes (e.g. how recovery duration is phrased) has to be found
and fixed twice, or it drifts.

DEPLOYMENT NOTE: GCP Cloud Functions (2nd gen) deploy each function from its own isolated
source directory with no cross-function import support. This file is the canonical source;
`scripts/sync_shared_parser.sh` copies it byte-for-byte into cloud_function/session_parser.py
and cloud_function_sync/session_parser.py before every deploy, and verifies (sha256) that both
copies are identical to this canonical file and to each other. NEVER hand-edit the copies --
edit this file, then run that script, then deploy. If a copy and the canonical file are ever
found to differ, that is a bug: something was edited in the wrong place.
"""
import re

# session_type values prescribed as warm-up + work reps + recovery + cool-down (confirmed
# against every row in training_plan on 2026-09-16: each of these carries a "Warm up Xkm ...
# NxYmin ... Cool down Xkm" description and a "Course on watch" structured workout).
# Whole-activity average HR on these is meaningless -- it blends four different intensities
# into one number. 'long_run' can ALSO contain a race-effort segment but is NOT included
# here: it's one continuous run with an embedded effort block, not a rep/recovery structure.
# There is no 'intervals' session_type in the plan data -- don't add one speculatively; if
# the plan vocabulary changes, update this set to match.
INTERVAL_SESSION_TYPES = {"vo2max", "threshold", "hill_repeats", "sharpener"}


def _parse_session_structure(description):
    """Pull (warmup_km, cooldown_km, rep_count, rep_minutes) out of the plan's
    free-text description. Every INTERVAL_SESSION_TYPES row seen so far
    follows 'Warm up Xkm. ... NxYmin ... Cool down Xkm.' (or 'Nx hill reps,
    ~Ymin climb'). Any field this can't find comes back None -- callers must
    treat that as "unknown", never assume a default.

    `warmup_mentioned` / `cooldown_mentioned` (Rune IMPORTANT, 2026-09-16):
    whether the literal phrase appears in the text AT ALL, independent of
    whether a distance could be parsed from it. This distinguishes "no
    warm-up/cool-down in this session" (nothing to strip, fine) from
    "warm-up/cool-down exists but we don't know its length" (something IS
    sitting in the lap data that must not silently stay in `interior` just
    because the distance-based strip couldn't fire) -- confirmed live on 14
    of 28 current interval-type training_plan rows: text reads "Cool down."
    with no distance, e.g. "3x8min @ Z4 with 2min jog recovery. Cool down.
    Raising threshold ahead of the specific block."
    """
    d = description or ""
    wu = re.search(r'[Ww]arm[- ]?up\s+([\d.]+)\s*km', d)
    cd = re.search(r'[Cc]ool[- ]?down\s+([\d.]+)\s*km', d)
    rep = re.search(r'(\d+)\s*x\.?\s*(?:hill reps,?\s*~?)?(\d+)\s*min', d)
    return {
        "warmup_km":   float(wu.group(1)) if wu else None,
        "cooldown_km": float(cd.group(1)) if cd else None,
        "rep_count":   int(rep.group(1)) if rep else None,
        "rep_minutes": int(rep.group(2)) if rep else None,
        "warmup_mentioned":   bool(re.search(r'[Ww]arm[- ]?up', d)),
        "cooldown_mentioned": bool(re.search(r'[Cc]ool[- ]?down', d)),
    }


# Recovery-interval duration between work reps. Deliberately NOT part of
# _parse_session_structure()'s return dict above -- that function's callers
# (assess_interval_effort() in the daily-feedback CF) never needed recovery
# duration, only the isolation boundaries (warmup/cooldown/rep_count/rep_minutes).
# training-plan-sync needs it to build intervals.icu's step DSL (a fixed-duration
# recovery step between repeat-group work steps), so it's added here as a
# separate, explicit function rather than folded into the dict silently --
# a caller that doesn't ask for it doesn't pay for it or get surprised by a
# new key appearing.
#
# Text patterns actually seen across all 28 live interval-type training_plan
# rows at the time this was written (2026-09-17 intervals.icu rebuild):
#   "2min jog recovery", "3min jog/walk recovery", "3min recovery",
#   "2min recovery", "90sec recovery", "full 3min recovery"
# Two known gaps where no duration is stated in the text at all:
#   "jog down recovery"  (hill_repeats -- downhill jog, no time given)
#   "full recovery"      (sharpener -- no time given)
# parse_recovery_minutes() returns None for both; callers must supply their
# own documented fallback and MUST flag it as an assumption, never silently
# default here. (training-plan-sync's fallback rules are documented in its
# own main.py next to where this function is called.)
_RECOVERY_RE = re.compile(
    r'(\d+)\s*(min|sec)\s*(?:jog(?:/walk)?\s*)?recovery', re.IGNORECASE
)


def parse_recovery_minutes(description):
    """Return the stated recovery duration in minutes (float), or None if the
    text doesn't state one (see the two known-gap patterns documented above)."""
    d = description or ""
    m = _RECOVERY_RE.search(d)
    if not m:
        return None
    val, unit = int(m.group(1)), m.group(2).lower()
    return val / 60.0 if unit == "sec" else float(val)
