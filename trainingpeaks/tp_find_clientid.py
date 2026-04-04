#!/usr/bin/env python3
"""
Scrape the TrainingPeaks web app to find the real OAuth client_id
"""
import requests
import re

session = requests.Session()
session.headers.update({
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                  "AppleWebKit/537.36 (KHTML, like Gecko) "
                  "Chrome/120.0.0.0 Safari/537.36"
})

print("[1] Fetching app.trainingpeaks.com...")
r = session.get("https://app.trainingpeaks.com/")
html = r.text

# Find all JS bundle URLs
js_urls = re.findall(r'src=["\']([^"\']*\.js[^"\']*)["\']', html)
# Also check for inline config
print(f"    Found {len(js_urls)} JS files")

# Search inline HTML first
patterns = [
    r'client.?[Ii]d["\s:=]+["\']([a-zA-Z0-9_\-]{10,})["\']',
    r'clientId["\s:=]+["\']([a-zA-Z0-9_\-]{10,})["\']',
    r'CLIENT_ID["\s:=]+["\']([a-zA-Z0-9_\-]{10,})["\']',
    r'audience["\s:=]+["\']([^"\']+trainingpeaks[^"\']+)["\']',
    r'AUTH[_0-9]*_CLIENT["\s:=]+["\']([a-zA-Z0-9_\-]{10,})["\']',
]
print("\n[2] Searching inline HTML for client_id...")
for pat in patterns:
    matches = re.findall(pat, html)
    if matches:
        print(f"    Pattern '{pat[:40]}...' → {matches[:3]}")

# Fetch and search JS bundles (largest ones likely contain auth config)
print("\n[3] Searching JS bundles...")
js_full_urls = []
for url in js_urls:
    if url.startswith("http"):
        js_full_urls.append(url)
    elif url.startswith("/"):
        js_full_urls.append("https://app.trainingpeaks.com" + url)

# Sort by likely importance (main/chunk bundles)
priority = [u for u in js_full_urls if any(x in u for x in ["main", "app", "auth", "vendor", "chunk"])]
rest = [u for u in js_full_urls if u not in priority]
js_full_urls = (priority + rest)[:15]  # Check top 15

found = {}
for url in js_full_urls:
    try:
        jr = session.get(url, timeout=15)
        js = jr.text
        for pat in patterns:
            matches = re.findall(pat, js)
            if matches:
                for m in matches:
                    if len(m) > 8 and m not in ("undefined", "null", "function"):
                        found[m] = url.split("/")[-1][:40]
    except Exception as e:
        pass

if found:
    print(f"\n    Found potential client IDs:")
    for val, src in found.items():
        print(f"      {val}  (from {src})")
else:
    print("    Nothing found in JS bundles")

# Also try fetching Auth0 discovery document
print("\n[4] Fetching Auth0 OIDC discovery...")
disc = session.get("https://oauth.trainingpeaks.com/.well-known/openid-configuration")
print(f"    Status: {disc.status_code}")
if disc.status_code == 200:
    import json
    d = disc.json()
    print(f"    Issuer: {d.get('issuer')}")
    print(f"    Token endpoint: {d.get('token_endpoint')}")
    print(f"    Supported grant types: {d.get('grant_types_supported')}")
    print(f"    Supported response types: {d.get('response_types_supported')}")
