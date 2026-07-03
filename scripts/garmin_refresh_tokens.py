#!/usr/bin/env python3
"""
Refresh Garmin OAuth tokens locally and push to GCP Secret Manager.

This script runs on the local Mac (via launchd) to avoid the Garmin rate-limit
that blocks GCP egress IPs. It:
  1. Checks current token expiry from Secret Manager
  2. If within threshold: refreshes via OAuth1->OAuth2 exchange (garth.client.refresh_oauth2)
     which produces a completely new access token with a fresh ~28h window
  3. Falls back to full garth.login() if the exchange fails
  4. Uploads the refreshed tokens back to Secret Manager
  5. Updates local ~/.garth/ as well

The OAuth1->OAuth2 exchange is preferred because:
  - It works reliably from the local IP (not rate-limited like the SSO login endpoint)
  - It produces a genuinely new token with a fresh ~28h expiry
  - It doesn't require email/password credentials

Designed to run unattended via launchd. Logs to stdout (captured by launchd).
Exit codes: 0 = success, 1 = error.
"""

import json
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

# garth must be importable from the venv that calls this script
import garth

GARTH_DIR = Path.home() / ".garth"
PROJECT_ID = "abm2020"
LOG_PREFIX = "[garmin-refresh]"
REFRESH_THRESHOLD_HOURS = 6  # refresh when token has < 6h remaining


def log(msg: str) -> None:
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    print(f"{LOG_PREFIX} {ts} {msg}", flush=True)


def gcloud_secret_access(secret_id: str) -> str:
    """Read latest version of a secret from Secret Manager via gcloud CLI."""
    result = subprocess.run(
        [
            "gcloud", "secrets", "versions", "access", "latest",
            f"--secret={secret_id}", f"--project={PROJECT_ID}",
        ],
        capture_output=True, text=True, timeout=30,
    )
    if result.returncode != 0:
        raise RuntimeError(f"Failed to read secret {secret_id}: {result.stderr.strip()}")
    return result.stdout


def gcloud_secret_add_version(secret_id: str, value: str) -> None:
    """Add a new version to a Secret Manager secret via gcloud CLI."""
    result = subprocess.run(
        [
            "gcloud", "secrets", "versions", "add", secret_id,
            f"--project={PROJECT_ID}", "--data-file=-",
        ],
        input=value, capture_output=True, text=True, timeout=30,
    )
    if result.returncode != 0:
        raise RuntimeError(f"Failed to update secret {secret_id}: {result.stderr.strip()}")


def refresh_via_exchange(tmp_dir: Path, oauth2_json: str) -> bool:
    """Refresh by exchanging OAuth1 token for new OAuth2 token. Returns True on success."""
    try:
        oauth1_json = gcloud_secret_access("garmin-oauth1-token")
    except Exception as e:
        log(f"Failed to download OAuth1 token: {e}")
        return False

    (tmp_dir / "oauth2_token.json").write_text(oauth2_json)
    (tmp_dir / "oauth1_token.json").write_text(oauth1_json)

    try:
        garth.resume(str(tmp_dir))
        garth.client.refresh_oauth2()
        garth.save(str(tmp_dir))
        log("OAuth1->OAuth2 exchange succeeded")
        return True
    except Exception as e:
        log(f"OAuth1->OAuth2 exchange failed: {e}")
        return False


def refresh_via_login(tmp_dir: Path) -> bool:
    """Refresh by full SSO login with email/password. Returns True on success."""
    try:
        creds_json = gcloud_secret_access("garmin-credentials")
        creds = json.loads(creds_json)
    except Exception as e:
        log(f"Failed to read credentials: {e}")
        return False

    try:
        garth.login(creds["email"], creds["password"])
        garth.save(str(tmp_dir))
        log("Full garth.login() succeeded")
        return True
    except Exception as e:
        log(f"Full garth.login() failed: {e}")
        return False


def main() -> int:
    log("Starting token refresh check")

    # 1. Download current OAuth2 token to check expiry
    try:
        oauth2_json = gcloud_secret_access("garmin-oauth2-token")
    except Exception as e:
        log(f"ERROR: Failed to download token from Secret Manager: {e}")
        return 1

    token_data = json.loads(oauth2_json)
    expires_at = token_data.get("expires_at", 0)
    now = time.time()
    hours_remaining = (expires_at - now) / 3600
    log(f"Current token expires at {datetime.fromtimestamp(expires_at, tz=timezone.utc).isoformat()} "
        f"({hours_remaining:.1f} hours from now)")

    # Skip if token is still well within validity
    if hours_remaining > REFRESH_THRESHOLD_HOURS:
        log(f"Token valid for {hours_remaining:.1f}h (>{REFRESH_THRESHOLD_HOURS}h threshold). No action needed.")
        return 0

    # 2. Attempt refresh
    log(f"Token expires in {hours_remaining:.1f}h -- refreshing...")
    tmp_dir = Path("/tmp/.garth_refresh")
    tmp_dir.mkdir(parents=True, exist_ok=True)

    # Primary: OAuth1->OAuth2 exchange (lightweight, no credentials needed)
    success = refresh_via_exchange(tmp_dir, oauth2_json)

    # Fallback: full SSO login (heavier, may be rate-limited)
    if not success:
        log("Falling back to full login...")
        success = refresh_via_login(tmp_dir)

    if not success:
        log("ERROR: All refresh methods failed")
        return 1

    # 3. Read and validate refreshed tokens
    new_oauth2 = (tmp_dir / "oauth2_token.json").read_text()
    new_oauth1 = (tmp_dir / "oauth1_token.json").read_text()

    new_data = json.loads(new_oauth2)
    new_exp = new_data.get("expires_at", 0)
    new_hours = (new_exp - time.time()) / 3600
    log(f"New token expires at {datetime.fromtimestamp(new_exp, tz=timezone.utc).isoformat()} "
        f"({new_hours:.1f}h from now)")

    if new_hours < 1:
        log("WARNING: New token expires in less than 1 hour. This may not help.")

    # 4. Upload to Secret Manager
    try:
        gcloud_secret_add_version("garmin-oauth2-token", new_oauth2)
        gcloud_secret_add_version("garmin-oauth1-token", new_oauth1)
        log("Tokens uploaded to Secret Manager")
    except Exception as e:
        log(f"ERROR: Failed to upload tokens: {e}")
        return 1

    # 5. Update local ~/.garth/
    GARTH_DIR.mkdir(parents=True, exist_ok=True)
    (GARTH_DIR / "oauth2_token.json").write_text(new_oauth2)
    (GARTH_DIR / "oauth1_token.json").write_text(new_oauth1)
    log("Local ~/.garth/ tokens updated")

    log("Token refresh complete")
    return 0


if __name__ == "__main__":
    sys.exit(main())
