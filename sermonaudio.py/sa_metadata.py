#!/usr/bin/env python3
"""
sa_metadata.py

Export sermon metadata from SermonAudio without downloading audio.

Uses the same API endpoint as sa_broadcaster.py but preserves the full
JSON response instead of extracting only sermon IDs.

Usage:
    # Single broadcaster
    python sermonaudio.py/sa_metadata.py ghbc
    python sermonaudio.py/sa_metadata.py https://www.sermonaudio.com/broadcasters/ghbc/

    # All broadcasters in a state
    python sermonaudio.py/sa_metadata.py --state MD

    # Dump raw JSON (first run, to inspect field names)
    python sermonaudio.py/sa_metadata.py ghbc --raw
"""

import argparse
import csv
import json
import os
import re
import sys
import time
from typing import Optional

import requests
from bs4 import BeautifulSoup

BASE_URL = "https://www.sermonaudio.com"
API_BASE = "https://api.sermonaudio.com/v2"
API_SERMONS = f"{API_BASE}/node/sermons"
API_BROADCASTERS = f"{API_BASE}/node/broadcasters"
HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; SA-Metadata/1.0)"}

session = requests.Session()
session.headers.update(HEADERS)


def ensure_api_key():
    if "X-API-Key" in session.headers:
        return
    key = None
    try:
        import sa_auth
        key = sa_auth.get_api_key()
    except Exception:
        pass
    if not key:
        key = "3C2E7B5F-5E3C-4AAC-AF49-0906CBDA920F"
    session.headers["X-API-Key"] = key


def slugify(name: str) -> str:
    if not name:
        return "untitled"
    name = name.strip().replace(":", " -")
    name = re.sub(r'[\\/*?"<>|]+', "", name)
    return re.sub(r"\s+", " ", name).strip() or "untitled"


def extract_broadcaster_id(arg: str) -> str:
    arg = arg.strip()
    m = re.search(r"/broadcasters/([^/]+)", arg)
    if m:
        return m.group(1)
    if arg.startswith("http"):
        return arg.rstrip("/").split("/")[-1]
    return arg


def get_broadcaster_name(broadcaster_id: str) -> str:
    url = f"{BASE_URL}/broadcasters/{broadcaster_id}"
    try:
        resp = session.get(url, timeout=20)
        resp.raise_for_status()
        soup = BeautifulSoup(resp.text, "html.parser")
        h1 = soup.find("h1")
        if h1 and h1.get_text(strip=True):
            return re.sub(r"^#", "", h1.get_text(strip=True)).strip()
        if soup.title and soup.title.string:
            m = re.search(r"\|\s*(.+?)\s*\|\s*SermonAudio", soup.title.string)
            if m:
                return m.group(1).strip()
    except Exception:
        pass
    return f"Broadcaster {broadcaster_id}"


# -- Flatten a sermon JSON object to a row dict --

def flatten_sermon(item: dict, broadcaster_id: str, broadcaster_name: str) -> dict:
    speaker = item.get("speaker") or {}
    broadcaster = item.get("broadcaster") or {}
    series = item.get("series") or {}

    series_title = series.get("title", "") if isinstance(series, dict) else str(series)
    series_id = series.get("seriesID", "") if isinstance(series, dict) else ""

    duration = item.get("audioDurationSeconds") or item.get("videoDurationSeconds") or ""

    return {
        "sermon_id": item.get("sermonID", ""),
        "title": item.get("fullTitle") or item.get("displayTitle") or "",
        "subtitle": item.get("subtitle") or "",
        "speaker": speaker.get("displayName") or "",
        "speaker_id": speaker.get("speakerID") or "",
        "date": item.get("preachDate") or "",
        "publish_date": item.get("publishDate") or "",
        "bible_text": item.get("bibleText") or "",
        "event_type": item.get("eventType") or "",
        "series": series_title,
        "series_id": series_id,
        "duration_seconds": duration,
        "download_count": item.get("downloadCount") or "",
        "more_info": item.get("moreInfoText") or "",
        "language": item.get("languageCode") or "",
        "keywords": item.get("keywords") or "",
        "has_audio": item.get("hasAudio", ""),
        "has_video": item.get("hasVideo", ""),
        "broadcaster_id": broadcaster.get("broadcasterID") or broadcaster_id,
        "broadcaster_name": broadcaster.get("displayName") or broadcaster_name,
        "broadcaster_location": broadcaster.get("location") or "",
        "broadcaster_denomination": broadcaster.get("denomination") or "",
        "broadcaster_minister": broadcaster.get("minister") or "",
    }


CSV_FIELDS = [
    "sermon_id", "title", "subtitle", "speaker", "speaker_id", "date",
    "publish_date", "bible_text", "event_type", "series", "series_id",
    "duration_seconds", "download_count", "more_info", "language", "keywords",
    "has_audio", "has_video",
    "broadcaster_id", "broadcaster_name", "broadcaster_location",
    "broadcaster_denomination", "broadcaster_minister",
]


# -- Pagination --

def collect_sermons(broadcaster_id: str, page_size: int = 100,
                    max_pages: int = 200) -> list[dict]:
    ensure_api_key()
    all_items: list[dict] = []
    seen: set[str] = set()

    for page in range(1, max_pages + 1):
        params = {
            "broadcasterID": broadcaster_id,
            "pageSize": str(page_size),
            "page": str(page),
            "sortBy": "newest",
            "requireAudio": "false",
        }
        try:
            resp = session.get(API_SERMONS, params=params, timeout=30)
            if resp.status_code != 200:
                print(f"  HTTP {resp.status_code} on page {page}, stopping.", file=sys.stderr)
                break
            data = resp.json()
        except Exception as e:
            print(f"  Error on page {page}: {e}", file=sys.stderr)
            break

        results = data.get("results") or data.get("sermons") or []
        if not results:
            break

        new = 0
        for item in results:
            sid = str(item.get("sermonID", ""))
            if sid and sid not in seen:
                seen.add(sid)
                all_items.append(item)
                new += 1

        total_count = data.get("totalCount") or "?"
        print(f"  page {page}: {new} new sermons (total {len(all_items)}/{total_count})",
              file=sys.stderr)

        if len(results) < page_size:
            break
        time.sleep(0.35)

    return all_items


# -- State-level: discover all broadcasters via API --

def collect_state_broadcaster_ids(state: str) -> list[tuple[str, str]]:
    ensure_api_key()
    print(f"Fetching broadcaster list for state '{state}' via API...", file=sys.stderr)

    all_broadcasters: list[tuple[str, str]] = []
    seen: set[str] = set()

    for page in range(1, 100):
        params = {
            "state": state,
            "pageSize": "100",
            "page": str(page),
            "sortBy": "sermoncount",
        }
        try:
            resp = session.get(API_BROADCASTERS, params=params, timeout=30)
            if resp.status_code != 200:
                print(f"  HTTP {resp.status_code} on page {page}, stopping.", file=sys.stderr)
                break
            data = resp.json()
        except Exception as e:
            print(f"  Error on page {page}: {e}", file=sys.stderr)
            break

        results = data.get("results") or []
        if not results:
            break

        for b in results:
            bid = b.get("broadcasterID", "")
            name = b.get("displayName") or b.get("shortName") or bid
            if bid and bid not in seen:
                seen.add(bid)
                all_broadcasters.append((bid, name))

        total = data.get("totalCount") or "?"
        print(f"  page {page}: {len(results)} broadcasters (total {len(all_broadcasters)}/{total})",
              file=sys.stderr)

        if len(results) < 100:
            break
        time.sleep(0.35)

    print(f"Found {len(all_broadcasters)} broadcasters in {state}.", file=sys.stderr)
    return all_broadcasters


def load_broadcaster_ids(path: str) -> list[str]:
    ids = []
    with open(path) as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith("#"):
                ids.append(extract_broadcaster_id(line))
    return ids


def main():
    parser = argparse.ArgumentParser(
        description="Export sermon metadata from SermonAudio as CSV.")
    parser.add_argument("broadcaster", nargs="?",
                        help="Broadcaster URL or ID (e.g. ghbc)")
    parser.add_argument("--state",
                        help="Fetch all broadcasters in a US state via API (e.g. MD)")
    parser.add_argument("--broadcasters-file",
                        help="File with one broadcaster ID/URL per line")
    parser.add_argument("--raw", action="store_true",
                        help="Dump raw JSON instead of CSV (for field discovery)")
    parser.add_argument("--out-dir", default=".",
                        help="Output directory for CSV/JSON files")
    parser.add_argument("--page-size", type=int, default=100)
    args = parser.parse_args()

    if not args.broadcaster and not args.state and not args.broadcasters_file:
        parser.error("Provide a broadcaster ID/URL, --state, or --broadcasters-file")

    os.makedirs(args.out_dir, exist_ok=True)

    # Multi-broadcaster mode: --state or --broadcasters-file
    if args.state or args.broadcasters_file:
        if args.state:
            broadcasters = collect_state_broadcaster_ids(args.state)
        else:
            bids = load_broadcaster_ids(args.broadcasters_file)
            broadcasters = [(bid, bid) for bid in bids]

        if not broadcasters:
            print("No broadcasters found.", file=sys.stderr)
            return 1

        label = args.state or "multi"
        all_rows: list[dict] = []
        for i, (bid, bname) in enumerate(broadcasters, 1):
            print(f"\n[{i}/{len(broadcasters)}] {bname} ({bid})", file=sys.stderr)
            items = collect_sermons(bid, page_size=args.page_size)

            if args.raw and items:
                raw_path = os.path.join(args.out_dir, f"{slugify(bid)}_raw.json")
                with open(raw_path, "w") as f:
                    json.dump(items, f, indent=2, default=str)
                print(f"  Wrote {len(items)} raw items -> {raw_path}", file=sys.stderr)
            else:
                for item in items:
                    all_rows.append(flatten_sermon(item, bid, bname))

        if not args.raw:
            out_path = os.path.join(args.out_dir, f"sermonaudio_{label}_metadata.csv")
            with open(out_path, "w", newline="") as f:
                writer = csv.DictWriter(f, fieldnames=CSV_FIELDS)
                writer.writeheader()
                writer.writerows(all_rows)
            print(f"\nWrote {len(all_rows)} sermons -> {out_path}", file=sys.stderr)
    else:
        bid = extract_broadcaster_id(args.broadcaster)
        bname = get_broadcaster_name(bid)
        print(f"Broadcaster: {bname} ({bid})", file=sys.stderr)

        items = collect_sermons(bid, page_size=args.page_size)
        if not items:
            print("No sermons found.", file=sys.stderr)
            return 1

        if args.raw:
            out_path = os.path.join(args.out_dir, f"{slugify(bid)}_raw.json")
            with open(out_path, "w") as f:
                json.dump(items, f, indent=2, default=str)
            print(f"Wrote {len(items)} raw items -> {out_path}", file=sys.stderr)
        else:
            rows = [flatten_sermon(item, bid, bname) for item in items]
            out_path = os.path.join(args.out_dir, f"{slugify(bid)}_metadata.csv")
            with open(out_path, "w", newline="") as f:
                writer = csv.DictWriter(f, fieldnames=CSV_FIELDS)
                writer.writeheader()
                writer.writerows(rows)
            print(f"Wrote {len(rows)} sermons -> {out_path}", file=sys.stderr)

    return 0


if __name__ == "__main__":
    sys.exit(main() or 0)
