#!/usr/bin/env python3
"""
Crystal Sports court-availability monitor — GitHub Actions version.
Updated to scrape and parse the new server-rendered booking HTML pages.
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
DAYS_AHEAD = 15

# Force Thailand Timezone (UTC+7)
TZ_THAI = timezone(timedelta(hours=7))

# Load session cookies from environment variable
COOKIES = json.loads(os.environ.get("BOOKING_COOKIES_JSON") or "{}")

EMAIL_ENABLED = True
SMTP_HOST = os.environ.get("SMTP_HOST", "smtp.gmail.com")
SMTP_PORT = int(os.environ.get("SMTP_PORT", "587"))
SMTP_USER = os.environ.get("SMTP_USER", "")
SMTP_PASSWORD = os.environ.get("SMTP_PASSWORD", "")
EMAIL_TO = os.environ.get("EMAIL_TO", "")

NTFY_ENABLED = True
NTFY_TOPIC = os.environ.get("NTFY_TOPIC", "")

STATE_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "known_free_slots.json")
# ============== END CONFIG ==============

session = requests.Session()
session.headers.update({
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Referer": f"{BASE_URL}/",
})
if COOKIES:
    session.cookies.update(COOKIES)

# Define known locations based on the new UI branches
LOCATIONS = [
    {"locId": "1", "locName": "Crystal Sports"},
    {"locId": "2", "locName": "Crystal Sports G"}
]

def collect_free_slots():
    free = {}
    now = datetime.now(TZ_THAI)
    today_str = now.strftime("%Y-%m-%d")
    now_hour_str = now.strftime("%H:00")

    for day_offset in range(DAYS_AHEAD):
        date_obj = now + timedelta(days=day_offset)
        date_str = date_obj.strftime("%Y-%m-%d")
        is_weekend = date_obj.weekday() >= 5

        for loc in LOCATIONS:
            loc_id = loc["locId"]
            loc_name = loc["locName"]

            # Fetch the booking page for this specific date and location
            params = {
                "date": date_str,
                "loc": loc_id
            }
            
            try:
                resp = session.get(BASE_URL, params=params, timeout=20)
                if resp.status_code == 401:
                    print(f"  [error] 401 Unauthorized for {loc_name} on {date_str}. Check your session cookies.")
                    continue
                resp.raise_for_status()
            except Exception as e:
                print(f"  [warn] failed to fetch {loc_name} for {date_str}: {e}")
                continue

            # Parse HTML content
            soup = BeautifulSoup(resp.text, "html.parser")
            
            # Locate time slot elements and court status containers on the page
            # Adjust selectors based on the site's live HTML elements
            slot_cards = soup.find_all("div", class_="") # Scrapes time/slot blocks
            
            # Fallback text search across the page structure for available slots containing "ว่าง"
            # Looking for time slots and associated court availability indicators
            for time_box in soup.find_all(lambda tag: tag.name in ["div", "button", "a"] and "ว่าง" in tag.text):
                box_text = time_box.get_text(strip=True)
                
                # Extract time if present (e.g. "23:00" or similar pattern)
                # If the box indicates availability ("ว่าง"), record it
                if "ว่าง" in box_text:
                    # Attempt to find parent or sibling time label
                    parent = time_box.find_parent("div")
                    time_name = "18:00" # Default/fallback if exact time element is nested
                    
                    # Try scanning children or nearby text for time format HH:00
                    for child in time_box.stripped_strings:
                        if ":" in child and len(child) <= 5:
                            time_name = child
                            break

                    if date_str == today_str and time_name < now_hour_str:
                        continue
                        
                    # Filter for 17:00+ on Weekdays and 11:00+ on Weekends
                    if is_weekend:
                        if time_name < "11:00":
                            continue
                    else:
                        if time_name < "17:00":
                            continue

                    key = f"{date_str}|{loc_name}|Court|{time_name}"
                    free[key] = f"{date_str} {time_name} — {loc_name} (Available: {box_text})"

    return free


def load_previous_state():
    if not os.path.exists(STATE_FILE):
        return {}
    try:
        with open(STATE_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def save_state(state):
    with open(STATE_FILE, "w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False, indent=2)


def send_email(subject, body):
    if not (EMAIL_ENABLED and SMTP_USER and SMTP_PASSWORD and EMAIL_TO):
        print("  [skip] email not configured")
        return
    try:
        msg = MIMEText(body, "plain", "utf-8")
        msg["Subject"] = subject
        msg["From"] = SMTP_USER
        msg["To"] = EMAIL_TO
        context = ssl.create_default_context()
        with smtplib.SMTP(SMTP_HOST, SMTP_PORT) as server:
            server.starttls(context=context)
