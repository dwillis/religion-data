import json
import os
import re
import time
from urllib.parse import urlparse, unquote

import requests

BASE_URL = "https://cheverlybaptist.org"
LIST_URL = f"{BASE_URL}/sermons?format=json"
OUTPUT_DIR = "cheverly_baptist"
HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; sermon-scraper/1.0)"}

AUDIO_URL_RE = re.compile(r'data-url="([^"]+\.mp3[^"]*)"')


def get_json(url, retries=3):
    for attempt in range(retries):
        try:
            r = requests.get(url, headers=HEADERS, timeout=30)
            r.raise_for_status()
            return r.json()
        except Exception as e:
            if attempt == retries - 1:
                raise
            print(f"  Retry {attempt + 1} for {url}: {e}")
            time.sleep(2)


def iter_sermon_items():
    """Walk Squarespace's offset-paginated collection and yield each sermon item."""
    url = LIST_URL
    page = 1
    while url:
        print(f"Fetching listing page {page}: {url}")
        data = get_json(url)
        items = data.get("items", [])
        for item in items:
            yield item
        pagination = data.get("pagination", {})
        if pagination.get("nextPage") and pagination.get("nextPageOffset"):
            url = f"{BASE_URL}/sermons?format=json&offset={pagination['nextPageOffset']}"
            page += 1
            time.sleep(0.5)
        else:
            url = None


def find_audio_url(item):
    # Check obvious top-level fields first
    for key in ("audioAssetUrl", "audioUrl"):
        val = item.get(key)
        if val and ".mp3" in val:
            return val
    # Fall back to scanning body HTML for sqs-audio-embed data-url
    body = item.get("body") or ""
    m = AUDIO_URL_RE.search(body)
    if m:
        return m.group(1)
    return None


def filename_from_url(audio_url, title):
    path = unquote(urlparse(audio_url).path)
    name = os.path.basename(path)
    if name and name.lower().endswith(".mp3"):
        return name
    safe = re.sub(r"[^\w\s\-.]", "", title).strip()
    safe = re.sub(r"\s+", "_", safe)[:150]
    return f"{safe}.mp3"


def download(audio_url, filepath):
    with requests.get(audio_url, headers=HEADERS, stream=True, timeout=120) as r:
        r.raise_for_status()
        with open(filepath, "wb") as f:
            for chunk in r.iter_content(chunk_size=65536):
                f.write(chunk)


def main():
    os.makedirs(OUTPUT_DIR, exist_ok=True)

    items = list(iter_sermon_items())
    print(f"\nFound {len(items)} sermons. Downloading audio...\n")

    for i, item in enumerate(items, 1):
        title = item.get("title", f"sermon_{i}")
        audio_url = find_audio_url(item)
        if not audio_url:
            print(f"  [{i}/{len(items)}] No audio for: {title}")
            continue

        filename = filename_from_url(audio_url, title)
        filepath = os.path.join(OUTPUT_DIR, filename)
        if os.path.exists(filepath):
            print(f"  [{i}/{len(items)}] Already exists: {filename}")
            continue

        print(f"  [{i}/{len(items)}] Downloading: {filename}")
        try:
            download(audio_url, filepath)
            time.sleep(0.5)
        except Exception as e:
            print(f"    ERROR: {e}")


if __name__ == "__main__":
    main()
