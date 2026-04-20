import os
import re
import requests
import xml.etree.ElementTree as ET
from urllib.parse import urlparse

RSS_URL = "https://www.omnycontent.com/d/playlist/5e27a451-e6e6-4c51-aa03-a7370003783c/cb31df1e-6e60-4a02-83e6-a80b00100cc2/dfa3eb91-333d-47d5-bc34-a80b00100cc2/podcast.rss"
OUTPUT_DIR = "kettering_baptist"


def sanitize_filename(name):
    name = re.sub(r'[^\w\s\-.]', '', name)
    name = re.sub(r'\s+', '_', name.strip())
    return name[:200]


def download_sermons():
    os.makedirs(OUTPUT_DIR, exist_ok=True)

    print(f"Fetching RSS feed...")
    response = requests.get(RSS_URL, timeout=30)
    response.raise_for_status()

    root = ET.fromstring(response.content)
    channel = root.find("channel")
    items = channel.findall("item")
    print(f"Found {len(items)} episodes")

    for i, item in enumerate(items, 1):
        title = item.findtext("title", default=f"episode_{i}")
        enclosure = item.find("enclosure")
        if enclosure is None:
            print(f"  [{i}/{len(items)}] Skipping '{title}' (no audio)")
            continue

        audio_url = enclosure.get("url")
        ext = os.path.splitext(urlparse(audio_url).path)[1] or ".mp3"
        filename = sanitize_filename(title) + ext
        filepath = os.path.join(OUTPUT_DIR, filename)

        if os.path.exists(filepath):
            print(f"  [{i}/{len(items)}] Already exists: {filename}")
            continue

        print(f"  [{i}/{len(items)}] Downloading: {filename}")
        try:
            with requests.get(audio_url, stream=True, timeout=60) as r:
                r.raise_for_status()
                with open(filepath, "wb") as f:
                    for chunk in r.iter_content(chunk_size=65536):
                        f.write(chunk)
        except Exception as e:
            print(f"    ERROR: {e}")


if __name__ == "__main__":
    download_sermons()
