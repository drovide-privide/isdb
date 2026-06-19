"""
update_matches.py
-----------------
Pipeline that:
1. Reads data/schedule/schedule_matches.json as the source of truth for matches
2. Finds the latest wc2026_<timestamp>.json from data/imdb/
3. Merges IMDb scores onto each match using two strategies:
   - Group stage: match by team pair (frozenset of FIFA codes)
   - Knockouts:   match by date (IMDb uses "Episode #4.x" with no team names)
4. Preserves existing oneline_comment values if already filled
5. Writes the result to data/frontend/matches_wc2026.json

Usage:
    python3 update_matches.py
    python3 update_matches.py --dry-run
    python3 update_matches.py --schedule ../data/schedule/schedule_matches.json
                              --matches  ../data/frontend/matches_wc2026.json
                              --imdb-dir ../data/imdb/
"""

import argparse
import glob
import json
import os
import re
import shutil
from datetime import datetime, timezone


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


def normalise(name: str) -> str:
    return re.sub(r"[^a-z0-9 ]", "", name.lower().strip())


def title_to_codes(episode_title: str) -> list[str]:
    """Parse 'Group A: Qatar vs. Ecuador' → ['QAT', 'ECU']"""
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
        raise FileNotFoundError(
            f"No files matching '{pattern}' found in '{directory}'"
        )
    return max(candidates, key=parse_timestamp)


# ---------------------------------------------------------------------------
# Core logic
# ---------------------------------------------------------------------------

def build_imdb_lookups(episodes: list[dict]) -> tuple[dict, dict]:
    """
    Returns two lookups:
      by_pair : frozenset({codeA, codeB}) → rating
                Used for group stage where titles are "Group A: Mexico vs. South Africa"
      by_date : "YYYY-MM-DD" → [rating, rating, ...]
                Used for knockouts where titles are just "Episode #4.1" etc.
                Multiple matches can share a date so we keep an ordered list.
    """
    by_pair: dict[frozenset, float | None] = {}
    by_date: dict[str, list[float | None]] = {}

    for ep in episodes:
        title  = ep.get("title", "")
        rating = ep.get("rating")
        y, mo, d = ep.get("year"), ep.get("month"), ep.get("day")
        date_str = f"{y}-{mo:02d}-{d:02d}" if (y and mo and d) else ""

        codes = title_to_codes(title)
        if len(codes) == 2:
            # Named episode — index by team pair
            by_pair[frozenset(codes)] = rating
        elif date_str:
            # Unnamed knockout episode — index by date in episode order
            by_date.setdefault(date_str, []).append(rating)

    return by_pair, by_date


def load_existing_comments(matches_path: str) -> dict[frozenset, str]:
    """Preserve any oneline_comments already filled in."""
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


def build_matches_from_schedule(schedule: list[dict]) -> list[dict]:
    """
    Convert schedule_matches entries into the matches_wc2026 format.
    Only includes matches where both home and away are resolved.
    """
    out = []
    for m in schedule:
        if not (m.get("home") and m.get("away")):
            continue
        out.append({
            "match_id":       m.get("match_id"),
            "date":           m.get("date"),
            "time_et":        m.get("time_et"),
            "stage":          m.get("stage"),
            "group":          m.get("group"),
            "stadium":        m.get("stadium"),
            "city":           m.get("city"),
            "country_played": m.get("country_played"),
            "home":           m["home"],
            "away":           m["away"],
        })
    return out


def enrich_matches(
    matches: list[dict],
    by_pair: dict,
    by_date: dict,
    existing_comments: dict[frozenset, str],
) -> tuple[list[dict], int, int]:
    """
    Add imdb_score and oneline_comment to every match.

    Strategy:
      1. Try by_pair (team codes) — works for group stage named episodes
      2. Fall back to by_date (date order) — works for knockout "Episode #x.y"
         Multiple matches on the same date are consumed in order as we iterate.

    Returns (enriched, n_by_pair, n_by_date).
    """
    # Track consumption position per date for the by_date fallback
    date_cursor: dict[str, int] = {}

    n_by_pair = 0
    n_by_date = 0
    enriched  = []

    for m in matches:
        m = dict(m)
        pair_key = frozenset([m["home"], m["away"]])
        date     = m.get("date", "")

        if pair_key in by_pair:
            # Group stage: matched by team names
            m["imdb_score"] = by_pair[pair_key]
            n_by_pair += 1
        elif date in by_date:
            # Knockout: consume the next rating for this date in order
            idx = date_cursor.get(date, 0)
            ratings = by_date[date]
            if idx < len(ratings):
                m["imdb_score"] = ratings[idx]
                date_cursor[date] = idx + 1
                n_by_date += 1
            else:
                m["imdb_score"] = None
        else:
            m["imdb_score"] = None

        m["oneline_comment"] = existing_comments.get(pair_key, "")
        enriched.append(m)

    return enriched, n_by_pair, n_by_date


# ---------------------------------------------------------------------------
# Main update function
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

    # 2. Find latest IMDb file
    imdb_path = find_latest_imdb_file(imdb_dir, prefix)
    print(f"[✓] Latest IMDb file : {imdb_path}")

    # 3. Load IMDb episodes
    with open(imdb_path, encoding="utf-8") as f:
        imdb_data = json.load(f)
    episodes = imdb_data.get("episodes", imdb_data) if isinstance(imdb_data, dict) else imdb_data

    # 4. Preserve existing comments
    existing_comments = load_existing_comments(matches_path)

    # 5. Build base match list from schedule (resolved only)
    matches = build_matches_from_schedule(schedule)
    print(f"[✓] Resolved matches : {len(matches)}  (unresolved knockouts skipped)")

    # 6. Build IMDb lookups and enrich
    by_pair, by_date = build_imdb_lookups(episodes)
    enriched, n_pair, n_date = enrich_matches(matches, by_pair, by_date, existing_comments)
    print(f"[✓] IMDb scores found: {n_pair + n_date}  "
          f"({n_pair} by team pair, {n_date} by date)")

    # 7. Build output
    out = {
        "last_updated":     datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "source_imdb_file": os.path.basename(imdb_path),
        "source_schedule":  os.path.basename(schedule_path),
        "matches":          enriched,
    }

    if dry_run:
        print("\n[dry-run] Output preview (first 3 matches):")
        preview = dict(out)
        preview["matches"] = enriched[:3]
        print(json.dumps(preview, indent=2, ensure_ascii=False))
        return

    # 8. Backup + write
    if os.path.exists(matches_path):
        bak = matches_path + ".bak"
        shutil.copy2(matches_path, bak)
        print(f"[✓] Backup saved     : {bak}")

    with open(matches_path, "w", encoding="utf-8") as f:
        json.dump(out, f, indent=2, ensure_ascii=False)
    print(f"[✓] Updated          : {matches_path}")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(
        description="Build matches_wc2026.json from schedule + IMDb ratings",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "Examples:\n"
            "  python3 update_matches.py\n"
            "  python3 update_matches.py --dry-run\n"
        ),
    )
    parser.add_argument(
        "--schedule",
        default="../data/schedule/schedule_matches.json",
        help="Path to schedule_matches.json",
    )
    parser.add_argument(
        "--matches",
        default="../data/frontend/matches_wc2026.json",
        help="Path to matches_wc2026.json output",
    )
    parser.add_argument(
        "--imdb-dir",
        default="../data/imdb/",
        help="Directory with wc2026_<timestamp>.json files",
    )
    parser.add_argument(
        "--prefix",
        default="wc2026_",
        help="IMDb filename prefix  (default: wc2026_)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Preview output without writing any files",
    )
    args = parser.parse_args()

    update(
        schedule_path=args.schedule,
        matches_path=args.matches,
        imdb_dir=args.imdb_dir,
        prefix=args.prefix,
        dry_run=args.dry_run,
    )


if __name__ == "__main__":
    main()