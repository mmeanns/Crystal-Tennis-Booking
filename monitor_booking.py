#!/usr/bin/env python3
"""
Crystal Sports court-availability monitor — Debugging version.
Inspects raw HTML responses to diagnose why slots aren't being matched.
"""

import json
import os
import smtplib
import ssl
from datetime import datetime, timedelta, timezone
from email.mime.text import MIMEText

import requests
from bs4 import BeautifulSoup

# ============== CONFIG ==============
BASE_URL = "https://crystalsports-booking.kegroup.co.th/booking"
DAYS_AHEAD = 3  # Check just 3 days for debugging output clarity

TZ_THAI = timezone(timedelta(hours=7))
COOKIES = json.loads(os.environ.get("BOOKING_COOKIES_JSON") or "{}")

STATE_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "known_free_slots.json")

LOCATIONS = [
    {"locId": "LOC001", "locName": "Crystal Sports"},
    {"locId": "LOC002", "locName": "Crystal Sports G"}
]

def collect_free_slots():
    free = {}
    now = datetime.now(TZ_THAI)
    today_str = now.strftime("%Y-%m-%d")

    session = requests.Session()
    session.headers.update({
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Referer": f"{BASE_URL}/",
    })
    if COOKIES:
        session.cookies.update(COOKIES)

    for day_offset in range(DAYS_AHEAD):
        date_obj = now + timedelta(days=day_offset)
        date_str = date_obj.strftime("%Y-%m-%d")

        for loc in LOCATIONS:
            loc_id = loc["locId"]
            loc_name = loc["locName"]

            params = {
                "date": date_str,
                "loc": loc_id,
                "time": "18",
                "sel": ""
            }
            
            try:
                resp = session.get(BASE_URL, params=params, timeout=20)
                print(f"[DEBUG] Fetched {loc_name} for {date_str} -> Status: {resp.status_code}, Length: {len(resp.text)}")
                
                if "login" in resp.url.lower() or "เข้าสู่ระบบ" in resp.text:
                    print(f"  [error] Session expired or unauthenticated! Redirected to login for {loc_name} on {date_str}.")
                    continue
                
                resp.raise_for_status()
            except Exception as e:
                print(f"  [warn] failed to fetch {loc_name} for {date_str}: {e}")
                continue

            soup = BeautifulSoup(resp.text, "html.parser")
            
            # Print a snippet of page text for the first request to verify contents
            if day_offset == 0 and loc_id == "LOC001":
                page_text = soup.get_text(separator=" ", strip=True)
                print(f"[DEBUG] Sample page text preview (first 300 chars): {page_text[:300]}")

            for element in soup.find_all(True):
                text = element.get_text(strip=True)
                if "ว่าง" in text:
                    print(f"[DEBUG] Found 'ว่าง' in element: {text[:100]}")
                    # Basic extraction logic
                    time_name = "18:00"
                    for token in text.replace("\n", " ").split():
                        if ":" in token and len(token) >= 5 and token[:2].isdigit():
                            time_name = token[:5]
                            break

                    key = f"{date_str}|{loc_name}|Court|{time_name}"
                    free[key] = f"{date_str} {time_name} — {loc_name} ({text})"

    print(f"  [info] Scraped {len(free)} available slots across the debug window.")
    return free

def main():
    print(f"[{datetime.now(TZ_THAI)}] Running debug check...")
    try:
        collect_free_slots()
    except Exception as e:
        print(f"[error] {e}")

if __name__ == "__main__":
    main()
