"""
WC 2026 Team Stats Scraper
- ESPN      → possession, shots on target, total shots, passes, duels, saves, fouls
- Sofascore → xG, big chances, corners, yellow/red cards, shots, offsides, tackles

Setup:
    pip install playwright
    playwright install chromium

Usage:
    python scrape_wc2026_espn.py

Output: ../data/espn/espn_wc2026_YYYYMMDD_HHMMSS.csv
"""

import csv, re, time, os, json
from datetime import datetime
from playwright.sync_api import sync_playwright

GAMES = {
    760415: ("Mexico",          "South Africa"),
    760416: ("Canada",          "Bosnia & Herzegovina"),
    760417: ("USA",             "Paraguay"),
    760418: ("Haiti",           "Scotland"),
    760419: ("Brazil",          "Morocco"),
    760420: ("Qatar",           "Switzerland"),
    760421: ("Australia",       "Turkey"),
    760422: ("Germany",         "Curacao"),
    760423: ("South Korea",     "Czech Republic"),
    760424: ("Sweden",          "Tunisia"),
    760425: ("Ivory Coast",     "Ecuador"),
    760426: ("Belgium",         "Egypt"),
    760427: ("Saudi Arabia",    "Uruguay"),
    760428: ("Spain",           "Cape Verde"),
    760429: ("Iran",            "New Zealand"),
    760430: ("Iraq",            "Norway"),
    760431: ("Argentina",       "Algeria"),
    760432: ("France",          "Senegal"),
    760433: ("Austria",         "Jordan"),
    760434: ("Ghana",           "Panama"),
    760435: ("Portugal",        "DR Congo"),
    760436: ("Uzbekistan",      "Colombia"),
    760437: ("England",         "Croatia"),
    760438: ("Czech Republic",  "South Africa"),
    760439: ("Switzerland",     "Bosnia & Herzegovina"),
    760440: ("Canada",          "Qatar"),
    760441: ("Mexico",          "South Korea"),
    760442: ("USA",             "Australia"),
    760443: ("Turkey",          "Paraguay"),
    760444: ("Brazil",          "Haiti"),
    760445: ("Scotland",        "Morocco"),
}


def name_match(a: str, b: str) -> bool:
    """Fuzzy match two team names."""
    a, b = a.lower().strip(), b.lower().strip()
    # exact
    if a == b: return True
    # one contains the other
    if a in b or b in a: return True
    # common aliases
    aliases = {
        "usa": ["united states", "us"],
        "turkey": ["türkiye", "turkiye"],
        "ivory coast": ["côte d'ivoire", "cote d'ivoire"],
        "curacao": ["curaçao"],
        "dr congo": ["congo dr", "congo democratic republic", "dr. congo"],
        "czech republic": ["czechia"],
        "cape verde": ["cabo verde", "cape verde islands"],
        "bosnia & herzegovina": ["bosnia and herzegovina", "bosnia-herzegovina"],
        "south korea": ["korea republic", "korea"],
    }
    for canonical, alts in aliases.items():
        group = [canonical] + alts
        if any(x in a for x in group) and any(x in b for x in group):
            return True
    return False


def parse_espn(text: str) -> dict:
    lines = [l.strip() for l in text.split("\n") if l.strip()]

    def stat(label):
        for i, line in enumerate(lines):
            if line == label:
                h = re.match(r"^(\d+(?:\.\d+)?)", lines[i-1]) if i > 0 else None
                a = re.match(r"^(\d+(?:\.\d+)?)", lines[i+1]) if i < len(lines)-1 else None
                if h and a:
                    return h.group(1), a.group(1)
        return None, None

    def pct(label):
        for i, line in enumerate(lines):
            if line == label:
                h = re.search(r"(\d+)%", lines[i-1]) if i > 0 else None
                a = re.search(r"(\d+)%", lines[i+1]) if i < len(lines)-1 else None
                if h and a:
                    return h.group(1), a.group(1)
        return None, None

    def sog():
        for i, line in enumerate(lines):
            if line == "Shots on Goal":
                h = re.match(r"^(\d+)", lines[i-1]) if i > 0 else None
                a = re.match(r"^(\d+)", lines[i+1]) if i < len(lines)-1 else None
                if h and a:
                    return h.group(1), a.group(1)
        return None, None

    def passes():
        for i, line in enumerate(lines):
            if line == "Accurate Passes":
                b = lines[i-1] if i > 0 else ""
                a = lines[i+1] if i < len(lines)-1 else ""
                hn = re.match(r"^(\d+)", b); hp = re.search(r"\((\d+)%\)", b)
                an = re.match(r"^(\d+)", a); ap = re.search(r"\((\d+)%\)", a)
                return (hn.group(1) if hn else None, hp.group(1) if hp else None,
                        an.group(1) if an else None, ap.group(1) if ap else None)
        return None, None, None, None

    m   = re.search(r"1 of (\d+)", text)
    ph, pa   = pct("Possession")
    sh, sa   = sog()
    dh, da   = stat("Duels Won")
    svh, sva = stat("Saves")
    fh, fa   = stat("Fouls Committed")
    p1, p2, p3, p4 = passes()

    return {
        "possession_home_pct":      ph,   "possession_away_pct":      pa,
        "shots_on_target_home":     sh,   "shots_on_target_away":     sa,
        "total_shots_match":        m.group(1) if m else None,
        "accurate_passes_home":     p1,   "accurate_passes_home_pct": p2,
        "accurate_passes_away":     p3,   "accurate_passes_away_pct": p4,
        "duels_won_home":           dh,   "duels_won_away":           da,
        "saves_home":               svh,  "saves_away":               sva,
        "fouls_home":               fh,   "fouls_away":               fa,
    }


def parse_sofascore_stats(api_json: dict) -> dict:
    result = {}
    key_map = {
        "expectedGoals":     ("xG_home",                 "xG_away"),
        "bigChancesCreated": ("big_chances_created_home", "big_chances_created_away"),
        "bigChancesMissed":  ("big_chances_missed_home",  "big_chances_missed_away"),
        "cornerKicks":       ("corners_home",             "corners_away"),
        "yellowCards":       ("yellow_cards_home",        "yellow_cards_away"),
        "redCards":          ("red_cards_home",           "red_cards_away"),
        "totalShots":        ("total_shots_home",         "total_shots_away"),
        "shotsOffTarget":    ("shots_off_target_home",    "shots_off_target_away"),
        "blockedShots":      ("shots_blocked_home",       "shots_blocked_away"),
        "offsides":          ("offsides_home",            "offsides_away"),
        "tackles":           ("tackles_home",             "tackles_away"),
        "interceptions":     ("interceptions_home",       "interceptions_away"),
        "foulsCommitted":    ("fouls_ss_home",            "fouls_ss_away"),
    }
    for period in api_json.get("statistics", []):
        if period.get("period") != "ALL":
            continue
        for group in period.get("groups", []):
            for item in group.get("statisticsItems", []):
                k = item.get("key", "")
                if k in key_map:
                    col_h, col_a = key_map[k]
                    result[col_h] = item.get("home")
                    result[col_a] = item.get("away")
    return result


def get_sofascore_event_map(context) -> dict:
    """
    Visit the Sofascore WC 2026 results pages and intercept the
    /unique-tournament/16/season/{id}/events/last/{page} API calls
    to build a map of (home_name, away_name) -> event_id.
    """
    print("Discovering Sofascore event IDs from tournament page...")
    event_map = {}   # (home, away) -> event_id
    captured  = []   # raw event objects

    page = context.new_page()

    def capture_events(response):
        if "events/last/" in response.url and "sofascore" in response.url:
            try:
                data = response.json()
                for e in data.get("events", []):
                    captured.append(e)
            except Exception:
                pass

    page.on("response", capture_events)

    # Visit the results page — Sofascore auto-loads past events
    page.goto(
        "https://www.sofascore.com/football/tournament/world/world-championship/16",
        wait_until="domcontentloaded",
        timeout=20000,
    )
    page.wait_for_timeout(5000)

    # Try clicking "Show more results" a few times to load all matches
    for _ in range(6):
        try:
            btn = page.locator("text=Show more").or_(page.locator("text=More results"))
            if btn.count() > 0:
                btn.first.click()
                page.wait_for_timeout(2000)
        except Exception:
            break

    page.close()

    for e in captured:
        home = e.get("homeTeam", {}).get("name", "")
        away = e.get("awayTeam", {}).get("name", "")
        eid  = e.get("id")
        if home and away and eid:
            event_map[(home, away)] = eid

    print(f"  Found {len(event_map)} events")
    for k, v in list(event_map.items())[:5]:
        print(f"    {k[0]} vs {k[1]} → {v}")
    return event_map


def find_ss_event(home: str, away: str, event_map: dict):
    """Match our team names to Sofascore names."""
    for (ss_home, ss_away), eid in event_map.items():
        if name_match(home, ss_home) and name_match(away, ss_away):
            return eid
        if name_match(home, ss_away) and name_match(away, ss_home):
            return eid  # reversed
    return None


def main():
    timestamp  = datetime.now().strftime("%Y%m%d_%H%M%S")
    script_dir = os.path.dirname(os.path.abspath(__file__))
    out_dir    = os.path.join(script_dir, "..", "data", "espn")
    os.makedirs(out_dir, exist_ok=True)
    out_path   = os.path.join(out_dir, f"espn_wc2026_{timestamp}.csv")

    rows = []

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(
            user_agent=(
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/124.0.0.0 Safari/537.36"
            ),
            viewport={"width": 1280, "height": 800},
            locale="en-US",
        )
        context.route(
            "**/*.{png,jpg,jpeg,gif,webp,woff,woff2,ttf,svg,ico}",
            lambda r: r.abort()
        )

        # Step 1: discover all Sofascore event IDs
        ss_event_map = get_sofascore_event_map(context)

        # Step 2: Sofascore stats page — intercept /statistics calls
        ss_stats_cache = {}   # event_id (str) -> parsed stats

        ss_page = context.new_page()

        def capture_ss_stats(response):
            m = re.search(r"/event/(\d+)/statistics", response.url)
            if m and "sofascore" in response.url:
                try:
                    ss_stats_cache[m.group(1)] = parse_sofascore_stats(response.json())
                except Exception:
                    pass

        ss_page.on("response", capture_ss_stats)

        # Step 3: ESPN + Sofascore per match
        espn_page = context.new_page()

        for espn_id, (home, away) in sorted(GAMES.items()):
            label   = f"{home} vs {away}"
            row     = {"espn_game_id": espn_id, "home_team": home, "away_team": away}
            ss_eid  = find_ss_event(home, away, ss_event_map)
            row["sofascore_event_id"] = ss_eid

            # ── ESPN ──────────────────────────────────────────────────────
            try:
                espn_page.goto(
                    f"https://www.espn.com/soccer/team-stats/_/gameId/{espn_id}",
                    wait_until="domcontentloaded", timeout=20000
                )
                espn_page.wait_for_selector("text=Possession", timeout=8000)
                row.update(parse_espn(espn_page.inner_text("body")))
                row["espn_title"]  = espn_page.title()
                row["espn_status"] = "ok"
            except Exception as e:
                row["espn_status"] = f"error: {e}"
                row["espn_title"]  = ""
                print(f"  ESPN ✗ {espn_id}: {label} — {e}")

            # ── Sofascore ─────────────────────────────────────────────────
            if ss_eid:
                ss_eid_str = str(ss_eid)
                if ss_eid_str not in ss_stats_cache:
                    # Visit the stats endpoint directly via the browser
                    # (browser has cookies/session from tournament page visit)
                    try:
                        ss_page.goto(
                            f"https://api.sofascore.com/api/v1/event/{ss_eid}/statistics",
                            wait_until="domcontentloaded", timeout=10000
                        )
                        body = ss_page.inner_text("body")
                        data = json.loads(body)
                        ss_stats_cache[ss_eid_str] = parse_sofascore_stats(data)
                    except Exception as e:
                        print(f"  SS  ✗ direct API {ss_eid}: {e}")

                if ss_eid_str in ss_stats_cache:
                    row.update(ss_stats_cache[ss_eid_str])
                    row["sofascore_status"] = "ok"
                else:
                    row["sofascore_status"] = "no_data"
            else:
                row["sofascore_status"] = "no_event_id"
                print(f"  SS  ✗ {label} — no event ID found")

            print(
                f"  ✓ {label}\n"
                f"    ESPN: poss={row.get('possession_home_pct')}/{row.get('possession_away_pct')} "
                f"sot={row.get('shots_on_target_home')}/{row.get('shots_on_target_away')} "
                f"fouls={row.get('fouls_home')}/{row.get('fouls_away')}\n"
                f"    SS:   xG={row.get('xG_home')}/{row.get('xG_away')} "
                f"bcc={row.get('big_chances_created_home')}/{row.get('big_chances_created_away')} "
                f"corners={row.get('corners_home')}/{row.get('corners_away')} "
                f"yc={row.get('yellow_cards_home')}/{row.get('yellow_cards_away')} "
                f"rc={row.get('red_cards_home')}/{row.get('red_cards_away')}"
            )

            rows.append(row)
            time.sleep(1.5)

        browser.close()

    fieldnames = [
        "espn_game_id", "home_team", "away_team",
        "espn_status", "espn_title", "sofascore_event_id", "sofascore_status",
        # ESPN
        "possession_home_pct",       "possession_away_pct",
        "shots_on_target_home",      "shots_on_target_away",
        "total_shots_match",
        "accurate_passes_home",      "accurate_passes_home_pct",
        "accurate_passes_away",      "accurate_passes_away_pct",
        "duels_won_home",            "duels_won_away",
        "saves_home",                "saves_away",
        "fouls_home",                "fouls_away",
        # Sofascore
        "xG_home",                   "xG_away",
        "big_chances_created_home",  "big_chances_created_away",
        "big_chances_missed_home",   "big_chances_missed_away",
        "total_shots_home",          "total_shots_away",
        "shots_off_target_home",     "shots_off_target_away",
        "shots_blocked_home",        "shots_blocked_away",
        "corners_home",              "corners_away",
        "yellow_cards_home",         "yellow_cards_away",
        "red_cards_home",            "red_cards_away",
        "offsides_home",             "offsides_away",
        "tackles_home",              "tackles_away",
        "interceptions_home",        "interceptions_away",
        "fouls_ss_home",             "fouls_ss_away",
    ]

    with open(out_path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
        w.writeheader()
        w.writerows(rows)

    ok_e = sum(1 for r in rows if r.get("espn_status") == "ok")
    ok_s = sum(1 for r in rows if r.get("sofascore_status") == "ok")
    print(f"\nDone — ESPN {ok_e}/{len(rows)} | Sofascore {ok_s}/{len(rows)}")
    print(f"→ {out_path}")


if __name__ == "__main__":
    main()