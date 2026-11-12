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
SMTP_HOST = "smtp.gmail.com"

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
                        if not match:
                            continue

                        time_name = match.group(1)

                        if date_str == today_str and time_name < now_hour_str:
                            continue

                        if is_weekend:
                            if time_name < "11:00":
                                continue
                        else:
                            if time_name < "17:00":
                                continue

                        avail_match = re.search(r"(ว่าง\s*\d*)", text)
                        status_label = avail_match.group(1).strip() if avail_match else "ว่าง"

                        key = f"{date_str}|{loc_name}|{status_label}|{time_name}"
                        free[key] = f"{date_str} {time_name} — {loc_name} ({status_label})"

                except Exception as e:
                    print(f"  [warn] failed to fetch {loc_name} for {date_str}: {e}")
                    continue

        browser.close()

    print(f"  [info] Scraped {len(free)} matching available slots across the 15-day window.")
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
        print("  [info] Email notifications disabled or credentials missing.")
        return
    try:
        msg = MIMEText(body, "plain", "utf-8")
        msg["Subject"] = subject
        msg["From"] = SMTP_USER
        msg["To"] = EMAIL_TO
        
        context = ssl.create_default_context()
        with smtplib.SMTP(SMTP_HOST, SMTP_PORT) as server:
            server.ehlo()
            server.starttls(context=context, server_hostname=SMTP_HOST)
            server.ehlo()
            server.login(SMTP_USER, SMTP_PASSWORD)
            server.sendmail(SMTP_USER, [EMAIL_TO], msg.as_string())
        print("  [info] Email notification sent successfully.")
    except Exception as e:
        print(f"  [error] failed to send email: {e}")

def send_push(title, message):
    if not (NTFY_ENABLED and NTFY_TOPIC):
        return
    try:
        import requests
        requests.post(
            f"https://ntfy.sh/{NTFY_TOPIC}",
            data=message.encode("utf-8"),
            headers={"Title": title},
            timeout=10,
        )
    except Exception as e:
        print(f"  [error] failed to send push notification: {e}")

def main():
    print(f"[{datetime.now(TZ_THAI)}] Checking availability via Playwright...")
    current_free = collect_free_slots()

    previous_free = load_previous_state()
    new_slots = {k: v for k, v in current_free.items() if k not in previous_free}

    if new_slots:
        grouped_slots = {}
        for key in new_slots.keys():
            parts = key.split("|")
            if len(parts) == 4:
                date_str, loc_name, status_label, time_name = parts
                if date_str not in grouped_slots:
                    grouped_slots[date_str] = []
                slot_info = f"{time_name} — {loc_name} ({status_label})"
                grouped_slots[date_str].append((time_name, slot_info))

        body_lines = ["New Available Slots Found:\n"]
        for date_str in sorted(grouped_slots.keys()):
            slots_in_day = grouped_slots[date_str]
            slots_in_day.sort(key=lambda x: x[0])
            try:
                date_obj = datetime.strptime(date_str, "%Y-%m-%d")
                day_of_week = date_obj.strftime("%A")
            except Exception:
                day_of_week = "Unknown Day"

            body_lines.append(f"{date_str} - {day_of_week}")
            for time_name, slot_info in slots_in_day:
                body_lines.append(f"- {slot_info}")
            body_lines.append("")

        body = "\n".join(body_lines)
        print(body)
        send_email("Crystal Sports: NEW available slots!", body)
        send_push("Crystal Sports new slots!", body[:1000])
    else:
        print("[info] No new slots since the last check.")

    save_state(current_free)

if __name__ == "__main__":
    main()
