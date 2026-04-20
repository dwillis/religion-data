import sqlite3
import time
import requests
from bs4 import BeautifulSoup
from datetime import datetime

INDEX_URL = "http://pbuuc.org/worship/past-worship-services/archival-sermons/"
DB_PATH = "sermons.db"
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


def init_db(conn):
    conn.execute("""
        CREATE TABLE IF NOT EXISTS sermons (
            id        INTEGER PRIMARY KEY AUTOINCREMENT,
            church    TEXT,
            title     TEXT,
            date      DATE,
            scripture TEXT,
            speaker   TEXT,
            full_text TEXT,
            url       TEXT UNIQUE
        )
    """)
    conn.commit()


def already_scraped(conn, url):
    return conn.execute("SELECT 1 FROM sermons WHERE url = ?", (url,)).fetchone() is not None


def save_sermon(conn, data):
    conn.execute(
        """INSERT OR IGNORE INTO sermons
           (church, title, date, scripture, speaker, full_text, url)
           VALUES (:church, :title, :date, :scripture, :speaker, :full_text, :url)""",
        data,
    )
    conn.commit()


def main():
    conn = sqlite3.connect(DB_PATH)
    init_db(conn)

    print(f"Fetching index: {INDEX_URL}")
    urls = get_sermon_urls(INDEX_URL)
    print(f"Found {len(urls)} sermon URLs\n")

    for i, url in enumerate(urls, 1):
        if already_scraped(conn, url):
            print(f"  [{i}/{len(urls)}] Already saved: {url}")
            continue
        print(f"  [{i}/{len(urls)}] Scraping: {url}")
        try:
            data = scrape_sermon(url)
            if data:
                save_sermon(conn, data)
            time.sleep(0.75)
        except Exception as e:
            print(f"    ERROR: {e}")

    conn.close()
    total = conn.execute("SELECT COUNT(*) FROM sermons WHERE church = ?", (CHURCH,)).fetchone()
    print(f"\nDone. {total[0] if total else '?'} Paint Branch sermons in database.")


if __name__ == "__main__":
    main()
