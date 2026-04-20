import os
import re
import sqlite3
from datetime import datetime

TEXT_DIR = "kettering_baptist_text"
DB_PATH = "sermons.db"
CHURCH = "Kettering Baptist Church"

# Date patterns to try, in order. Each yields (month, day, year) groups.
DATE_PATTERNS = [
    # MM-DD-YYYY or M-D-YYYY (with - or .)
    (re.compile(r"\b(\d{1,2})[-.](\d{1,2})[-.](\d{4})\b"), "mdy"),
    # MM.DD.YY or M.D.YY (dotted, 2-digit year)
    (re.compile(r"\b(\d{1,2})\.(\d{1,2})\.(\d{2})\b"), "mdy2"),
    # MM-DD-YY or M-D-YY (hyphen, 2-digit year)
    (re.compile(r"\b(\d{1,2})-(\d{1,2})-(\d{2})\b"), "mdy2"),
    # MMDDYY (6 consecutive digits)
    (re.compile(r"\b(\d{2})(\d{2})(\d{2})\b"), "mdy2"),
    # MMDDYYYY (8 consecutive digits)
    (re.compile(r"\b(\d{2})(\d{2})(\d{4})\b"), "mdy"),
]


def two_digit_year(y):
    y = int(y)
    # Treat 00-49 as 2000s, 50-99 as 1900s
    return 2000 + y if y < 50 else 1900 + y


def parse_date_from_filename(stem):
    for pattern, kind in DATE_PATTERNS:
        m = pattern.search(stem)
        if not m:
            continue
        try:
            mm, dd, yy = m.group(1), m.group(2), m.group(3)
            year = int(yy) if kind == "mdy" else two_digit_year(yy)
            dt = datetime(year, int(mm), int(dd))
            return dt.strftime("%Y-%m-%d"), m.span()
        except ValueError:
            continue
    return None, None


def extract_title(stem, date_span):
    """If a date was found, return None (no real title). Otherwise derive
    a readable title from the filename."""
    if date_span is not None:
        return None

    # Strip common church prefixes
    cleaned = stem
    for prefix in ("Kettering_Baptist_-_", "Kettering_Baptist_", "Kettering_Bap._", "Kettering_Bap_"):
        if cleaned.startswith(prefix):
            cleaned = cleaned[len(prefix):]
            break

    # Replace underscores/hyphens with spaces
    title = cleaned.replace("_", " ").replace("-", " ").strip()
    title = re.sub(r"\s+", " ", title)
    return title or None


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


def already_imported(conn, source_key):
    return conn.execute("SELECT 1 FROM sermons WHERE url = ?", (source_key,)).fetchone() is not None


def main():
    conn = sqlite3.connect(DB_PATH)
    init_db(conn)

    files = sorted(f for f in os.listdir(TEXT_DIR) if f.endswith(".txt"))
    print(f"Found {len(files)} text files\n")

    imported = skipped = 0
    for fname in files:
        stem = os.path.splitext(fname)[0]
        source_key = f"file://kettering_baptist_text/{fname}"

        if already_imported(conn, source_key):
            print(f"  SKIP (already in db): {fname}")
            skipped += 1
            continue

        date, date_span = parse_date_from_filename(stem)
        title = extract_title(stem, date_span)

        with open(os.path.join(TEXT_DIR, fname), "r", encoding="utf-8", errors="replace") as f:
            full_text = f.read().strip()

        conn.execute(
            """INSERT INTO sermons (church, title, date, scripture, speaker, full_text, url)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (CHURCH, title, date, "", "", full_text, source_key),
        )
        conn.commit()
        imported += 1
        print(f"  + {fname}  ->  date={date or 'NULL'}, title={title or 'NULL'}")

    print(f"\nDone. Imported {imported}, skipped {skipped}.")
    conn.close()


if __name__ == "__main__":
    main()
