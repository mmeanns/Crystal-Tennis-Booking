def collect_free_slots():
    free = {}
    now = datetime.now(TZ_THAI)
    today_str = now.strftime("%Y-%m-%d")
    now_hour_str = now.strftime("%H:00")

    auth_state_str = os.environ.get("PLAYWRIGHT_AUTH_STATE")

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context()
        
        if auth_state_str:
            try:
                state_json = json.loads(auth_state_str)
                cookies = state_json.get("cookies", [])
                if cookies:
                    context.add_cookies(cookies)
                    print(f"  [info] Successfully injected {len(cookies)} authentication cookies.")
            except Exception as e:
                print(f"  [warn] Failed to parse PLAYWRIGHT_AUTH_STATE JSON: {e}")

        page = context.new_page()

        # Test the first URL and inspect what cookies the browser actually holds
        test_url = f"{BASE_URL}?date={today_str}&loc=LOC001&time=18&sel="
        try:
            page.goto(test_url, timeout=30000)
            page.wait_for_load_state("domcontentloaded", timeout=15000)
            print(f"  [debug] Final landed URL: {page.url}")
            print(f"  [debug] Active cookies in browser: {[c['name'] for c in context.cookies()]}")
        except Exception as e:
            print(f"  [error] Initial navigation failed: {e}")

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
                        print(f"  [error] Session expired. Redirected to login for {loc_name} on {date_str}. Current URL: {page.url}")
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
