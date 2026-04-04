#!/usr/bin/env python3
"""
TrainingPeaks auth - tries multiple approaches
"""
import requests
import json
import getpass

email    = input("TrainingPeaks username (e.g. Alex0907): ")
password = getpass.getpass("TrainingPeaks password: ")

session = requests.Session()
session.headers.update({
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                  "AppleWebKit/537.36 (KHTML, like Gecko) "
                  "Chrome/120.0.0.0 Safari/537.36",
    "Accept": "application/json, text/plain, */*",
    "Origin": "https://app.trainingpeaks.com",
    "Referer": "https://app.trainingpeaks.com/"
})

# ── Attempt 1: OAuth password grant with v2 endpoint ────────────────────────
print("\n[1] Trying OAuth password grant...")
auth_endpoints = [
    "https://oauth.trainingpeaks.com/OAuth/token",
    "https://api.trainingpeaks.com/OAuth/token",
]
client_ids = ["trainingpeaks", "TPWebApp", "tpapi"]

for url in auth_endpoints:
    for cid in client_ids:
        payload = {
            "grant_type": "password",
            "client_id":  cid,
            "username":   email,
            "password":   password,
            "scope":      "trainingpeaks.v1 openid",
        }
        r = session.post(url, data=payload)
        print(f"   {url} | client_id={cid} → {r.status_code}")
        if r.status_code == 200:
            print(f"   SUCCESS: {r.text[:200]}")
            token = r.json().get("access_token")
            athlete_id = r.json().get("UserId") or r.json().get("userId")
            print(f"   Token: {token[:40]}...")
            print(f"   AthleteID: {athlete_id}")
            exit(0)

# ── Attempt 2: Web app login (cookie-based) ──────────────────────────────────
print("\n[2] Trying web app cookie login...")
login_url = "https://api.trainingpeaks.com/v1/auth/login"
payload = {"Username": email, "Password": password}
r = session.post(login_url, json=payload)
print(f"   {login_url} → {r.status_code}")
if r.status_code == 200:
    print(f"   Response: {r.text[:300]}")
    print(f"   Cookies: {dict(session.cookies)}")

# ── Attempt 3: Alternate login endpoint ─────────────────────────────────────
print("\n[3] Trying alternate endpoints...")
endpoints = [
    ("POST", "https://api.trainingpeaks.com/v2/auth/token",
     {"username": email, "password": password, "grant_type": "password"}),
    ("POST", "https://app.trainingpeaks.com/api/v1/auth",
     {"Username": email, "Password": password}),
    ("POST", "https://www.trainingpeaks.com/api/v1/login",
     {"Username": email, "Password": password}),
    ("POST", "https://api.trainingpeaks.com/v1/auth/login",
     {"Username": email, "Password": password}),
]
for method, url, data in endpoints:
    try:
        r = session.post(url, json=data, timeout=10)
        print(f"   {url} → {r.status_code}")
        if r.status_code in (200, 201):
            print(f"   SUCCESS: {r.text[:300]}")
    except Exception as e:
        print(f"   {url} → Error: {e}")

# ── Attempt 4: Check what the login page reveals ─────────────────────────────
print("\n[4] Checking login page for clues...")
r = session.get("https://app.trainingpeaks.com/")
print(f"   Homepage status: {r.status_code}")
# Look for any API config in the page
if "clientId" in r.text or "client_id" in r.text:
    import re
    ids = re.findall(r'client.?[Ii]d["\s:]+(["\']?)([a-zA-Z0-9_-]+)\1', r.text)
    print(f"   Found client IDs in page: {ids[:5]}")
