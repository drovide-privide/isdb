"""
Test proper Statistics tab interaction and stat text parsing on Sofascore.
python debug_sofascore_names.py
"""
import re, time
from playwright.sync_api import sync_playwright

TEST_URL = "https://www.sofascore.com/football/match/morocco-brazil/YUbsDVb"

def main():
    captured_stats = {}

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=False)
        context = browser.new_context(
            user_agent="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
            viewport={"width": 1280, "height": 900},
        )
        page = context.new_page()

        # Intercept ALL sofascore API responses
        def on_response(response):
            if "sofascore" not in response.url:
                return
            if any(x in response.url for x in ["/statistics", "/details", "/graph", "/highlights"]):
                print(f"  API CALL: {response.url}  status={response.status}")
                if "/statistics" in response.url:
                    try:
                        data = response.json()
                        periods = [p.get("period") for p in data.get("statistics", [])]
                        print(f"    → periods: {periods}")
                        m = re.search(r"/event/(\d+)/", response.url)
                        if m:
                            captured_stats[m.group(1)] = data
                    except Exception as e:
                        print(f"    → parse error: {e}")

        page.on("response", on_response)

        print(f"Loading page...")
        page.goto(TEST_URL, wait_until="networkidle", timeout=30000)
        page.wait_for_timeout(2000)

        print("\nLooking for Statistics tab...")
        # Find all tabs/buttons and print them
        tabs = page.locator("a, button, [role='tab'], li[role='tab']")
        count = tabs.count()
        print(f"  Total tab-like elements: {count}")
        for i in range(min(count, 30)):
            try:
                txt = tabs.nth(i).inner_text().strip()
                if txt:
                    print(f"    [{i}] '{txt}'")
            except Exception:
                pass

        # Click the right Statistics tab (look for one in match nav, not page nav)
        print("\nClicking Statistics tab (index-based)...")
        # Try clicking each one that says "Statistics" until stats load
        for i in range(count):
            try:
                el = tabs.nth(i)
                txt = el.inner_text().strip()
                if "statistic" in txt.lower() or "stats" in txt.lower():
                    print(f"  Clicking tab [{i}]: '{txt}'")
                    el.click()
                    page.wait_for_timeout(3000)
                    # Check if stats appeared in page text
                    body = page.inner_text("body")
                    if "Ball Possession" in body or "Expected Goals" in body or "Corner Kicks" in body:
                        print(f"  ✓ Stats text found in page after clicking [{i}]!")
                        # Extract stats from text
                        print("\n=== STATS IN PAGE TEXT ===")
                        lines = [l.strip() for l in body.split("\n") if l.strip()]
                        stat_keywords = ["Possession", "Expected Goals", "Corner", "Yellow Card",
                                        "Big Chance", "Total Shots", "Shots on", "Fouls", "Offsides",
                                        "Tackles", "Interceptions", "Red Card", "Blocked"]
                        for j, line in enumerate(lines):
                            if any(kw.lower() in line.lower() for kw in stat_keywords):
                                ctx = lines[max(0,j-1):j+2]
                                print(f"  {ctx}")
                        break
            except Exception as e:
                pass

        if not captured_stats:
            print("\nNo stats intercepted via API. Dumping page text snippet...")
            body = page.inner_text("body")
            # Find the stats section
            for kw in ["Ball Possession", "Expected Goals", "Possession", "Corner Kicks"]:
                idx = body.find(kw)
                if idx >= 0:
                    print(f"\nFound '{kw}' at {idx}:")
                    print(body[max(0,idx-200):idx+500])
                    break

        browser.close()

if __name__ == "__main__":
    main()