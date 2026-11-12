#!/usr/bin/env python3
"""
Crystal Sports court-availability monitor — Cookie & Redirect Diagnostic Version.
"""

import json
import os
import re
import smtplib
import ssl
from datetime import datetime, timedelta, timezone
from email.mime.text import MIMEText

import requests
from bs4 import BeautifulSoup

# ============== CONFIG ==============
BASE_URL = "https://crystalsports-booking.kegroup.co.th/booking"
DAYS_AHEAD = 2  # Just check 2 days for quick testing

TZ_THAI = timezone(timedelta(hours=7))
RAW_COOKIES = json.loads(os.environ.get("BOOKING_COOKIES_JSON") or "{}")

EMAIL_ENABLED = True
SMTP_HOST = os.environ.get("SMTP_HOST", "smtp.gmail.com")
SMTP_PORT = int(os.environ.get("SMTP_PORT", "587"))
SMTP_USER = os.environ.get("SMTP_USER", "")
SMTP_PASSWORD = os.environ.get("SMTP_PASSWORD", "")
EMAIL_TO = os.environ.get("EMAIL_TO", "")

NTFY_ENABLED = True
NTFY_TOPIC = os.environ.get("NTFY_TOPIC", "")

STATE_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "known_free_slots.json")

LOCATIONS = [
    {"locId": "LOC001", "locName": "Crystal Sports"},
]
# ============== END CONFIG ==============

session = requests.Session()
session.headers.update({
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.5",
    "Referer": f"{BASE_URL}/",
})

# Load cookies directly into session
if RAW_COOKIES:
    session.cookies.update(RAW_COOKIES)


def collect_free_slots():
    free = {}
    now = datetime.now(TZ_THAI)
    today_str = now.strftime("%Y-%m-%d")

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
                "sel": "",
            }

            try:
                # Disable automatic redirects to inspect raw server response
                resp = session.get(BASE_URL, params=params, timeout=20, allow_redirects=False)
                print(f"[DIAG] {loc_name} on {date_str} -> Status Code: {resp.status_code}")
                
                if resp.status_code in (301, 302, 303, 307, 308):
                    redirect_target = resp.headers.get("Location", "Unknown")
                    print(f"  [error] Server rejected cookies and redirected to: {redirect_target}")
                    continue
                
                resp.raise_for_status()
            except Exception as e:
                print(f"  [warn] failed to fetch {loc_name} for {date_str}: {e}")
                continue

            soup = BeautifulSoup(resp.text, "html.parser")
            for element in soup.find_all(["button", "a", "div", "label", "span"]):
                text = element.get_text(" ", strip=True)
                if "ว่าง" not in text or len(text) > 40:
                    continue

                match = re.search(r"\b(\d{2}:\d{2})\b", text)
                if not match:
                    continue

                time_name = match.group(1)
                avail_match = re.search(r"(ว่าง\s*\d*)", text)
                status_label = avail_match.group(1).strip() if avail_match else "ว่าง"

                key = f"{date_str}|{loc_name}|{status_label}|{time_name}"
                free[key] = f"{date_str} {time_name} — {loc_name} ({status_label})"

    print(f"  [info] Scraped {len(free)} slots.")
    return free


def main():
    print(f"[{datetime.now(TZ_THAI)}] Running diagnostic check...")
    collect_free_slots()


if __name__ == "__main__":
    main()
