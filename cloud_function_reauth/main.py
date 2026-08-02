#!/usr/bin/env python3
"""
Garmin full re-authentication Cloud Function.

Runs on a Cloud Scheduler cron every 20 days (well before the 30-day
OAuth2 refresh token expiry). Performs a fresh garth.login() using
credentials stored in Secret Manager, then saves the new OAuth1 +
OAuth2 tokens back to Secret Manager so the daily feedback function
never hits an expired refresh token.

This function is intentionally separate from the daily feedback function
so a re-auth failure does not block coaching email delivery and vice versa.

Security posture:
- Credentials are stored in Secret Manager, not in environment variables
  or source code.
- The function SA requires only secretmanager.secretVersions.access and
  secretmanager.secretVersions.add on the four relevant secrets.
- No credentials are logged.
- MFA: the garth login call uses return_on_mfa=True. If Garmin ever
  enables MFA on this account, the function returns HTTP 424 and sends
  an alert email so the operator can handle it manually.
"""

import json
import os
import smtplib
import time
import functions_framework

from email.mime.text import MIMEText
from google.cloud import secretmanager

import garth

PROJECT_ID = "abm2020"
TOKEN_DIR  = "/tmp/.garth"


# ---------------------------------------------------------------------------
# Secret Manager helpers
# ---------------------------------------------------------------------------

def _sm_client():
    return secretmanager.SecretManagerServiceClient()


def get_secret(secret_id: str) -> str:
    name = f"projects/{PROJECT_ID}/secrets/{secret_id}/versions/latest"
    resp = _sm_client().access_secret_version(request={"name": name})
    return resp.payload.data.decode("utf-8")


def update_secret(secret_id: str, value: str | bytes) -> None:
    if isinstance(value, str):
        value = value.encode("utf-8")
    parent = f"projects/{PROJECT_ID}/secrets/{secret_id}"
    _sm_client().add_secret_version(
        request={"parent": parent, "payload": {"data": value}}
    )


# ---------------------------------------------------------------------------
# Core re-authentication
# ---------------------------------------------------------------------------

def do_reauth() -> dict:
    """
    Perform a full Garmin re-authentication using stored credentials.

    Returns a dict with keys:
        success (bool)
        message (str)
        mfa_required (bool)   — True if Garmin prompted for MFA
        new_refresh_expires (str) — ISO date of new refresh token expiry (on success)
    """
    os.makedirs(TOKEN_DIR, exist_ok=True)

    # Load credentials from Secret Manager
    creds_raw = get_secret("garmin-credentials")
    creds = json.loads(creds_raw)
    email    = creds["email"]
    password = creds["password"]

    if not email or not password:
        return {
            "success": False,
            "message": "garmin-credentials secret is missing email or password",
            "mfa_required": False,
        }

    # Perform login — never log credentials
    print(f"Starting garth.login() for {email[:3]}***@***")

    result = garth.login(email, password, return_on_mfa=True)

    # Detect if MFA is required
    if isinstance(result, tuple) and result[0] == "needs_mfa":
        return {
            "success": False,
            "message": "Garmin MFA challenge encountered — manual intervention required",
            "mfa_required": True,
        }

    # Login succeeded — save tokens
    garth.save(TOKEN_DIR)

    with open(f"{TOKEN_DIR}/oauth2_token.json") as f:
        oauth2_raw = f.read()
    with open(f"{TOKEN_DIR}/oauth1_token.json") as f:
        oauth1_raw = f.read()

    # Check whether tokens actually changed before writing new SM versions
    try:
        current_oauth2 = get_secret("garmin-oauth2-token")
        oauth2_changed = oauth2_raw != current_oauth2
    except Exception:
        oauth2_changed = True

    try:
        current_oauth1 = get_secret("garmin-oauth1-token")
        oauth1_changed = oauth1_raw != current_oauth1
    except Exception:
        oauth1_changed = True

    if oauth2_changed:
        update_secret("garmin-oauth2-token", oauth2_raw)
        print("garmin-oauth2-token updated in Secret Manager.")
    else:
        print("garmin-oauth2-token unchanged — skipping write.")

    if oauth1_changed:
        update_secret("garmin-oauth1-token", oauth1_raw)
        print("garmin-oauth1-token updated in Secret Manager.")
    else:
        print("garmin-oauth1-token unchanged — skipping write.")

    # Parse new refresh token expiry for the response message
    token_data = json.loads(oauth2_raw)
    rt_exp_at  = token_data.get("refresh_token_expires_at", 0)
    rt_exp_str = time.strftime("%Y-%m-%d %H:%M UTC", time.gmtime(rt_exp_at))
    days_valid = round((rt_exp_at - time.time()) / 86400, 1)

    return {
        "success": True,
        "message": f"Re-auth successful. New refresh token valid until {rt_exp_str} ({days_valid} days).",
        "mfa_required": False,
        "new_refresh_expires": rt_exp_str,
    }


# ---------------------------------------------------------------------------
# Alert email
# ---------------------------------------------------------------------------

def send_alert(subject: str, body: str) -> None:
    try:
        gmail_user = get_secret("garmin-gmail-user")
        app_pw     = get_secret("garmin-gmail-app-password")
        msg = MIMEText(body)
        msg["Subject"] = subject
        msg["From"]    = f"Garmin Auth Bot <{gmail_user}>"
        msg["To"]      = gmail_user
        with smtplib.SMTP_SSL("smtp.gmail.com", 465) as smtp:
            smtp.login(gmail_user, app_pw)
            smtp.sendmail(gmail_user, gmail_user, msg.as_string())
        print(f"Alert email sent: {subject}")
    except Exception as e:
        print(f"Alert email failed: {e}")


# ---------------------------------------------------------------------------
# Cloud Function entry point
# ---------------------------------------------------------------------------

@functions_framework.http
def garmin_reauth(request):
    """HTTP Cloud Function — triggered by Cloud Scheduler every 20 days."""
    print("garmin_reauth invoked")

    try:
        result = do_reauth()
    except Exception as e:
        import traceback
        tb = traceback.format_exc()
        msg = f"garmin_reauth fatal error: {e}\n\n{tb}"
        print(msg)
        send_alert(
            subject="ALERT: Garmin re-auth failed",
            body=msg,
        )
        return (msg, 500)

    if result.get("mfa_required"):
        body = (
            "Garmin re-authentication was blocked by an MFA challenge.\n\n"
            "Action required: log in to Garmin Connect and check your 2FA settings, "
            "or run garmin_save_session.py on the Mac and push new tokens manually.\n\n"
            "The daily coaching emails will continue working until the current refresh "
            "token expires."
        )
        send_alert(subject="ACTION REQUIRED: Garmin MFA challenge", body=body)
        return ("MFA required — alert sent", 424)

    if not result["success"]:
        msg = f"Re-auth failed: {result['message']}"
        print(msg)
        send_alert(subject="ALERT: Garmin re-auth failed", body=msg)
        return (msg, 500)

    # Success
    print(result["message"])
    return (result["message"], 200)
