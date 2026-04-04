#!/usr/bin/env python3
"""
One-time Garmin session saver — run once, never enter credentials again
"""
import getpass
import os
from garminconnect import Garmin
import garth

TOKEN_STORE = os.path.expanduser("~/.garth")

email    = input("Garmin email: ")
password = getpass.getpass("Garmin password: ")

print("\nLogging in and saving session...")
client = Garmin(email, password)
client.login()
client.garth.dump(TOKEN_STORE)

print(f"✅ Session saved to {TOKEN_STORE}")
print("The daily script will now run without asking for credentials.")
