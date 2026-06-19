"""
update_matches.py
-----------------
Pipeline that:
1. Reads data/schedule/schedule_matches.json as the source of truth for matches
2. Fetches scores (hg/ag) from openfootball
3. Finds the latest wc2026_<timestamp>.json from data/imdb/
4. Writes data/frontend/matches_wc2026.json as a plain JSON array,
   keeping all fields the HTML frontend expects:
     home, away, hg, ag, imdb_score, oneline_comment
   plus enriched fields:
     match_id, date, time_et, stage, group, stadium, city, country_played

Usage:
    python3 update_matches.py
    python3 update_matches.py --dry-run
"""

import argparse
import glob
import json
import os
import re
import shutil
import requests
from datetime import datetime, timezone


OPENFOOTBALL_URL = (
    "https://raw.githubusercontent.com/openfootball/"
    "worldcup.json/master/2026/worldcup.json"
)

# ---------------------------------------------------------------------------
# Team name → FIFA 3-letter code
# ---------------------------------------------------------------------------

COUNTRY_TO_CODE: dict[str, str] = {
    "afghanistan": "AFG", "albania": "ALB", "algeria": "ALG",
    "angola": "ANG", "argentina": "ARG", "armenia": "ARM",
    "australia": "AUS", "austria": "AUT", "azerbaijan": "AZE",
    "bahrain": "BHR", "bangladesh": "BAN", "belgium": "BEL",
    "bolivia": "BOL", "bosnia": "BIH", "bosnia and herzegovina": "BIH",
    "botswana": "BOT", "brazil": "BRA", "bulgaria": "BUL",
    "burkina faso": "BFA",
    "cameroon": "CMR", "canada": "CAN", "cape verde": "CPV",
    "chile": "CHI", "china": "CHN", "colombia": "COL",
    "comoros": "COM", "congo": "CGO", "costa rica": "CRC",
    "côte d'ivoire": "CIV", "ivory coast": "CIV", "cote d'ivoire": "CIV",
    "croatia": "CRO", "cuba": "CUB", "curaçao": "CUW", "curacao": "CUW",
    "czech republic": "CZE", "czechia": "CZE",
    "dr congo": "COD", "congo dr": "COD", "democratic republic of congo": "COD",
    "denmark": "DEN", "djibouti": "DJI",
    "ecuador": "ECU", "egypt": "EGY", "el salvador": "SLV",
    "england": "ENG", "eritrea": "ERI", "ethiopia": "ETH",
    "finland": "FIN", "france": "FRA",
    "gabon": "GAB", "gambia": "GAM", "georgia": "GEO",
    "germany": "GER", "ghana": "GHA", "greece": "GRE",
    "guatemala": "GUA", "guinea": "GUI", "guinea-bissau": "GNB",
    "haiti": "HAI", "honduras": "HON", "hungary": "HUN",
    "iceland": "ISL", "india": "IND", "indonesia": "IDN",
    "iran": "IRN", "ir iran": "IRN", "iraq": "IRQ", "ireland": "IRL",
    "israel": "ISR", "italy": "ITA",
    "jamaica": "JAM", "japan": "JPN", "jordan": "JOR",
    "kenya": "KEN", "korea republic": "KOR", "south korea": "KOR",
    "korea": "KOR", "kuwait": "KUW",
    "latvia": "LVA", "lebanon": "LIB", "libya": "LBA",
    "madagascar": "MAD", "mali": "MLI", "malta": "MLT",
    "mauritania": "MTN", "mexico": "MEX", "moldova": "MDA",
    "montenegro": "MNE", "morocco": "MAR", "mozambique": "MOZ",
    "namibia": "NAM", "nepal": "NEP", "netherlands": "NED",
    "new zealand": "NZL", "nicaragua": "NCA", "nigeria": "NGA",
    "north korea": "PRK", "north macedonia": "MKD", "norway": "NOR",
    "oman": "OMA",
    "pakistan": "PAK", "palestine": "PLE", "panama": "PAN",
    "paraguay": "PAR", "peru": "PER", "philippines": "PHI",
    "poland": "POL", "portugal": "POR",
    "qatar": "QAT",
    "republic of ireland": "IRL", "romania": "ROU",
    "russia": "RUS", "rwanda": "RWA",
    "saudi arabia": "KSA", "scotland": "SCO", "senegal": "SEN",
    "serbia": "SRB", "sierra leone": "SLE", "slovakia": "SVK",
    "slovenia": "SVN", "somalia": "SOM", "south africa": "RSA",
    "spain": "ESP", "sudan": "SDN", "sweden": "SWE",
    "switzerland": "SUI", "syria": "SYR",
    "tanzania": "TAN", "thailand": "THA", "togo": "TOG",
    "trinidad and tobago": "TRI", "tunisia": "TUN",
    "turkey": "TUR", "türkiye": "TUR",
    "uganda": "UGA", "ukraine": "UKR",
    "united arab emirates": "UAE",
    "united states": "USA", "usa": "USA",
    "uruguay": "URU", "uzbekistan": "UZB",
    "venezuela": "VEN", "vietnam": "VIE",
    "wales": "WAL",
    "yemen": "YEM",
    "zambia": "ZAM", "zimbabwe": "ZIM",
}


def to_code(name: str) -> str | None:
    key = name.lower().strip()
    if key in COUNTRY_TO_CODE:
        return COUNTRY_TO_CODE[key]
    for country, c in COUNTRY_TO_CODE.items():
        if country in key or key in country:
            return c
    return None


def normalise(name: str) -> str:
    return re.sub(r"[^a-z0-9 ]", "", name.lower().strip())


def title_to_codes(episode_title: str) -> list[str]:
    body = episode_title.split(":", 1)[-1] if ":" in episode_title else episode_title
    parts = re.split(r"\s+vs\.?\s+|\s+versus\s+", body, flags=re.IGNORECASE)
    codes = []
    for part in parts:
        key = normalise(part)
        code = COUNTRY_TO_CODE.get(key)
        if not code:
            for country, c in COUNTRY_TO_CODE.items():
                if country in key or key in country:
                    code = c
                    break
        if code:
            codes.append(code)
    return codes


# ---------------------------------------------------------------------------
# File helpers
# ---------------------------------------------------------------------------

TIMESTAMP_RE = re.compile(r"_(\d{8}_\d{6})\.json$", re.IGNORECASE)


def parse_timestamp(path: str) -> datetime:
    m = TIMESTAMP_RE.search(os.path.basename(path))
    if m:
        return datetime.strptime(m.group(1), "%Y%m%d_%H%M%S")
    return datetime.fromtimestamp(os.path.getmtime(path))


def find_latest_imdb_file(directory: str, prefix: str = "wc2026_") -> str:
    pattern = os.path.join(directory, f"{prefix}*.json")
    candidates = glob.glob(pattern)
    if not candidates:
        raise FileNotFoundError(f"No files matching '{pattern}' found in '{directory}'")
    return max(candidates, key=parse_timestamp)


# ---------------------------------------------------------------------------
# Scores from openfootball  →  {frozenset(home, away): (hg, ag)}
# ---------------------------------------------------------------------------

def fetch_scores() -> dict[frozenset, tuple[int, int]]:
    print(f"  Fetching scores from openfootball...")
    r = requests.get(OPENFOOTBALL_URL, headers={"User-Agent": "Mozilla/5.0"}, timeout=15)
    r.raise_for_status()
    scores = {}
    for m in r.json().get("matches", []):
        t1, t2 = m.get("team1", ""), m.get("team2", "")
        score = m.get("score", {}).get("ft")
        if not score or re.match(r'^[WL]\d+$', t1) or re.match(r'^[WL]\d+$', t2):
            continue
        h, a = to_code(t1), to_code(t2)
        if h and a:
            scores[frozenset([h, a])] = (score[0], score[1])
    print(f"  Got {len(scores)} scores")
    return scores


# ---------------------------------------------------------------------------
# IMDb lookups
# ---------------------------------------------------------------------------

def build_imdb_lookups(episodes: list[dict]) -> tuple[dict, dict]:
    by_pair: dict[frozenset, float | None] = {}
    by_date: dict[str, list[float | None]] = {}
    for ep in episodes:
        title  = ep.get("title", "")
        rating = ep.get("rating")
        y, mo, d = ep.get("year"), ep.get("month"), ep.get("day")
        date_str = f"{y}-{mo:02d}-{d:02d}" if (y and mo and d) else ""
        codes = title_to_codes(title)
        if len(codes) == 2:
            by_pair[frozenset(codes)] = rating
        elif date_str:
            by_date.setdefault(date_str, []).append(rating)
    return by_pair, by_date


# ---------------------------------------------------------------------------
# Preserve existing comments
# ---------------------------------------------------------------------------

def load_existing_comments(matches_path: str) -> dict[frozenset, str]:
    if not os.path.exists(matches_path):
        return {}
    with open(matches_path, encoding="utf-8") as f:
        raw = json.load(f)
    existing = raw if isinstance(raw, list) else raw.get("matches", [])
    return {
        frozenset([m["home"], m["away"]]): m.get("oneline_comment", "")
        for m in existing
        if m.get("home") and m.get("away")
    }


# ---------------------------------------------------------------------------
# Build final match list
# ---------------------------------------------------------------------------

def build_matches(
    schedule: list[dict],
    scores: dict[frozenset, tuple[int, int]],
    by_pair: dict,
    by_date: dict,
    existing_comments: dict[frozenset, str],
) -> tuple[list[dict], int, int]:

    date_cursor: dict[str, int] = {}
    n_pair = n_date = 0
    out = []

    for m in schedule:
        h, a = m.get("home", ""), m.get("away", "")
        if not (h and a):
            continue  # skip unresolved knockout slots

        pair_key = frozenset([h, a])
        date     = m.get("date", "")

        # --- scores (hg / ag) ---
        if pair_key in scores:
            hg, ag = scores[pair_key]
        else:
            hg, ag = None, None

        # --- imdb_score ---
        if pair_key in by_pair:
            imdb_score = by_pair[pair_key]
            n_pair += 1
        elif date in by_date:
            idx = date_cursor.get(date, 0)
            ratings = by_date[date]
            imdb_score = ratings[idx] if idx < len(ratings) else None
            date_cursor[date] = idx + 1
            if imdb_score is not None:
                n_date += 1
        else:
            imdb_score = None

        out.append({
            "home":           h,
            "away":           a,
            "hg":             hg,
            "ag":             ag,
            # enriched fields
            "match_id":       m.get("match_id"),
            "date":           date,
            "time_et":        m.get("time_et"),
            "stage":          m.get("stage"),
            "group":          m.get("group"),
            "stadium":        m.get("stadium"),
            "city":           m.get("city"),
            "country_played": m.get("country_played"),
            "imdb_score":     imdb_score,
            "oneline_comment": existing_comments.get(pair_key, ""),
        })

    return out, n_pair, n_date


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def update(
    schedule_path: str,
    matches_path: str,
    imdb_dir: str,
    prefix: str = "wc2026_",
    dry_run: bool = False,
) -> None:
    # 1. Load schedule
    with open(schedule_path, encoding="utf-8") as f:
        raw_schedule = json.load(f)
    schedule = raw_schedule if isinstance(raw_schedule, list) else raw_schedule.get("matches", [])
    print(f"[✓] Schedule loaded  : {schedule_path}  ({len(schedule)} total slots)")

    # 2. Fetch scores
    try:
        scores = fetch_scores()
    except Exception as e:
        print(f"[!] Could not fetch scores: {e} — real=False for all matches")
        scores = {}

    # 3. Latest IMDb file
    imdb_path = find_latest_imdb_file(imdb_dir, prefix)
    print(f"[✓] Latest IMDb file : {imdb_path}")
    with open(imdb_path, encoding="utf-8") as f:
        imdb_data = json.load(f)
    episodes = imdb_data.get("episodes", imdb_data) if isinstance(imdb_data, dict) else imdb_data

    # 4. Preserve existing comments
    existing_comments = load_existing_comments(matches_path)

    # 5. Build IMDb lookups
    by_pair, by_date = build_imdb_lookups(episodes)

    # 6. Build output
    enriched, n_pair, n_date = build_matches(schedule, scores, by_pair, by_date, existing_comments)
    real_count = sum(1 for m in enriched if m["hg"] is not None)
    print(f"[✓] Resolved matches : {len(enriched)}")
    print(f"[✓] With scores      : {real_count}")
    print(f"[✓] IMDb scores found: {n_pair + n_date}  ({n_pair} by team pair, {n_date} by date)")

    if dry_run:
        print("\n[dry-run] First 3 entries:")
        print(json.dumps(enriched[:3], indent=2, ensure_ascii=False))
        return

    # 7. Backup + write as plain array (what the HTML expects)
    if os.path.exists(matches_path):
        shutil.copy2(matches_path, matches_path + ".bak")
        print(f"[✓] Backup saved     : {matches_path}.bak")

    with open(matches_path, "w", encoding="utf-8") as f:
        json.dump(enriched, f, indent=2, ensure_ascii=False)
    print(f"[✓] Updated          : {matches_path}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Build matches_wc2026.json")
    parser.add_argument("--schedule", default="../data/schedule/schedule_matches.json")
    parser.add_argument("--matches",  default="../data/frontend/matches_wc2026.json")
    parser.add_argument("--imdb-dir", default="../data/imdb/")
    parser.add_argument("--prefix",   default="wc2026_")
    parser.add_argument("--dry-run",  action="store_true")
    args = parser.parse_args()
    update(args.schedule, args.matches, args.imdb_dir, args.prefix, args.dry_run)


if __name__ == "__main__":
    main()