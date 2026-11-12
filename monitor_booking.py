#!/usr/bin/env python3
"""
Crystal Sports court-availability monitor — Playwright Headless version.
"""

import json
import os
import re
import smtplib
import ssl
from datetime import datetime, timedelta, timezone
from email.mime.text import MIMEText
from playwright.sync_api import sync_playwright
from bs4 import BeautifulSoup

BASE_URL = "https://crystalsports-booking.kegroup.co.th/booking"
DAYS_AHEAD = 15
TZ_THAI = timezone(timedelta(hours=7))

EMAIL_ENABLED = True
SMTP_HOST = os.environ.get("SMTP_HOST", "smtp.gmail.com")

# Safely parse SMTP_PORT, falling back to 587 if empty or missing
_smtp_port_raw = os.environ.get("SMTP_PORT")
SMTP_PORT = int(_smtp_port_raw) if _smtp_port_raw and _smtp_port_raw.strip().isdigit() else 587

SMTP_USER = os.environ.get("SMTP_USER", "")
SMTP_PASSWORD = os.environ.get("SMTP_PASSWORD", "")
EMAIL_TO = os.environ.get("EMAIL_TO", "")

NTFY_ENABLED = True
NTFY_TOPIC = os.environ.get("NTFY_TOPIC", "")

STATE_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "known_free_slots.json")

LOCATIONS = [
    {"locId": "LOC001", "locName": "Crystal Sports"},
    {"locId": "LOC002", "locName": "Crystal Sports G"},
]

def collect_free_slots():
    free = {}
    now = datetime.now(TZ_THAI)
    today_str = now.strftime("%Y-%m-%d")
    now_hour_str = now.strftime("%H:00")

    auth_state_str = os.environ.get("PLAYWRIGHT_AUTH_STATE")
    storage_state = json.loads(auth_state_str) if auth_state_str else None

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(storage_state=storage_state)
        page = context.new_page()

        for day_offset in range(DAYS_AHEAD):
            date_obj = now + timedelta(days=day_offset)
            date_str = date_obj.strftime("%Y-%m-%d")
            is_weekend = date_obj.weekday() >= 5

            for loc in LOCATIONS:
                loc_id = loc["locId"]
                loc_name = loc["locName"]

                target_url = f"{BASE_URL}?date={date_str}&loc={loc_id}&time=18&sel="

                try:
                    page.goto(target_url, timeout=30000)
                    page.wait_for_load_state("domcontentloaded", timeout=15000)

                    if "login" in page.url.lower():
                        print(f"  [error] Session expired. Redirected to login for {loc_name} on {date_str}.")
                        continue

                    content = page.content()
                    soup = BeautifulSoup(content, "html.parser")

                    for element in soup.find_all(["button", "a", "div", "label", "span"]):
                        text = element.get_text(" ", strip=True)
                        if "ว่าง" not in text or len(text) > 40:
                            continue

                        match = re.search(r"\b(\d{2}:\d{2})\b", text)
                        if not
