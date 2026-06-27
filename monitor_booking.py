#!/usr/bin/env python3
"""
Crystal Sports court-availability monitor — GitHub Actions version.

Reads configuration from environment variables (set as GitHub Secrets)
instead of hardcoding them in the file, so you can safely commit this
script to a public or private repo.

See SETUP_GITHUB_ACTIONS.md for full setup steps.
"""

import json
import os
import smtplib
import ssl
from datetime import datetime, timedelta
from email.mime.text import MIMEText

import requests

# ============== CONFIG ==============
BASE_URL = "https://crystalsports-booking.kegroup.co.th/"
DAYS_AHEAD = 14

# Optional login cookie, as a JSON string env var, e.g. {"PHPSESSID": "abc"}
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
    "User-Agent": "Mozilla/5.0 (booking-monitor script)",
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


def get_locations():
    return api_get("getLocations")


def get_stadiums():
    return api_get("getStadiums")


def collect_free_slots():
    free = {}
    locations = get_locations()
    stadiums = get_stadiums()

    now = datetime.now()
    today_str = now.strftime("%Y-%m-%d")
    now_hour_str = now.strftime("%H:00")

    for day_offset in range(DAYS_AHEAD):
        date_obj = now + timedelta(days=day_offset)
        date_str = date_obj.strftime("%Y-%m-%d")

        for loc in locations:
            loc_id = loc.get("locId")
            loc_name = loc.get("locName", f"loc{loc_id}")
            courts = [s for s in stadiums if str(s.get("locId")) == str(loc_id)]

            for court in courts:
                stadium_id = court.get("stadiumId")
                stadium_name = court.get("stadiumName", f"court{stadium_id}")
                try:
                    slots = api_post_available(date_str, stadium_id, loc_id)
                except Exception as e:
                    print(f"  [warn] failed {loc_name}/{stadium_name} {date_str}: {e}")
                    continue
                if isinstance(slots, str):
                    slots = json.loads(slots)

                for slot in slots:
                    if str(slot.get("stadiumId")) != str(stadium_id):
                        continue
                    time_name = slot.get("timeName", "")
                    reserve_status = str(slot.get("reservestatus", ""))
                    if date_str == today_str and time_name < now_hour_str:
                        continue
                    if reserve_status != "1":
                        key = f"{date_str}|{loc_name}|{stadium_name}|{time_name}"
                        free[key] = f"{date_str} {time_name} \u2014 {loc_name} / {stadium_name}"
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
    print(f"[{datetime.now()}] Checking availability...")

    try:
        current_free = collect_free_slots()
    except Exception as e:
        print(f"[error] Could not fetch availability: {e}")
        return

    if current_free:
        # Step 1: Group the data by date, storing tuples of (time, display_string)
        grouped_slots = {}
        for key in current_free.keys():
            parts = key.split("|")
            if len(parts) == 4:
                date_str, loc_name, stadium_name, time_name = parts
                if date_str not in grouped_slots:
                    grouped_slots[date_str] = []
                
                slot_info = f"{time_name} — {loc_name} ({stadium_name})"
                grouped_slots[date_str].append((time_name, slot_info))

        # Step 2: Build the text block chronologically
        body_lines = ["All Available Slots:\n"]
        for date_str in sorted(grouped_slots.keys()):
            slots_in_day = grouped_slots[date_str]
            
            # CRITICAL FIX: Sort the slots strictly by the time element (index 0 of the tuple)
            slots_in_day.sort(key=lambda x: x[0])
            
            try:
                date_obj = datetime.strptime(date_str, "%Y-%m-%d")
                day_of_week = date_obj.strftime("%A")
            except Exception:
                day_of_week = "Unknown Day"
            
            body_lines.append(f"{date_str} - {day_of_week}")
            
            for time_name, slot_info in slots_in_day:
                body_lines.append(f"- {slot_info}")
            body_lines.append("") # Spacer between different dates

        body = "\n".join(body_lines)
        
        print(body)
        send_email("Crystal Sports: available slots!", body)
        send_push("Crystal Sports slots free!", body[:1000])
    else:
        print("[info] No slots available at all.")

    save_state(current_free)


if __name__ == "__main__":
    main()
