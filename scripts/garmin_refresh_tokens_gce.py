#!/usr/bin/env python3
"""
Refresh Garmin OAuth tokens on a GCP Compute Engine VM.

This is the GCE-adapted version of garmin_refresh_tokens.py. Key differences:
  - Uses google-cloud-secret-manager Python SDK instead of shelling out to gcloud CLI
  - Authenticates via the VM's attached service account (metadata server) -- no key files
  - No local ~/.garth/ update (there's no local user on the VM that needs it)
  - Designed to run unattended via systemd timer

The script:
  1. Reads current OAuth2 token from Secret Manager, checks expiry
  2. If within threshold: refreshes via OAuth1->OAuth2 exchange (garth)
  3. Falls back to full garth.login() using garmin-credentials secret
  4. Uploads refreshed tokens to Secret Manager

Exit codes: 0 = success (including "no refresh needed"), 1 = error.
"""

import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import garth
from google.cloud import secretmanager

PROJECT_ID = "abm2020"
LOG_PREFIX = "[garmin-refresh]"
REFRESH_THRESHOLD_HOURS = 6  # refresh when token has < 6h remaining
TMP_DIR = Path("/tmp/.garth_refresh")


def log(msg: str) -> None:
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    print(f"{LOG_PREFIX} {ts} {msg}", flush=True)


def _sm_client():
    """Lazy singleton for the Secret Manager client."""
    if not hasattr(_sm_client, "_instance"):
        _sm_client._instance = secretmanager.SecretManagerServiceClient()
    return _sm_client._instance


def secret_read(secret_id: str) -> str:
    """Read the latest version of a secret."""
    name = f"projects/{PROJECT_ID}/secrets/{secret_id}/versions/latest"
    response = _sm_client().access_secret_version(request={"name": name})
    return response.payload.data.decode("utf-8")


def secret_write(secret_id: str, value: str) -> None:
    """Add a new version to a secret."""
    parent = f"projects/{PROJECT_ID}/secrets/{secret_id}"
    _sm_client().add_secret_version(
        request={"parent": parent, "payload": {"data": value.encode("utf-8")}}
    )


def refresh_via_exchange(oauth2_json: str) -> bool:
    """Refresh by exchanging OAuth1 token for new OAuth2 token."""
    try:
        oauth1_json = secret_read("garmin-oauth1-token")
    except Exception as e:
        log(f"Failed to download OAuth1 token: {e}")
        return False

    TMP_DIR.mkdir(parents=True, exist_ok=True)
    (TMP_DIR / "oauth2_token.json").write_text(oauth2_json)
    (TMP_DIR / "oauth1_token.json").write_text(oauth1_json)

    try:
        garth.resume(str(TMP_DIR))
        garth.client.refresh_oauth2()
        garth.save(str(TMP_DIR))
        log("OAuth1->OAuth2 exchange succeeded")
        return True
    except Exception as e:
        log(f"OAuth1->OAuth2 exchange failed: {e}")
        return False


def refresh_via_login() -> bool:
    """Refresh by full SSO login with email/password."""
    try:
        creds = json.loads(secret_read("garmin-credentials"))
    except Exception as e:
        log(f"Failed to read credentials: {e}")
        return False

    TMP_DIR.mkdir(parents=True, exist_ok=True)
    try:
        garth.login(creds["email"], creds["password"])
        garth.save(str(TMP_DIR))
        log("Full garth.login() succeeded")
        return True
    except Exception as e:
        log(f"Full garth.login() failed: {e}")
        return False


def main() -> int:
    log("Starting token refresh check")

    # 1. Check current token expiry
    try:
        oauth2_json = secret_read("garmin-oauth2-token")
    except Exception as e:
        log(f"ERROR: Failed to download token from Secret Manager: {e}")
        return 1

    token_data = json.loads(oauth2_json)
    expires_at = token_data.get("expires_at", 0)
    now = time.time()
    hours_remaining = (expires_at - now) / 3600
    log(
        f"Current token expires at "
        f"{datetime.fromtimestamp(expires_at, tz=timezone.utc).isoformat()} "
        f"({hours_remaining:.1f}h remaining)"
    )

    if hours_remaining > REFRESH_THRESHOLD_HOURS:
        log(f"Token valid for {hours_remaining:.1f}h (>{REFRESH_THRESHOLD_HOURS}h). No action needed.")
        return 0

    # 2. Refresh
    log(f"Token expires in {hours_remaining:.1f}h -- refreshing...")

    success = refresh_via_exchange(oauth2_json)
    if not success:
        log("Falling back to full login...")
        success = refresh_via_login()

    if not success:
        log("ERROR: All refresh methods failed")
        return 1

    # 3. Validate
    new_oauth2 = (TMP_DIR / "oauth2_token.json").read_text()
    new_oauth1 = (TMP_DIR / "oauth1_token.json").read_text()
    new_data = json.loads(new_oauth2)
    new_exp = new_data.get("expires_at", 0)
    new_hours = (new_exp - time.time()) / 3600
    log(
        f"New token expires at "
        f"{datetime.fromtimestamp(new_exp, tz=timezone.utc).isoformat()} "
        f"({new_hours:.1f}h remaining)"
    )
    if new_hours < 1:
        log("WARNING: New token expires in < 1h -- this may not help")

    # 4. Upload to Secret Manager
    try:
        secret_write("garmin-oauth2-token", new_oauth2)
        secret_write("garmin-oauth1-token", new_oauth1)
        log("Tokens uploaded to Secret Manager")
    except Exception as e:
        log(f"ERROR: Failed to upload tokens: {e}")
        return 1

    log("Token refresh complete")
    return 0


if __name__ == "__main__":
    sys.exit(main())
