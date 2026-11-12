#!/usr/bin/env python3
"""
Crystal Sports court-availability monitor — GitHub Actions version.
Scans today + next 14 days (15 days total) for available ('ว่าง') slots.
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
DAYS_AHEAD = 15  # Today + next 14 days

TZ_THAI = timezone(timedelta(hours=7))
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

LOCATIONS = [
    {"locId": "LOC001", "locName": "Crystal Sports"},
    {"locId": "LOC002", "locName": "Crystal Sports G"},
]
# ============== END CONFIG ==============

session = requests.Session()
session.headers.update({
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Referer": f"{BASE_URL}/",
})
if COOKIES:
    session.cookies.update(COOKIES)


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

            params = {
                "date": date_str,
                "loc": loc_id,
                "time": "18",
                "sel": "",
            }

            try:
                resp = session.get(BASE_URL, params=params, timeout=20)
                if resp.status_code == 401 or "login" in resp.url.lower():
                    print(f"  [error] Session expired or unauthenticated for {loc_name} on {date_str}.")
                    continue
                resp.raise_for_status()
            except Exception as e:
                print(f"  [warn] failed to fetch {loc_name} for {date_str}: {e}")
                continue

            soup = BeautifulSoup(resp.text, "html.parser")

            # Match tight slot cards/buttons containing both a timestamp and "ว่าง"
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

                # Business hours filter: 11:00+ on weekends, 17:00+ on weekdays
                if is_weekend:
                    if time_name < "11:00":
                        continue
                else:
                    if time_name < "17:00":
                        continue

                # Extract availability count if shown (e.g., "ว่าง 3")
                avail_match = re.search(r"(ว่าง\s*\d*)", text)
                status_label = avail_match.group(1).strip() if avail_match else "ว่าง"

                key = f"{date_str}|{loc_name}|{status_label}|{time_name}"
                free[key] = f"{date_str} {time_name} — {loc_name} ({status_label})"

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
            server.login(SMTP_USER, SMTP_PASSWORD)
            server.sendmail(SMTP_USER, [EMAIL_TO], msg.as_string())
        print("  [ok] email sent")
    except Exception as e:
        print(f"  [error] failed to send email: {e}")


def send_push(title, message):
    if not (NTFY_ENABLED and NTFY_TOPIC):
        print("  [skip] push not configured")
        return
    try:
        requests.post(
            f"https://ntfy.sh/{NTFY_TOPIC}",
            data=message.encode("utf-8"),
            headers={"Title": title},
            timeout=10,
        )
        print("  [ok] push notification sent")
    except Exception as e:
        print(f"  [error] failed to send push notification: {e}")


def main():
    print(f"[{datetime.now(TZ_THAI)}] Checking availability...")

    try:
        current_free = collect_free_slots()
    except Exception as e:
        print(f"[error] {e}")
        return

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
