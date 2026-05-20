#!/usr/bin/env python3
"""
Scraper for ATS (Association of Theological Schools) Annual Data Tables.

Fetches all available PDF links from https://www.ats.edu/Annual-Data-Tables,
extracts tables from each PDF using natural-pdf, and writes one CSV per table
into a per-PDF subdirectory under the output directory.

Output structure:
    data/ats/
        annual_2024-25/
            page_4_table_0.csv
            page_4_table_1.csv
            ...
        annual_2023-24/
            ...

Usage:
    uv run python scrapers/ats/scraper.py
    uv run python scrapers/ats/scraper.py --section factbook
    uv run python scrapers/ats/scraper.py --section all --delay 2.0
    uv run python scrapers/ats/scraper.py --no-skip   # re-process existing
"""

import argparse
import csv
import time
from pathlib import Path

import requests
from bs4 import BeautifulSoup
from natural_pdf import PDF

BASE_URL = "https://www.ats.edu"
INDEX_URL = f"{BASE_URL}/Annual-Data-Tables"
DEFAULT_OUTPUT_DIR = Path(__file__).parent.parent.parent / "data" / "ats"
DEFAULT_DELAY = 1.0


def get_pdf_links(section: str = "annual") -> list[dict]:
    """
    Fetch the ATS index page and return PDF links.

    Args:
        section: "annual", "factbook", or "all"

    Returns:
        List of dicts with keys: label, url, section
    """
    resp = requests.get(INDEX_URL, timeout=30)
    resp.raise_for_status()
    soup = BeautifulSoup(resp.text, "lxml")

    links = []
    seen_urls: set[str] = set()
    current_section = None

    for heading in soup.find_all(["h2", "h3"]):
        text = heading.get_text(strip=True)
        if "Annual Data Tables" in text:
            current_section = "annual"
        elif "Fact Book" in text:
            current_section = "factbook"
        else:
            continue

        if section != "all" and current_section != section:
            continue

        table = heading.find_next_sibling("table") or heading.find_next("table")
        if not table:
            continue

        for a in table.find_all("a", href=True):
            href = a["href"]
            if not href.lower().endswith(".pdf"):
                continue
            if href.startswith("/"):
                href = BASE_URL + href
            if href in seen_urls:
                continue
            seen_urls.add(href)
            label = a.get_text(strip=True)
            if label:
                links.append({"label": label, "url": href, "section": current_section})

    return links


def _strip_numeric_commas(value: str) -> str:
    """Remove thousands-separator commas from numeric strings (e.g. '1,012' → '1012')."""
    stripped = value.replace(",", "")
    try:
        float(stripped)
        return stripped
    except ValueError:
        return value


def rows_to_records(rows: list[list]) -> list[dict]:
    """
    Convert a list-of-lists table into a list of dicts using the first row as headers.

    Empty or None header cells are replaced with a positional fallback (col_0, col_1, …).
    Rows that are entirely empty are skipped.
    """
    if not rows:
        return []

    raw_headers = [str(h).strip() if h else "" for h in rows[0]]
    seen: dict[str, int] = {}
    headers: list[str] = []
    for i, h in enumerate(raw_headers):
        key = h if h else f"col_{i}"
        if key in seen:
            seen[key] += 1
            key = f"{key}_{seen[key]}"
        else:
            seen[key] = 0
        headers.append(key)

    records = []
    for row in rows[1:]:
        padded = list(row) + [None] * (len(headers) - len(row))
        record = {headers[i]: (_strip_numeric_commas(str(v).strip()) if v is not None else "")
                  for i, v in enumerate(padded)}
        if any(v for v in record.values()):
            records.append(record)
    return records


def _looks_like_axis_label(text: str) -> bool:
    """Return True if text looks like rotated chart axis labels (single chars per line)."""
    lines = [l.strip() for l in text.split("\n") if l.strip()]
    if len(lines) < 4:
        return False
    return sum(1 for l in lines if len(l) <= 2) / len(lines) > 0.6


def is_data_table(rows: list[list]) -> bool:
    """
    Return True only if rows look like a genuine data table.

    Rejects:
    - Fewer than 2 columns
    - Fewer than 3 rows total (header + at least 2 data rows)
    - Headers containing "GRAPH"
    - Headers where any cell contains 3+ newlines (chart legend strings)
    - Tables where most cells contain rotated chart-axis text
    """
    if not rows or len(rows) < 3:
        return False

    max_cols = max(len(row) for row in rows)
    if max_cols < 2:
        return False

    header_text = " ".join(str(c) for c in rows[0] if c)
    if "GRAPH" in header_text.upper():
        return False

    # Reject if any header or data cell looks like a multi-item chart legend
    for row in rows:
        for cell in row:
            if cell and str(cell).count("\n") >= 3:
                return False

    all_cells = [str(c) for row in rows for c in row if c]
    if not all_cells:
        return False
    axis_count = sum(1 for c in all_cells if _looks_like_axis_label(c))
    if axis_count / len(all_cells) > 0.25:
        return False

    return True


def extract_tables_from_pdf(url: str) -> list[dict]:
    """
    Download a PDF and extract genuine data tables from every page.

    Returns:
        List of dicts with keys: page (1-based int), table_index (int),
        headers (list of str), data (list of dicts).
    """
    results = []
    with PDF(url) as pdf:
        for page_num, page in enumerate(pdf.pages, start=1):
            tables = page.extract_tables()
            for table_idx, table in enumerate(tables):
                rows = [list(row) for row in table]
                if not is_data_table(rows):
                    continue
                records = rows_to_records(rows)
                if len(records) >= 2:
                    results.append(
                        {
                            "page": page_num,
                            "table_index": table_idx,
                            "headers": list(records[0].keys()),
                            "data": records,
                        }
                    )
    return results


def write_table_csv(out_path: Path, headers: list[str], data: list[dict]) -> None:
    """Write a single table to a CSV file."""
    with out_path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=headers)
        writer.writeheader()
        writer.writerows(data)


def slug_from_label(label: str) -> str:
    """Convert a year label like '2024–25' to a lowercase filename-safe slug."""
    return label.replace("\u2013", "-").replace("\u2014", "-").replace("/", "-").strip().lower()


def start_year(label: str) -> int:
    """Extract the start year from a label like '2010–11' or '2010-11'."""
    digits = "".join(c for c in label if c.isdigit())
    return int(digits[:4]) if len(digits) >= 4 else 0


def scrape(
    section: str = "annual",
    output_dir: Path = DEFAULT_OUTPUT_DIR,
    delay: float = DEFAULT_DELAY,
    skip_existing: bool = True,
    min_year: int = 2010,
) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)

    links = get_pdf_links(section)
    links = [e for e in links if start_year(e["label"]) >= min_year]
    print(f"Found {len(links)} PDF(s) to process (from {min_year} onwards).")

    for entry in links:
        slug = slug_from_label(entry["label"])
        pdf_dir = output_dir / f"{entry['section']}_{slug}"

        if skip_existing and pdf_dir.exists():
            print(f"  Skipping {entry['label']} (directory already exists)")
            continue

        print(f"  Processing {entry['label']} — {entry['url']}")
        try:
            tables = extract_tables_from_pdf(entry["url"])
            if not tables:
                print(f"    No tables found.")
                time.sleep(delay)
                continue

            pdf_dir.mkdir(parents=True, exist_ok=True)
            for t in tables:
                filename = f"page_{t['page']}_table_{t['table_index']}.csv"
                write_table_csv(pdf_dir / filename, t["headers"], t["data"])

            print(f"    Wrote {len(tables)} CSV(s) → {pdf_dir.name}/")
        except Exception as exc:
            print(f"    ERROR processing {entry['label']}: {exc}")

        time.sleep(delay)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Extract tables from ATS Annual Data Tables PDFs into JSON files."
    )
    parser.add_argument(
        "--section",
        choices=["annual", "factbook", "all"],
        default="annual",
        help="Which section to scrape (default: annual)",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=DEFAULT_OUTPUT_DIR,
        help=f"Output directory (default: {DEFAULT_OUTPUT_DIR})",
    )
    parser.add_argument(
        "--delay",
        type=float,
        default=DEFAULT_DELAY,
        help="Seconds to wait between PDFs (default: 1.0)",
    )
    parser.add_argument(
        "--no-skip",
        action="store_true",
        help="Re-process PDFs even if the output file already exists",
    )
    parser.add_argument(
        "--min-year",
        type=int,
        default=2010,
        help="Skip PDFs with a start year before this value (default: 2010)",
    )
    args = parser.parse_args()

    scrape(
        section=args.section,
        output_dir=args.output_dir,
        delay=args.delay,
        skip_existing=not args.no_skip,
        min_year=args.min_year,
    )


if __name__ == "__main__":
    main()
