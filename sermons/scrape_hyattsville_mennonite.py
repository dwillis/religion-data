import argparse
import os
import re
import time
import requests
from bs4 import BeautifulSoup
from datetime import datetime

BASE_URL = "https://hyattsvillemennonite.org"
LIST_URL = f"{BASE_URL}/worship/sermons/"
OUTPUT_DIR = "hyattsville_mennonite_text"
CHURCH = "Hyattsville Mennonite"


def get_soup(url, retries=3):
    headers = {"User-Agent": "Mozilla/5.0 (compatible; sermon-scraper/1.0)"}
    for attempt in range(retries):
        try:
            r = requests.get(url, headers=headers, timeout=30)
            r.raise_for_status()
            return BeautifulSoup(r.text, "html.parser")
        except Exception as e:
            if attempt == retries - 1:
                raise
            print(f"  Retry {attempt + 1} for {url}: {e}")
            time.sleep(2)


def parse_date(text):
    text = text.strip()
    for fmt in ("%B %d, %Y", "%b. %d, %Y", "%B %Y"):
        try:
            return datetime.strptime(text, fmt).strftime("%Y-%m-%d")
        except ValueError:
            pass
    return text


def scrape_sermon(url):
    soup = get_soup(url)
    header = soup.find("div", class_="post-single-sermon-header")
    if not header:
        return None

    title_tag = header.find("h2")
    title = title_tag.get_text(strip=True) if title_tag else ""

    date_tag = header.find("div", class_="date")
    date = parse_date(date_tag.get_text()) if date_tag else ""

    # Scripture is the first <strong> not containing "Speaker:"
    scripture = ""
    for strong in header.find_all("strong"):
        text = strong.get_text(strip=True)
        if "Speaker:" not in text and text:
            scripture = text
            break

    # Speaker is in an <a rel="tag"> link
    speaker_link = header.find("a", rel="tag")
    speaker = speaker_link.get_text(strip=True) if speaker_link else ""

    # Full text: all <p> tags inside the sermon wrapper, outside the header
    sermon_div = soup.find("div", class_="post-single-sermon")
    full_text = ""
    if sermon_div:
        paragraphs = []
        for p in sermon_div.find_all("p"):
            # Skip if nested inside another element that isn't the sermon div directly
            text = p.get_text(separator=" ", strip=True)
            if text:
                paragraphs.append(text)
        full_text = "\n\n".join(paragraphs)

    return {
        "church": CHURCH,
        "title": title,
        "date": date,
        "scripture": scripture,
        "speaker": speaker,
        "full_text": full_text,
        "url": url,
    }


def get_sermon_urls(list_url, max_pages=None):
    """Yield sermon URLs from paginated listing pages."""
    page_url = list_url
    visited = set()
    pages_fetched = 0
    while page_url and page_url not in visited:
        if max_pages and pages_fetched >= max_pages:
            break
        visited.add(page_url)
        pages_fetched += 1
        print(f"Fetching listing page: {page_url}")
        soup = get_soup(page_url)

        for item in soup.find_all("div", class_="post-single-sermon"):
            link = item.find("h2").find("a") if item.find("h2") else None
            if link and link.get("href"):
                yield link["href"]

        # Find next page link — match by URL pattern and "Next" in link text
        next_link = None
        for a in soup.find_all("a", href=re.compile(r"/worship/sermons/page/\d+/")):
            if "next" in a.get_text().lower():
                next_link = a
                break
        page_url = next_link["href"] if next_link else None
        if page_url:
            time.sleep(0.5)


def make_filename(data):
    date = data.get("date", "unknown")
    title = data.get("title", "untitled")
    slug = re.sub(r'[^\w\s-]', '', title).strip()
    slug = re.sub(r'[\s]+', '_', slug)
    return f"{date}_{slug}.txt"


def already_saved(filename):
    return os.path.exists(os.path.join(OUTPUT_DIR, filename))


def save_sermon(data, filename):
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    filepath = os.path.join(OUTPUT_DIR, filename)
    with open(filepath, "w", encoding="utf-8") as f:
        f.write(data.get("full_text", ""))


def main():
    parser = argparse.ArgumentParser(description="Scrape Hyattsville Mennonite sermons")
    parser.add_argument("--pages", type=int, default=None, help="Number of listing pages to fetch (default: all)")
    args = parser.parse_args()

    os.makedirs(OUTPUT_DIR, exist_ok=True)

    urls = list(get_sermon_urls(LIST_URL, max_pages=args.pages))
    print(f"\nFound {len(urls)} sermon URLs. Scraping individual pages...\n")

    for i, url in enumerate(urls, 1):
        print(f"  [{i}/{len(urls)}] Scraping: {url}")
        try:
            data = scrape_sermon(url)
            if data:
                filename = make_filename(data)
                if already_saved(filename):
                    print(f"  [{i}/{len(urls)}] Already saved: {filename}")
                    continue
                save_sermon(data, filename)
            time.sleep(0.75)
        except Exception as e:
            print(f"    ERROR: {e}")

    total = len(os.listdir(OUTPUT_DIR))
    print(f"\nDone. {total} sermons saved to {OUTPUT_DIR}/")


if __name__ == "__main__":
    main()
