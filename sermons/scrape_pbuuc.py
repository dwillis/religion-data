import os
import re
import time
import requests
from bs4 import BeautifulSoup
from datetime import datetime

INDEX_URL = "http://pbuuc.org/worship/past-worship-services/archival-sermons/"
OUTPUT_DIR = "paint_branch_uu_text"
CHURCH = "Paint Branch Unitarian Universalist Church"


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
    for fmt in ("%B %d, %Y", "%b %d, %Y", "%Y-%m-%d"):
        try:
            return datetime.strptime(text, fmt).strftime("%Y-%m-%d")
        except ValueError:
            pass
    return text


def get_sermon_urls(index_url):
    soup = get_soup(index_url)
    urls = []
    for pane in soup.find_all("div", class_="su-tabs-pane"):
        for a in pane.find_all("a", href=True):
            href = a["href"]
            if href and href not in urls:
                urls.append(href)
    return urls


def scrape_sermon(url):
    soup = get_soup(url)
    article = soup.find("article")
    if not article:
        return None

    title_tag = article.find(class_="entry-title")
    title = title_tag.get_text(strip=True) if title_tag else ""

    time_tag = article.find("time")
    if time_tag:
        dt_attr = time_tag.get("datetime", "")
        if dt_attr:
            date = dt_attr[:10]
        else:
            date = parse_date(time_tag.get_text())
    else:
        date = ""

    # Speaker: from post tags (class like "tag-firstname-lastname") or entry content
    speaker = ""
    if article.get("class"):
        for cls in article["class"]:
            if cls.startswith("tag-") and cls != "tag-":
                name = cls[4:].replace("-", " ").title()
                # Filter out generic tags
                if len(name.split()) >= 2:
                    speaker = name
                    break

    content_div = article.find(class_="entry-content")
    full_text = ""
    if content_div:
        parts = []
        for tag in content_div.find_all(["p", "h2", "h3", "h4", "blockquote"]):
            text = tag.get_text(separator=" ", strip=True)
            if text:
                parts.append(text)
        full_text = "\n\n".join(parts)

    return {
        "church": CHURCH,
        "title": title,
        "date": date,
        "scripture": "",
        "speaker": speaker,
        "full_text": full_text,
        "url": url,
    }


def make_filename(data):
    date = data.get("date", "unknown")
    title = data.get("title", "untitled")
    slug = re.sub(r'[^\w\s-]', '', title).strip()
    slug = re.sub(r'[\s]+', '_', slug)
    return f"{date}_{slug}.txt"


INDEX_FILE = os.path.join(OUTPUT_DIR, "_scraped_urls.txt")


def load_scraped_urls():
    if not os.path.exists(INDEX_FILE):
        return set()
    with open(INDEX_FILE, encoding="utf-8") as f:
        return {line.strip() for line in f if line.strip()}


def mark_scraped(url):
    with open(INDEX_FILE, "a", encoding="utf-8") as f:
        f.write(url + "\n")


def save_sermon(data, filename):
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    filepath = os.path.join(OUTPUT_DIR, filename)
    if os.path.exists(filepath):
        return False
    with open(filepath, "w", encoding="utf-8") as f:
        f.write(data.get("full_text", ""))
    return True


def main():
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    scraped_urls = load_scraped_urls()

    print(f"Fetching index: {INDEX_URL}")
    urls = get_sermon_urls(INDEX_URL)
    print(f"Found {len(urls)} sermon URLs\n")

    for i, url in enumerate(urls, 1):
        if url in scraped_urls:
            print(f"  [{i}/{len(urls)}] Already saved: {url}")
            continue
        print(f"  [{i}/{len(urls)}] Scraping: {url}")
        try:
            data = scrape_sermon(url)
            if data:
                filename = make_filename(data)
                written = save_sermon(data, filename)
                if not written:
                    print(f"  [{i}/{len(urls)}] File exists, skipping: {filename}")
                mark_scraped(url)
            time.sleep(0.75)
        except Exception as e:
            print(f"    ERROR: {e}")

    total = len([f for f in os.listdir(OUTPUT_DIR) if f.endswith(".txt") and not f.startswith("_")])
    print(f"\nDone. {total} sermons saved to {OUTPUT_DIR}/")


if __name__ == "__main__":
    main()
