"""
Run this first to debug Sofascore connectivity and find the right season ID.
python debug_sofascore.py
"""
import requests, json

headers = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "en-US,en;q=0.9",
    "Referer": "https://www.sofascore.com/",
    "Origin": "https://www.sofascore.com",
}

print("=== 1. Check seasons for tournament 16 (World Cup) ===")
r = requests.get("https://api.sofascore.com/api/v1/unique-tournament/16/seasons", headers=headers, timeout=10)
print(f"Status: {r.status_code}")
if r.status_code == 200:
    seasons = r.json().get("seasons", [])
    for s in seasons:
        print(f"  id={s['id']}  year={s.get('year')}  name={s.get('name')}")
    # Find 2026
    s2026 = next((s for s in seasons if "2026" in str(s.get("year","")) or "2026" in str(s.get("name",""))), None)
    if s2026:
        print(f"\n>>> 2026 season id = {s2026['id']}")
        season_id = s2026["id"]
    else:
        print("2026 not found, using 58210")
        season_id = 58210
else:
    print(r.text[:200])
    season_id = 58210

print(f"\n=== 2. Fetch events for season {season_id} ===")
for endpoint in ["last", "next"]:
    for page in range(0, 3):
        url = f"https://api.sofascore.com/api/v1/unique-tournament/16/season/{season_id}/events/{endpoint}/{page}"
        r = requests.get(url, headers=headers, timeout=10)
        print(f"  {endpoint}/{page}: status={r.status_code}", end="")
        if r.status_code == 200:
            events = r.json().get("events", [])
            print(f"  events={len(events)}", end="")
            if events:
                e = events[0]
                print(f"  first: {e['homeTeam']['name']} vs {e['awayTeam']['name']} id={e['id']}")
            else:
                print()
        else:
            print(f"  {r.text[:100]}")
        if r.status_code != 200:
            break

print("\n=== 3. Test stats for Brazil vs Morocco (id=15186850) ===")
r = requests.get("https://api.sofascore.com/api/v1/event/15186850/statistics", headers=headers, timeout=10)
print(f"Status: {r.status_code}")
if r.status_code == 200:
    data = r.json()
    for period in data.get("statistics", []):
        if period.get("period") == "ALL":
            for group in period.get("groups", []):
                for item in group.get("statisticsItems", []):
                    print(f"  {item['key']}: {item.get('home')} / {item.get('away')}")
else:
    print(r.text[:200])