def collect_free_slots():
    free = {}
    locations = get_locations()
    stadiums = get_stadiums()

    # CRITICAL FIX: Explicitly use Thailand time instead of GitHub server time
    now = datetime.now(TZ_THAI)
    today_str = now.strftime("%Y-%m-%d")
    now_hour_str = now.strftime("%H:00")

    for day_offset in range(DAYS_AHEAD):
        date_obj = now + timedelta(days=day_offset)
        date_str = date_obj.strftime("%Y-%m-%d")
        
        # Determine if it's a weekday or weekend
        # weekday() returns 0 for Monday ... 4 for Friday, 5 for Saturday, 6 for Sunday
        is_weekend = date_obj.weekday() >= 5 

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
                        
                    # --- NEW TIME FILTER CONDITION ---
                    # Check if slot meets your preferred times
                    if is_weekend:
                        if time_name < "11:00":
                            continue
                    else:  # Weekday
                        if time_name < "17:00":
                            continue
                    # ----------------------------------

                    if reserve_status != "1":
                        key = f"{date_str}|{loc_name}|{stadium_name}|{time_name}"
                        free[key] = f"{date_str} {time_name} \u2014 {loc_name} / {stadium_name}"
    return free
