#!/usr/bin/env python3
"""
UMData Work History Scraper
Scrapes work history from individual pastor pages with checkpoint/resume support.

Usage:
    # Scrape all (resumable — safe to ctrl-C and restart):
    uv run python umdata/work_history_scraper.py

    # Test with a few records:
    uv run python umdata/work_history_scraper.py --limit 10

    # Merge per-person files into combined JSON/CSV (no scraping):
    uv run python umdata/work_history_scraper.py --merge
"""

import argparse
import requests
from bs4 import BeautifulSoup
import json
import time
import csv
import os
import glob
from typing import List, Dict, Optional
import re


class WorkHistoryScraper:
    """Scraper for UMData.org pastor work history pages"""

    def __init__(self, delay: float = 0.5):
        self.delay = delay
        self.session = requests.Session()
        self.session.headers.update({
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
            'Accept-Language': 'en-US,en;q=0.9',
        })

    def scrape_work_history(self, pastor_url: str) -> Dict:
        """Scrape work history from a pastor's page."""
        gcfa_match = re.search(r'pastor=(\d+)', pastor_url)
        gcfa_id = gcfa_match.group(1) if gcfa_match else None

        try:
            response = self.session.get(pastor_url, timeout=30)
            response.raise_for_status()
            soup = BeautifulSoup(response.text, 'lxml')

            return {
                'GCFAId': gcfa_id,
                'URL': pastor_url,
                'Name': self._extract_pastor_name(soup),
                'WorkHistory': self._extract_work_history_table(soup)
            }

        except requests.exceptions.RequestException as e:
            return {
                'GCFAId': gcfa_id,
                'URL': pastor_url,
                'Name': None,
                'WorkHistory': [],
                'Error': str(e)
            }

    def _extract_pastor_name(self, soup: BeautifulSoup) -> Optional[str]:
        h1 = soup.find('h1')
        if h1:
            name = h1.get_text(separator=' ', strip=True)
            return ' '.join(name.split())
        return None

    def _convert_to_iso_date(self, date_str: str) -> Optional[str]:
        if not date_str:
            return None
        try:
            parts = date_str.split('/')
            if len(parts) == 3:
                month, day, year = parts
                return f"{year.strip()}-{month.strip().zfill(2)}-{day.strip().zfill(2)}"
        except (ValueError, AttributeError):
            pass
        return date_str

    def _parse_dates(self, date_string: str) -> tuple[Optional[str], Optional[str]]:
        if not date_string:
            return None, None
        parts = re.split(r'\s*-\s*', date_string)
        if len(parts) == 1:
            return self._convert_to_iso_date(parts[0].strip()), None
        elif len(parts) == 2:
            start_date = parts[0].strip()
            end_date = parts[1].strip()
            if end_date.lower() == 'present':
                return self._convert_to_iso_date(start_date), None
            return self._convert_to_iso_date(start_date), self._convert_to_iso_date(end_date)
        else:
            return date_string, None

    def _extract_work_history_table(self, soup: BeautifulSoup) -> List[Dict]:
        work_history = []

        table = soup.find('table')
        if not table:
            tables = soup.find_all('table')
            for t in tables:
                thead = t.find('thead')
                if thead and ('appointment' in thead.get_text().lower() or 'church' in thead.get_text().lower()):
                    table = t
                    break

        if not table:
            return work_history

        headers = []
        thead = table.find('thead')
        if thead:
            header_row = thead.find('tr')
            if header_row:
                headers = [th.get_text(strip=True) for th in header_row.find_all(['th', 'td'])]

        tbody = table.find('tbody')
        if tbody:
            rows = tbody.find_all('tr')
        else:
            all_rows = table.find_all('tr')
            rows = all_rows[1:] if len(all_rows) > 1 else []

        for tr in rows:
            cells = tr.find_all(['td', 'th'])
            if not cells:
                continue

            row_dict = {}
            for i, cell in enumerate(cells):
                header_name = headers[i] if i < len(headers) else f"Column_{i}"

                link = cell.find('a')
                if link and link.get('href'):
                    href = link.get('href')
                    if href and not href.startswith('http'):
                        href = f"https://www.umdata.org{href}"
                    row_dict[f"{header_name}_URL"] = href

                text = cell.get_text(strip=True)
                if header_name != 'View Charts':
                    row_dict[header_name] = text

                if header_name == 'Dates' and text:
                    start_date, end_date = self._parse_dates(text)
                    row_dict['StartDate'] = start_date
                    row_dict['EndDate'] = end_date

            if row_dict:
                work_history.append(row_dict)

        return work_history

    def scrape_all_work_histories(self, people_file: str, output_dir: str,
                                  limit: Optional[int] = None):
        """
        Scrape work histories for all people, with checkpoint/resume.

        Each person's result is saved to {output_dir}/{gcfa_id}.json immediately.
        On restart, already-scraped IDs are skipped.
        """
        # Load people
        print(f"Loading people from {people_file}...")
        with open(people_file, 'r', encoding='utf-8') as f:
            people = json.load(f)

        # Build list of (gcfa_id, url) to scrape
        to_scrape = []
        for person in people:
            gcfa_id = person.get('GCFAId')
            url = person.get('URL')
            if gcfa_id and url:
                to_scrape.append((gcfa_id, url))

        if limit:
            to_scrape = to_scrape[:limit]

        total = len(to_scrape)
        print(f"Total people to process: {total}")

        # Check which are already done
        os.makedirs(output_dir, exist_ok=True)
        done = set()
        for path in glob.glob(os.path.join(output_dir, '*.json')):
            basename = os.path.splitext(os.path.basename(path))[0]
            # Skip the merged output files
            if basename in ('work_histories',):
                continue
            done.add(basename)

        remaining = [(gid, url) for gid, url in to_scrape if gid not in done]
        print(f"Already scraped: {len(done)}, remaining: {len(remaining)}")

        if not remaining:
            print("Nothing to scrape — all done!")
            return

        errors = 0
        for i, (gcfa_id, url) in enumerate(remaining, 1):
            result = self.scrape_work_history(url)

            # Write immediately
            out_path = os.path.join(output_dir, f"{gcfa_id}.json")
            with open(out_path, 'w', encoding='utf-8') as f:
                json.dump(result, f, ensure_ascii=False)

            if 'Error' in result:
                errors += 1

            if i % 100 == 0 or i == len(remaining):
                done_total = len(done) + i
                entries = len(result.get('WorkHistory', []))
                print(f"  [{done_total}/{total}] {gcfa_id} {result.get('Name', '?')}: "
                      f"{entries} entries  (errors so far: {errors})")

            if i < len(remaining):
                time.sleep(self.delay)

        print(f"\nScraping complete. Total: {len(done) + len(remaining)}, errors: {errors}")

    @staticmethod
    def merge(output_dir: str):
        """Merge per-person JSON files into combined work_histories.json and .csv."""
        files = sorted(glob.glob(os.path.join(output_dir, '*.json')))
        files = [f for f in files if os.path.basename(f) != 'work_histories.json']

        print(f"Merging {len(files)} files from {output_dir}...")

        all_results = []
        for path in files:
            with open(path, 'r', encoding='utf-8') as f:
                all_results.append(json.load(f))

        # Save combined JSON
        json_path = os.path.join(output_dir, 'work_histories.json')
        with open(json_path, 'w', encoding='utf-8') as f:
            json.dump(all_results, f, indent=2, ensure_ascii=False)
        print(f"Saved {json_path}")

        # Save flattened CSV
        csv_path = os.path.join(output_dir, 'work_histories.csv')
        flattened = []
        for result in all_results:
            gcfa_id = result.get('GCFAId', '')
            url = result.get('URL', '')
            name = result.get('Name', '')
            work_history = result.get('WorkHistory', [])
            if work_history:
                for entry in work_history:
                    flattened.append({'GCFAId': gcfa_id, 'PastorURL': url, 'Name': name, **entry})
            else:
                flattened.append({'GCFAId': gcfa_id, 'PastorURL': url, 'Name': name})

        if flattened:
            all_keys = set()
            for row in flattened:
                all_keys.update(row.keys())
            main_fields = ['GCFAId', 'PastorURL', 'Name']
            fieldnames = main_fields + sorted(k for k in all_keys if k not in main_fields)

            with open(csv_path, 'w', newline='', encoding='utf-8') as f:
                writer = csv.DictWriter(f, fieldnames=fieldnames)
                writer.writeheader()
                writer.writerows(flattened)
            print(f"Saved {csv_path}")

        total_entries = sum(len(r.get('WorkHistory', [])) for r in all_results)
        print(f"People: {len(all_results)}, work history entries: {total_entries}")


def main():
    parser = argparse.ArgumentParser(
        description='Scrape work history from UMData.org pastor pages (resumable)'
    )
    parser.add_argument(
        '--input', type=str, default='./data/umdata_people.json',
        help='Input JSON file with people data (default: ./data/umdata_people.json)'
    )
    parser.add_argument(
        '--output-dir', type=str, default='./data/work_histories',
        help='Output directory for per-person JSON files (default: ./data/work_histories/)'
    )
    parser.add_argument(
        '--delay', type=float, default=0.5,
        help='Delay between requests in seconds (default: 0.5)'
    )
    parser.add_argument(
        '--limit', type=int, default=None,
        help='Limit number of records to process (for testing)'
    )
    parser.add_argument(
        '--merge', action='store_true',
        help='Skip scraping, just merge per-person files into combined output'
    )

    args = parser.parse_args()

    if args.merge:
        WorkHistoryScraper.merge(args.output_dir)
        return

    if not os.path.exists(args.input):
        print(f"Error: {args.input} not found. Run people_scraper.py first.")
        return

    scraper = WorkHistoryScraper(delay=args.delay)
    scraper.scrape_all_work_histories(args.input, args.output_dir, limit=args.limit)

    # Auto-merge on completion
    print()
    WorkHistoryScraper.merge(args.output_dir)


if __name__ == "__main__":
    main()
