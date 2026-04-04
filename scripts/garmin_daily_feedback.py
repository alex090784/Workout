#!/usr/bin/env python3
"""
Daily Garmin Connect session analyser
Pulls yesterday's activity and generates professional trail running coaching feedback
Inspired by: Jason Koop (ultrarunning), Joe Friel (triathlete's bible),
             Steve Magness (science of running), Maffetone (aerobic base)
"""

import json
import sys
import os
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from datetime import datetime, timedelta, date
from garminconnect import Garmin
import garth

# ── Config ───────────────────────────────────────────────────────────────────
TOKEN_STORE  = os.path.expanduser("~/.garth")
OUTPUT_FILE  = os.path.expanduser("~/projects/garmin/data/garmin_daily_log.md")
LT_HR        = 176   # Lactate threshold HR (from Garmin profile)
MAX_HR       = 198   # Estimated true max HR

# ── Load email config ─────────────────────────────────────────────────────────
def load_email_config():
    config_file = os.path.expanduser("~/.garmin_email_config")
    config = {}
    with open(config_file) as f:
        for line in f:
            line = line.strip()
            if "=" in line and not line.startswith("#"):
                k, v = line.split("=", 1)
                config[k.strip()] = v.strip()
    return config

# ── Send email ────────────────────────────────────────────────────────────────
def send_email(subject, markdown_body):
    try:
        cfg = load_email_config()
        # Convert markdown to clean HTML
        html = markdown_to_html(markdown_body)
        msg = MIMEMultipart("alternative")
        msg["Subject"] = subject
        msg["From"]    = f"Garmin Coach <{cfg['GMAIL_USER']}>"
        msg["To"]      = cfg["RECIPIENT"]
        msg.attach(MIMEText(markdown_body, "plain"))
        msg.attach(MIMEText(html, "html"))
        with smtplib.SMTP_SSL("smtp.gmail.com", 465) as smtp:
            smtp.login(cfg["GMAIL_USER"], cfg["GMAIL_APP_PASSWORD"])
            smtp.sendmail(cfg["GMAIL_USER"], cfg["RECIPIENT"], msg.as_string())
        print("✅ Email sent successfully")
    except Exception as e:
        print(f"⚠️  Email failed: {e}")

def markdown_to_html(md):
    """Convert the markdown feedback to clean mobile-friendly HTML"""
    lines = md.split("\n")
    html_lines = ["""
    <html><body style="font-family:-apple-system,sans-serif;max-width:600px;
    margin:0 auto;padding:20px;background:#f9f9f9;color:#222;">
    <div style="background:white;border-radius:12px;padding:24px;
    box-shadow:0 2px 8px rgba(0,0,0,0.08);">
    """]
    for line in lines:
        if line.startswith("# "):
            html_lines.append(f'<h1 style="color:#1a1a2e;font-size:20px;margin-bottom:4px">{line[2:]}</h1>')
        elif line.startswith("## "):
            html_lines.append(f'<h2 style="color:#16213e;font-size:16px;border-bottom:2px solid #e8f4f8;padding-bottom:6px;margin-top:20px">{line[3:]}</h2>')
        elif line.startswith("**") and line.endswith("**"):
            html_lines.append(f'<p style="font-weight:700;margin:8px 0">{line[2:-2]}</p>')
        elif line.startswith("- "):
            html_lines.append(f'<li style="margin:4px 0;line-height:1.5">{line[2:]}</li>')
        elif line.startswith("✅"):
            html_lines.append(f'<p style="color:#2d6a4f;margin:6px 0">{line}</p>')
        elif line.startswith("⚠️"):
            html_lines.append(f'<p style="color:#e07c24;margin:6px 0">{line}</p>')
        elif line.startswith("🔴"):
            html_lines.append(f'<p style="color:#c62828;margin:6px 0">{line}</p>')
        elif line.startswith("🔵") or line.startswith("🟡") or line.startswith("🟢"):
            html_lines.append(f'<p style="font-weight:600;margin:8px 0">{line}</p>')
        elif line.startswith("*") and line.endswith("*") and not line.startswith("**"):
            html_lines.append(f'<p style="font-style:italic;color:#555;margin:4px 0">{line[1:-1]}</p>')
        elif line.startswith("---"):
            html_lines.append('<hr style="border:none;border-top:1px solid #eee;margin:16px 0">')
        elif line.strip() == "":
            html_lines.append("<br>")
        else:
            # Bold inline **text**
            import re
            line = re.sub(r'\*\*(.+?)\*\*', r'<strong>\1</strong>', line)
            html_lines.append(f'<p style="margin:4px 0;line-height:1.6">{line}</p>')
    html_lines.append("</div></body></html>")
    return "\n".join(html_lines)

# Zone boundaries based on LT HR (Friel method)
ZONES = {
    "Z1": (0,   141),   # Recovery        < 80% LT
    "Z2": (141, 158),   # Aerobic base      80–90% LT
    "Z3": (158, 167),   # Tempo             90–95% LT
    "Z4": (167, 178),   # Threshold         95–102% LT
    "Z5": (178, 999),   # VO2max / Race    >102% LT
}

def hr_zone(hr):
    for z, (lo, hi) in ZONES.items():
        if lo <= hr < hi:
            return z
    return "Z5"

def fmt_pace(min_per_km):
    if not min_per_km or min_per_km > 20: return "N/A"
    return f"{int(min_per_km)}:{int((min_per_km % 1) * 60):02d}/km"

def fmt_duration(minutes):
    h = int(minutes // 60)
    m = int(minutes % 60)
    return f"{h}h{m:02d}m" if h else f"{m}min"

# ── Authenticate ─────────────────────────────────────────────────────────────
def get_client():
    try:
        client = Garmin()
        client.garth.load(TOKEN_STORE)
        return client
    except Exception as e:
        print(f"Session error: {e}")
        print("Tokens may have expired. Please run garmin_save_session.py first.")
        sys.exit(1)

# ── Pull activities ───────────────────────────────────────────────────────────
def get_recent_activities(client, days=3):
    """Pull last 3 days to handle rest days gracefully"""
    activities = client.get_activities(0, 10)
    cutoff = datetime.today() - timedelta(days=days)
    recent = []
    for a in activities:
        dt_str = a.get("startTimeLocal", "")[:19]
        try:
            dt = datetime.fromisoformat(dt_str)
            if dt >= cutoff:
                recent.append(a)
        except:
            pass
    return recent

# ── Generate coaching feedback ────────────────────────────────────────────────
def analyse_activity(a, all_recent):
    name      = a.get("activityName", "Unnamed")
    dt_str    = a.get("startTimeLocal", "")[:19]
    dt        = datetime.fromisoformat(dt_str)
    act_type  = a.get("activityType", {}).get("typeKey", "running")
    dist_km   = round((a.get("distance") or 0) / 1000, 2)
    dur_min   = round((a.get("duration") or 0) / 60, 1)
    elev_m    = round(a.get("elevationGain") or 0, 0)
    avg_hr    = a.get("averageHR")
    max_hr_act= a.get("maxHR")
    avg_pace  = round((a.get("duration") or 0) / 60 / ((a.get("distance") or 1) / 1000), 2) if a.get("distance") else None
    te        = a.get("aerobicTrainingEffect")
    vo2       = a.get("vO2MaxValue")
    calories  = a.get("calories") or 0
    m_per_km  = round(elev_m / dist_km, 1) if dist_km else 0

    lines = []
    lines.append(f"# Daily Training Feedback — {dt.strftime('%A %d %B %Y')}")
    lines.append(f"*Generated by your AI coaching assistant*\n")

    # ── Session Header ────────────────────────────────────────────────────────
    lines.append("## Session Summary")
    lines.append(f"**{name}**")
    lines.append(f"- Type: {act_type.replace('_', ' ').title()}")
    lines.append(f"- Distance: {dist_km} km")
    lines.append(f"- Duration: {fmt_duration(dur_min)}")
    lines.append(f"- Elevation: +{elev_m:.0f}m  ({m_per_km}m/km)")
    lines.append(f"- Avg pace: {fmt_pace(avg_pace)}")
    lines.append(f"- Avg HR: {avg_hr:.0f} bpm  |  Max HR: {max_hr_act:.0f} bpm" if avg_hr else "- HR: N/A")
    lines.append(f"- Training Effect: {te:.1f}/5.0" if te else "")
    lines.append(f"- VO2max estimate: {vo2:.0f}" if vo2 else "")
    lines.append(f"- Calories: {calories:.0f} kcal\n")

    # ── HR Zone Analysis ──────────────────────────────────────────────────────
    if avg_hr:
        zone = hr_zone(avg_hr)
        lines.append("## Heart Rate Analysis")

        zone_desc = {
            "Z1": "Recovery — very easy, below aerobic threshold",
            "Z2": "Aerobic base — ideal for easy and long runs",
            "Z3": "Tempo — comfortably hard, upper aerobic",
            "Z4": "Threshold — lactate threshold zone, race effort",
            "Z5": "VO2max — maximum effort, intervals only",
        }
        lines.append(f"**Average HR: {avg_hr:.0f} bpm → {zone} ({zone_desc[zone]})**")

        # HR interpretation
        if zone == "Z1":
            lines.append("✅ Perfect recovery intensity. Your cardiovascular system is being efficiently restored.")
        elif zone == "Z2":
            lines.append("✅ Solid aerobic base work. This is where your fat oxidation engine is built.")
            if avg_hr > 152:
                lines.append("⚠️  Upper Z2 — watch for drift. If this was a 'long easy' session, aim to keep avg HR 5 bpm lower next time.")
        elif zone == "Z3":
            if "easy" in name.lower() or "recovery" in name.lower() or "z2" in name.lower():
                lines.append("⚠️  **Zone mismatch**: Session was labelled easy/Z2 but avg HR landed in Z3.")
                lines.append("   → This is the 'grey zone' — too hard to recover, not hard enough to meaningfully improve threshold.")
                lines.append("   → Per Koop (Training Essentials for Ultrarunning): the grey zone is where most athletes over-train. Slow down on easy days.")
            else:
                lines.append("✅ Z3 is appropriate for quality mid-week efforts and trail terrain.")
        elif zone == "Z4":
            lines.append("🔴 High intensity session. Z4 requires 48h full recovery before next quality effort.")
            lines.append("   → Limit Z4+ sessions to 1–2 per week maximum (Friel's 80/20 principle).")
        elif zone == "Z5":
            lines.append("🔴 Maximum effort. This should be rare — intervals or race only.")
            lines.append("   → Ensure 2–3 easy days follow this session before any quality work.")

        # Max HR flag
        if max_hr_act and max_hr_act > 180:
            lines.append(f"\n⚡ Max HR hit {max_hr_act:.0f} bpm — you pushed into true VO2max territory.")
        lines.append("")

    # ── Effort Quality Assessment ─────────────────────────────────────────────
    lines.append("## Effort Quality")

    if te:
        if te >= 4.5:
            lines.append(f"**Training Effect {te:.1f} — Highly Improving** ✅")
            lines.append("Peak stimulus. Your body will adapt strongly to this session. Prioritise sleep tonight (aim 8–9hrs).")
        elif te >= 3.5:
            lines.append(f"**Training Effect {te:.1f} — Improving** ✅")
            lines.append("Good training stimulus. This session is building your aerobic engine effectively.")
        elif te >= 2.5:
            lines.append(f"**Training Effect {te:.1f} — Maintaining** ⚪")
            lines.append("Maintenance stimulus. Fine for a recovery day or high-volume week buffer.")
        else:
            lines.append(f"**Training Effect {te:.1f} — Recovery** 🔵")
            lines.append("Very light session. Good if this was planned recovery; if not, consider adding more volume next time.")

    # Elevation density insight
    if m_per_km > 70:
        lines.append(f"\n🏔️  **Mountain density: {m_per_km}m/km** — extremely vert-heavy.")
        lines.append("   This demands specific quad and hip flexor recovery. Protein + elevation legs tonight.")
    elif m_per_km > 40:
        lines.append(f"\n⛰️  **Elevation density: {m_per_km}m/km** — solid mountain load.")
    elif m_per_km < 10 and dist_km > 10:
        lines.append(f"\n🛣️  Flat session ({m_per_km}m/km). Good for speed/efficiency work.")
    lines.append("")

    # ── Pace vs HR Efficiency ─────────────────────────────────────────────────
    if avg_pace and avg_hr and avg_hr > 0:
        lines.append("## Efficiency Index")
        speed_kmh = 60 / avg_pace
        efficiency = round(avg_hr / speed_kmh, 2)
        lines.append(f"HR/Speed ratio: **{efficiency:.2f}** (lower = more efficient)")

        if efficiency < 14.5:
            lines.append("✅ Excellent aerobic efficiency. Your fitness is translating well to performance.")
        elif efficiency < 16.5:
            lines.append("✅ Good efficiency — normal for trail running with elevation.")
        elif efficiency < 19.0:
            lines.append("⚠️  Moderate efficiency. Could indicate fatigue, heat, or technical terrain.")
        else:
            lines.append("🔴 Low efficiency. Possible causes: accumulated fatigue, illness onset, excessive heat, or very steep terrain.")
            lines.append("   → If this is 2nd+ day of low efficiency, consider a complete rest day.")
        lines.append("")

    # ── Load Context ──────────────────────────────────────────────────────────
    lines.append("## Load Context")
    total_recent_km = sum((a2.get("distance") or 0)/1000 for a2 in all_recent)
    total_recent_elev = sum(a2.get("elevationGain") or 0 for a2 in all_recent)
    lines.append(f"Last 3 days total: **{total_recent_km:.1f} km / +{total_recent_elev:.0f}m**")

    if len(all_recent) >= 2:
        days_run = len(all_recent)
        if days_run >= 3:
            lines.append(f"⚠️  {days_run} consecutive sessions in 3 days. Monitor for early fatigue signals.")
            lines.append("   → Steve Magness: 'Accumulated fatigue is invisible until it isn't. Listen to the data.'")
        else:
            lines.append("✅ Load distribution looks balanced over the last 3 days.")
    lines.append("")

    # ── Recovery Prescription ─────────────────────────────────────────────────
    lines.append("## Recovery Prescription")

    if te and te >= 4.5:
        lines.append("- **Tonight**: 8–9hrs sleep. This is non-negotiable after a TE 4.5+ session.")
        lines.append("- **Nutrition**: 1.6–2.0g protein/kg bodyweight. Carb refuel within 30min of finishing.")
        lines.append("- **Tomorrow**: Easy Z2 only OR full rest. No quality work for 48hrs.")
    elif te and te >= 3.5:
        lines.append("- **Tonight**: 7–8hrs sleep. Legs up if possible in the evening.")
        lines.append("- **Nutrition**: Solid carb + protein meal within 60min.")
        lines.append("- **Tomorrow**: Easy Z2 run fine. Avoid hills if legs feel heavy.")
    elif zone == "Z4" or zone == "Z5":
        lines.append("- **Tonight**: Prioritise sleep — hard HR session needs full recovery.")
        lines.append("- **Tomorrow**: Full rest or 30min very easy jog only. HR must stay in Z1.")
    else:
        lines.append("- **Tonight**: Normal sleep (7hrs+).")
        lines.append("- **Tomorrow**: Ready for quality work if scheduled.")

    if elev_m > 1000:
        lines.append("- **Specific to today**: High elevation session — focus on quad foam rolling and calf stretching tonight.")
    lines.append("")

    # ── Tomorrow's Focus ──────────────────────────────────────────────────────
    lines.append("## Tomorrow's Focus")
    tomorrow = dt + timedelta(days=1)
    lines.append(f"*{tomorrow.strftime('%A %d %B')}*")

    if te and te >= 4.0 and zone in ("Z3", "Z4", "Z5"):
        lines.append("🔵 **Active recovery or full rest** — your body needs to absorb today's work.")
        lines.append("   If running: max 45min, HR under 150, flat terrain, no effort.")
    elif zone == "Z2" and dist_km > 20:
        lines.append("🟡 **Easy day** — long runs require recovery even at easy effort.")
        lines.append("   If running: 45–60min easy, listen to your legs.")
    elif zone == "Z1" or (te and te < 2.5):
        lines.append("🟢 **Ready for quality** — legs are fresh, good day for intervals or threshold work.")
    else:
        lines.append("🟡 **Moderate day** — assess how legs feel in the morning. Easy Z2 is always a safe choice.")
    lines.append("")

    # ── Key Coaching Quote ────────────────────────────────────────────────────
    import random
    quotes = [
        ("Jason Koop", "The biggest mistake ultrarunners make is running their easy days too hard and their hard days not hard enough."),
        ("Kilian Jornet", "I don't train to be ready for a race. I train to be ready for life in the mountains."),
        ("Joe Friel", "Aerobic capacity is built slowly, over years. It cannot be rushed — only damaged."),
        ("Steve Magness", "Fatigue is a signal. The question is whether you're listening."),
        ("Courtney Dauwalter", "Embrace the suffering. It means you're doing it right."),
        ("Maffetone", "The faster you run slow, the faster you'll run fast."),
        ("Scott Jurek", "Consistency over intensity. Every time."),
    ]
    author, quote = random.choice(quotes)
    lines.append(f"---")
    lines.append(f"*\"{quote}\"*")
    lines.append(f"— **{author}**")

    return "\n".join(lines)

# ── Rest day feedback ──────────────────────────────────────────────────────────
def rest_day_feedback(last_activity_date):
    today = datetime.today()
    lines = []
    lines.append(f"# Daily Training Check — {today.strftime('%A %d %B %Y')}")
    lines.append(f"*Generated by your AI coaching assistant*\n")
    lines.append("## Today: Rest Day ✅")
    lines.append(f"No activity recorded today or yesterday.")
    if last_activity_date:
        days_off = (today.date() - last_activity_date).days
        lines.append(f"Days since last session: **{days_off}**")
        if days_off <= 2:
            lines.append("\n✅ Normal recovery window. Your body is adapting to the recent training load.")
        elif days_off <= 5:
            lines.append(f"\n⚠️  {days_off} days off. Check in with how you're feeling — illness or planned rest?")
        else:
            lines.append(f"\n🔴 {days_off} days without running. If unplanned, ease back with a short Z2 session tomorrow.")
    lines.append("\n### Rest Day Recommendations")
    lines.append("- 15–20min mobility work (hip flexors, glutes, calves)")
    lines.append("- Hydration: 2–3L water")
    lines.append("- Sleep 8hrs tonight to maximise adaptation from recent sessions")
    lines.append("- Mental: visualise your MUT George race — route, pacing, nutrition execution")
    return "\n".join(lines)

# ── Main ──────────────────────────────────────────────────────────────────────
def main():
    client = get_client()
    recent = get_recent_activities(client, days=2)

    if not recent:
        # Try to get last activity for context
        all_acts = client.get_activities(0, 5)
        last_date = None
        if all_acts:
            try:
                last_date = datetime.fromisoformat(all_acts[0].get("startTimeLocal","")[:19]).date()
            except: pass
        feedback = rest_day_feedback(last_date)
    else:
        # Most recent activity
        latest = sorted(recent, key=lambda x: x.get("startTimeLocal",""), reverse=True)[0]
        all_recent_3d = get_recent_activities(client, days=3)
        feedback = analyse_activity(latest, all_recent_3d)

    # Write to log file (append)
    today_str = datetime.today().strftime("%Y-%m-%d")
    with open(OUTPUT_FILE, "a") as f:
        f.write(f"\n\n<!-- {today_str} -->\n")
        f.write(feedback)
        f.write("\n\n---\n")

    # Print to stdout (for cron log)
    print(feedback)

    # Send email
    today_label = datetime.today().strftime("%a %d %b")
    subject = f"🏔️ Training Feedback — {today_label}"
    send_email(subject, feedback)

    # Mac notification
    import subprocess
    notif_body = ""
    for line in feedback.split("\n"):
        if line.startswith("✅") or line.startswith("⚠️") or line.startswith("🔴") or line.startswith("🔵"):
            notif_body = line[:80]
            break
    if not notif_body:
        notif_body = "Feedback sent to alexisclermont@gmail.com"

    subprocess.run([
        "osascript", "-e",
        f'display notification "{notif_body}" with title "🏔️ Training Feedback" subtitle "Check your inbox"'
    ])

if __name__ == "__main__":
    main()
