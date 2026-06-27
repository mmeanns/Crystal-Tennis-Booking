#!/usr/bin/env python3
"""
One-off debug script: prints the RAW JSON the booking site returns,
for the first location/court/today's date, so we can see real field
names and values instead of guessing.

Temporarily point the workflow at this script instead of
monitor_booking.py, run it once, then switch back.
"""

import json
import os
from datetime import datetime

import requests

BASE_URL = "https://crystalsports-booking.kegroup.co.th/"
COOKIES = json.loads(os.environ.get("BOOKING_COOKIES_JSON") or "{}")

session = requests.Session()
session.headers.update({
    "User-Agent": "Mozilla/5.0 (booking-monitor debug script)",
    "X-Requested-With": "XMLHttpRequest",
})
if COOKIES:
    session.cookies.update(COOKIES)


def api_get(action):
    url = f"{BASE_URL}api_helper.php?action={action}"
    resp = session.get(url, timeout=20)
    resp.raise_for_status()
    try:
        return resp.json()
    except Exception:
        return json.loads(resp.text)


def api_post_available(date_str, stadium_id, loc_id):
    url = f"{BASE_URL}api_helper.php?action=getAvailableStadiums"
    payload = {"date": date_str, "stadiumId": stadium_id, "locId": loc_id}
    resp = session.post(url, json=payload, timeout=20)
    resp.raise_for_status()
    try:
        return resp.json()
    except Exception:
        return json.loads(resp.text)


print("=== Locations ===")
locations = api_get("getLocations")
print(json.dumps(locations, indent=2, ensure_ascii=False))

print("\n=== Stadiums (first 5) ===")
stadiums = api_get("getStadiums")
print(json.dumps(stadiums[:5], indent=2, ensure_ascii=False))

if locations and stadiums:
    loc_id = locations[0].get("locId")
    first_court = next((s for s in stadiums if str(s.get("locId")) == str(loc_id)), stadiums[0])
    stadium_id = first_court.get("stadiumId")
    today_str = datetime.now().strftime("%Y-%m-%d")

    print(f"\n=== getAvailableStadiums for locId={loc_id}, stadiumId={stadium_id}, date={today_str} ===")
    slots = api_post_available(today_str, stadium_id, loc_id)
    print(json.dumps(slots, indent=2, ensure_ascii=False))
else:
    print("\n[error] No locations or stadiums returned — can't run availability test.")
