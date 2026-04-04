#!/usr/bin/env python3
"""
One-time helper: store Garmin username + password in GCP Secret Manager.

Run this ONCE on the Mac when setting up automated re-authentication.
After this, the garmin-reauth Cloud Function handles everything.

Usage:
    ~/garmin_venv/bin/python3 ~/garmin_store_credentials.py
"""

import getpass
import json
from google.cloud import secretmanager

PROJECT_ID = "abm2020"
SECRET_ID  = "garmin-credentials"


def main():
    print("Garmin credential storage utility")
    print("These credentials will be stored encrypted in GCP Secret Manager.")
    print("They are used only by the garmin-reauth Cloud Function.\n")

    email    = input("Garmin account email: ").strip()
    password = getpass.getpass("Garmin account password: ")

    if not email or not password:
        print("Email and password are required.")
        return

    payload = json.dumps({"email": email, "password": password}).encode("utf-8")

    client = secretmanager.SecretManagerServiceClient()
    parent = f"projects/{PROJECT_ID}/secrets/{SECRET_ID}"

    try:
        version = client.add_secret_version(
            request={"parent": parent, "payload": {"data": payload}}
        )
        print(f"\nCredentials stored successfully as: {version.name}")
        print("\nYou can verify the secret exists (without revealing its value) with:")
        print(f"  gcloud secrets versions list {SECRET_ID} --project={PROJECT_ID}")
    except Exception as e:
        print(f"\nFailed to store credentials: {e}")
        raise


if __name__ == "__main__":
    main()
