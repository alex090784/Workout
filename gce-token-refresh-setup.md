# Garmin Token Refresh: GCE VM Setup Guide

Replace the local Mac launchd job with a free-tier GCE e2-micro VM that refreshes
Garmin OAuth tokens every 4 hours. The VM uses its own external IP (not the shared
Cloud Functions NAT pool), which should bypass Garmin's rate-limiting of GCP egress.

**Risk:** If Garmin blocks the entire GCP ASN (AS396982), this won't work either.
Step 3 includes a quick test before doing the full setup.

**Cost:** e2-micro is included in the GCP Always Free tier (720 hrs/mo in
us-central1, us-west1, or us-east1). A static external IP is free while attached
to a running VM. Total cost: $0/mo if you stay within free tier limits.

---

## Step 1: Create a dedicated service account

Don't use the default Compute Engine SA. Create one with only the permissions needed.

```bash
# Create the service account
gcloud iam service-accounts create garmin-refresh-vm \
  --display-name="Garmin token refresh VM" \
  --project=abm2020

# Grant secretmanager.secretAccessor on the specific secrets it needs to READ
for SECRET in garmin-oauth2-token garmin-oauth1-token garmin-credentials; do
  gcloud secrets add-iam-policy-binding $SECRET \
    --member="serviceAccount:garmin-refresh-vm@abm2020.iam.gserviceaccount.com" \
    --role="roles/secretmanager.secretAccessor" \
    --project=abm2020
done

# Grant secretmanager.secretVersionAdder on the secrets it needs to WRITE
for SECRET in garmin-oauth2-token garmin-oauth1-token; do
  gcloud secrets add-iam-policy-binding $SECRET \
    --member="serviceAccount:garmin-refresh-vm@abm2020.iam.gserviceaccount.com" \
    --role="roles/secretmanager.versions.add" \
    --project=abm2020 2>/dev/null || \
  gcloud secrets add-iam-policy-binding $SECRET \
    --member="serviceAccount:garmin-refresh-vm@abm2020.iam.gserviceaccount.com" \
    --role="roles/secretmanager.secretVersionManager" \
    --project=abm2020
done
```

Note: `roles/secretmanager.secretAccessor` allows reading versions.
`roles/secretmanager.secretVersionManager` allows adding new versions. If you want
tighter control, you can create a custom role with just `secretmanager.versions.add`,
but the built-in role is fine for this use case.

---

## Step 2: Create the e2-micro VM

```bash
gcloud compute instances create garmin-refresh \
  --project=abm2020 \
  --zone=us-central1-a \
  --machine-type=e2-micro \
  --image-family=debian-12 \
  --image-project=debian-cloud \
  --boot-disk-size=10GB \
  --boot-disk-type=pd-standard \
  --service-account=garmin-refresh-vm@abm2020.iam.gserviceaccount.com \
  --scopes=cloud-platform \
  --tags=garmin-refresh \
  --metadata=startup-script='#!/bin/bash
echo "VM started at $(date -u)" >> /var/log/garmin-refresh-startup.log'
```

Free tier notes:
- e2-micro in us-central1 = free tier eligible (720 hrs/mo = always on)
- 10GB pd-standard boot disk = within 30GB free tier
- Ephemeral external IP = free (static IP also free while VM is running)

Reserve a static IP so Garmin sees a consistent address:

```bash
gcloud compute addresses create garmin-refresh-ip \
  --project=abm2020 \
  --region=us-central1

# Get the IP
gcloud compute addresses describe garmin-refresh-ip \
  --project=abm2020 \
  --region=us-central1 \
  --format="get(address)"

# Assign it to the VM (requires a stop/start or create with --address)
# If the VM is already running:
gcloud compute instances delete-access-config garmin-refresh \
  --zone=us-central1-a --project=abm2020 --access-config-name="external-nat"

gcloud compute instances add-access-config garmin-refresh \
  --zone=us-central1-a --project=abm2020 \
  --address=$(gcloud compute addresses describe garmin-refresh-ip \
    --project=abm2020 --region=us-central1 --format="get(address)")
```

---

## Step 3: Quick IP test BEFORE full setup

SSH into the VM and test whether Garmin accepts OAuth exchange from this IP.
Do this BEFORE installing the full stack.

```bash
gcloud compute ssh garmin-refresh --zone=us-central1-a --project=abm2020
```

On the VM:

```bash
# Check the external IP
curl -s ifconfig.me && echo

# Install minimal Python + pip
sudo apt-get update && sudo apt-get install -y python3 python3-pip python3-venv

# Create a venv and install just garth
python3 -m venv /opt/garmin-refresh/venv
source /opt/garmin-refresh/venv/bin/activate
pip install garth

# Quick test: can we reach Garmin's OAuth endpoint without a 429?
python3 -c "
import requests
r = requests.get('https://sso.garmin.com/sso/signin', timeout=10)
print(f'Status: {r.status_code}')
print(f'Rate limited: {r.status_code == 429}')
"
```

**If status is 429**: Garmin is blocking the entire GCP ASN. Stop here -- delete the
VM and fall back to the Mac launchd approach (or a non-GCP VPS).

**If status is 200 (or 302/303)**: The VM's IP is not rate-limited. Proceed.

For a more thorough test, copy the current tokens from Secret Manager and attempt
an actual exchange:

```bash
# Install the Secret Manager SDK
pip install google-cloud-secret-manager

python3 -c "
from google.cloud import secretmanager
import garth, json, tempfile
from pathlib import Path

client = secretmanager.SecretManagerServiceClient()

def read_secret(name):
    resp = client.access_secret_version(
        request={'name': f'projects/abm2020/secrets/{name}/versions/latest'})
    return resp.payload.data.decode('utf-8')

d = Path(tempfile.mkdtemp())
(d / 'oauth2_token.json').write_text(read_secret('garmin-oauth2-token'))
(d / 'oauth1_token.json').write_text(read_secret('garmin-oauth1-token'))

garth.resume(str(d))

# Check current token
data = json.loads((d / 'oauth2_token.json').read_text())
import time
hrs = (data.get('expires_at', 0) - time.time()) / 3600
print(f'Current token: {hrs:.1f}h remaining')

# Attempt refresh
try:
    garth.client.refresh_oauth2()
    garth.save(str(d))
    new = json.loads((d / 'oauth2_token.json').read_text())
    new_hrs = (new.get('expires_at', 0) - time.time()) / 3600
    print(f'EXCHANGE SUCCEEDED -- new token: {new_hrs:.1f}h remaining')
except Exception as e:
    print(f'EXCHANGE FAILED: {e}')
"
```

**If "EXCHANGE SUCCEEDED"**: You're clear. Proceed to full setup.

Exit SSH for now: `exit`

---

## Step 4: Deploy the refresh script

```bash
# Copy the script to the VM
gcloud compute scp \
  /Users/alexct/projects/garmin/scripts/garmin_refresh_tokens_gce.py \
  garmin-refresh:/tmp/garmin_refresh_tokens.py \
  --zone=us-central1-a --project=abm2020

# SSH back in
gcloud compute ssh garmin-refresh --zone=us-central1-a --project=abm2020
```

On the VM:

```bash
# Set up the app directory (if not done in Step 3)
sudo mkdir -p /opt/garmin-refresh
sudo mv /tmp/garmin_refresh_tokens.py /opt/garmin-refresh/refresh.py
sudo chown -R root:root /opt/garmin-refresh

# Create venv if not already done
sudo python3 -m venv /opt/garmin-refresh/venv
sudo /opt/garmin-refresh/venv/bin/pip install garth google-cloud-secret-manager

# Test the script manually
sudo /opt/garmin-refresh/venv/bin/python3 /opt/garmin-refresh/refresh.py
```

You should see output like:
```
[garmin-refresh] 2026-04-13T...Z Starting token refresh check
[garmin-refresh] 2026-04-13T...Z Current token expires at ... (X.Xh remaining)
[garmin-refresh] 2026-04-13T...Z Token valid for X.Xh (>6h). No action needed.
```

---

## Step 5: Create systemd timer (runs every 4 hours)

Still on the VM:

```bash
# Create the service unit
sudo tee /etc/systemd/system/garmin-refresh.service << 'EOF'
[Unit]
Description=Refresh Garmin OAuth tokens via Secret Manager
After=network-online.target
Wants=network-online.target

[Service]
Type=oneshot
ExecStart=/opt/garmin-refresh/venv/bin/python3 /opt/garmin-refresh/refresh.py
# No User= directive needed -- runs as root, authenticates via metadata server
# The script doesn't write to disk (except /tmp), so root is fine.
TimeoutStartSec=120
StandardOutput=journal
StandardError=journal
SyslogIdentifier=garmin-refresh

[Install]
WantedBy=multi-user.target
EOF

# Create the timer unit
sudo tee /etc/systemd/system/garmin-refresh.timer << 'EOF'
[Unit]
Description=Run Garmin token refresh every 4 hours

[Timer]
OnCalendar=*-*-* 00/4:00:00
# Fires at 00:00, 04:00, 08:00, 12:00, 16:00, 20:00 UTC
Persistent=true
# If the VM was down during a scheduled time, run on next boot
RandomizedDelaySec=60

[Install]
WantedBy=timers.target
EOF

# Enable and start
sudo systemctl daemon-reload
sudo systemctl enable garmin-refresh.timer
sudo systemctl start garmin-refresh.timer

# Verify
systemctl list-timers garmin-refresh.timer
```

Test the service manually:

```bash
sudo systemctl start garmin-refresh.service
journalctl -u garmin-refresh.service --no-pager -n 20
```

---

## Step 6: Harden the VM

This VM is internet-facing. Lock it down.

```bash
# On the VM:

# Update packages
sudo apt-get update && sudo apt-get upgrade -y

# Install unattended-upgrades for automatic security patches
sudo apt-get install -y unattended-upgrades
sudo dpkg-reconfigure -plow unattended-upgrades  # select Yes

# Install fail2ban
sudo apt-get install -y fail2ban
sudo systemctl enable fail2ban
sudo systemctl start fail2ban
```

Restrict firewall at the GCP level (more reliable than host-level UFW for GCE):

```bash
# From your local machine (not the VM):

# Delete the default allow-ssh rule if you want to restrict SSH to your IP only
# First, check what firewall rules exist:
gcloud compute firewall-rules list --project=abm2020

# Create a restrictive rule: SSH only from your IP (optional but recommended)
# Replace YOUR_IP with your actual IP (run: curl -s ifconfig.me)
gcloud compute firewall-rules create allow-ssh-garmin-refresh \
  --project=abm2020 \
  --direction=INGRESS \
  --action=ALLOW \
  --rules=tcp:22 \
  --source-ranges=YOUR_IP/32 \
  --target-tags=garmin-refresh \
  --priority=1000

# The VM doesn't need ANY inbound ports except SSH for management.
# No HTTP/HTTPS listeners. It only makes outbound connections.
```

---

## Step 7: Verify the full loop

1. **Check the timer is scheduled:**
   ```bash
   # On the VM
   systemctl list-timers garmin-refresh.timer
   ```

2. **Force a refresh cycle** (even if the token isn't expired):
   Temporarily edit the script's threshold or just wait for the token to drop below 6h.
   Or, on the VM:
   ```bash
   # Run with a forced high threshold (quick one-liner test)
   sudo /opt/garmin-refresh/venv/bin/python3 -c "
   import sys; sys.path.insert(0, '/opt/garmin-refresh')
   import refresh
   refresh.REFRESH_THRESHOLD_HOURS = 999  # force refresh
   sys.exit(refresh.main())
   "
   ```

3. **Verify Secret Manager was updated:**
   ```bash
   # From your local Mac
   gcloud secrets versions list garmin-oauth2-token --project=abm2020 --limit=3
   ```
   You should see a new version with a recent createTime.

4. **Wait for the next daily function run** (05:00 UTC) and confirm the coaching
   email arrives. Check function logs:
   ```bash
   gcloud functions logs read garmin-daily-feedback \
     --limit=20 --region=europe-west1 --project=abm2020
   ```

---

## Step 8: Clean up the old infrastructure

Once the GCE VM has been running successfully for a few days:

### 8a. Disable the Mac launchd job

```bash
# On your Mac
launchctl unload ~/Library/LaunchAgents/com.garmin.token-refresh.plist
# Optionally remove:
# rm ~/Library/LaunchAgents/com.garmin.token-refresh.plist
```

### 8b. Pause (don't delete) the Cloud Scheduler reauth job

```bash
gcloud scheduler jobs pause garmin-reauth-20d \
  --location=europe-west1 --project=abm2020
```

### 8c. Optionally delete the garmin-reauth Cloud Function

Only after you're confident the VM solution is stable (give it a week):

```bash
gcloud functions delete garmin-reauth \
  --region=europe-west1 --project=abm2020

# Then delete the scheduler job too
gcloud scheduler jobs delete garmin-reauth-20d \
  --location=europe-west1 --project=abm2020
```

---

## Ongoing maintenance

- **OS updates:** `unattended-upgrades` handles security patches. For major upgrades,
  SSH in quarterly and run `sudo apt-get update && sudo apt-get dist-upgrade`.

- **Python package updates:** Periodically update garth:
  ```bash
  sudo /opt/garmin-refresh/venv/bin/pip install --upgrade garth google-cloud-secret-manager
  ```

- **Monitoring:** Check `journalctl -u garmin-refresh.service` periodically, or set
  up a Cloud Monitoring uptime check on the VM.

- **If the VM gets rate-limited too:** You'll see `429 Too Many Requests` in the
  journal logs. Options:
  1. Release and re-reserve a different static IP
  2. Move to a non-GCP VPS (Hetzner/DigitalOcean, ~$4/mo)
  3. Fall back to Mac launchd (just re-load the plist)

- **Cost check:** Verify monthly billing stays at $0 for the VM. The only potential
  charge is egress (but token refresh is a few KB -- negligible).

---

## Architecture summary

```
Before (broken):
  Cloud Scheduler --> garmin-reauth CF --> Garmin SSO --> 429 (GCP shared NAT IP)

Current (fragile):
  Mac launchd --> garmin_refresh_tokens.py --> Garmin SSO --> OK (residential IP)
  Problem: depends on Mac being awake, on the home network, not travelling

After (this guide):
  GCE VM systemd timer --> refresh.py --> Garmin SSO --> OK? (dedicated GCE IP)
  Benefits: always on, no laptop dependency, free tier, same GCP project
```
