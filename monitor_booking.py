def main():
    print(f"[{datetime.now(TZ_THAI)}] Checking availability via Playwright...")
    
    # Check if secret is actually populated in the environment
    auth_state_str = os.environ.get("PLAYWRIGHT_AUTH_STATE", "")
    print(f"  [debug] PLAYWRIGHT_AUTH_STATE length: {len(auth_state_str)}")
    if not auth_state_str:
        print("  [error] PLAYWRIGHT_AUTH_STATE is completely empty! Check GitHub Actions Secrets mapping.")
        return

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
