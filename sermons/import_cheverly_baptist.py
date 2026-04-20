import os
import re
import sqlite3
from datetime import datetime

TEXT_DIR = "cheverly_baptist_text"
DB_PATH = "sermons.db"
CHURCH = "Cheverly Baptist Church"

DATE_RE = re.compile(r"\b(\d{4})[-.](\d{2})[-.](\d{2})\b")


def parse_date_from_filename(stem):
    m = DATE_RE.search(stem)
    if not m:
        return None
    try:
        return datetime(int(m.group(1)), int(m.group(2)), int(m.group(3))).strftime("%Y-%m-%d")
    except ValueError:
        return None


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
        source_key = f"file://cheverly_baptist_text/{fname}"

        if already_imported(conn, source_key):
            print(f"  SKIP: {fname}")
            skipped += 1
            continue

        date = parse_date_from_filename(stem)

        with open(os.path.join(TEXT_DIR, fname), "r", encoding="utf-8", errors="replace") as f:
            full_text = f.read().strip()

        conn.execute(
            """INSERT INTO sermons (church, title, date, scripture, speaker, full_text, url)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (CHURCH, None, date, "", "", full_text, source_key),
        )
        conn.commit()
        imported += 1
        print(f"  + {fname}  ->  date={date or 'NULL'}")

    print(f"\nDone. Imported {imported}, skipped {skipped}.")
    conn.close()


if __name__ == "__main__":
    main()
