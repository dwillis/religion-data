#!/usr/bin/env python3
"""
UMData People Scraper
Scrapes paginated data from umdata.org people search results
"""

import argparse
import requests
from bs4 import BeautifulSoup
import json
import time
import csv
import os
from typing import List, Dict, Optional
import re
import html
from urllib.parse import parse_qs, urlparse


class UMDataScraper:
    """Scraper for UMData.org people tables with DataTables pagination"""
    
    def __init__(self, base_url: str, delay: float = 1.0):
        """
        Initialize the scraper
        
        Args:
            base_url: The full URL of the search results page
            delay: Delay between requests in seconds (be polite!)
        """
        self.base_url = base_url
        self.delay = delay
        self.session = requests.Session()
        self.session.headers.update({
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
            'Accept-Language': 'en-US,en;q=0.9',
        })
        
    def _extract_datatables_ajax_url(self, soup: BeautifulSoup) -> Optional[str]:
        """Extract DataTables AJAX URL from page scripts"""
        scripts = soup.find_all('script')
        for script in scripts:
            if script.string and 'DataTable' in script.string:
                # Look for ajax: { url: '...' } pattern
                ajax_match = re.search(r'ajax:\s*\{\s*url:\s*["\']([^"\']+)["\']', script.string)
                if ajax_match:
                    return ajax_match.group(1)
        return None
    
    def _get_initial_page(self) -> tuple[BeautifulSoup, Optional[str], Dict]:
        """Fetch the initial page and detect AJAX endpoint"""
        try:
            response = self.session.get(self.base_url, timeout=30)
            response.raise_for_status()
            soup = BeautifulSoup(response.text, 'lxml')
            
            # Try to find AJAX URL for server-side processing
            ajax_url = self._extract_datatables_ajax_url(soup)
            
            # Extract query parameters from the URL
            parsed = urlparse(self.base_url)
            query_params = parse_qs(parsed.query)
            flat_params = {k: v[0] for k, v in query_params.items()}
            
            return soup, ajax_url, flat_params
        except requests.exceptions.RequestException as e:
            print(f"Error fetching initial page: {e}")
            raise
    
    def _scrape_ajax_data(self, ajax_url: str, params: Dict) -> Dict:
        """Fetch data from DataTables AJAX endpoint"""
        try:
            # Build the full URL
            if not ajax_url.startswith('http'):
                from urllib.parse import urljoin
                ajax_url = urljoin(self.base_url, ajax_url)
            
            response = self.session.get(ajax_url, params=params, timeout=30)
            response.raise_for_status()
            
            return response.json()
        except requests.exceptions.RequestException as e:
            print(f"Error fetching AJAX data: {e}")
            raise
    
    def _scrape_people_ajax(self, ajax_url: str, query_params: Dict) -> List[Dict]:
        """Fetch data from UMData people-ajax endpoint (returns all records at once)"""
        try:
            # Build the full URL
            if not ajax_url.startswith('http'):
                from urllib.parse import urljoin
                ajax_url = urljoin(self.base_url, ajax_url)
            
            # Add headers to indicate AJAX request
            headers = {
                'Accept': 'application/json, text/javascript, */*; q=0.01',
                'X-Requested-With': 'XMLHttpRequest',
            }
            
            print(f"Fetching data from {ajax_url}...")
            response = self.session.post(ajax_url, data=query_params, headers=headers, timeout=30)
            response.raise_for_status()
            
            # Decode HTML entities (the response is HTML-encoded JSON)
            decoded_text = html.unescape(response.text)
            
            # Parse JSON (returns array directly, not DataTables format)
            data = json.loads(decoded_text)
            
            if isinstance(data, list):
                print(f"Retrieved {len(data)} records")
                return data
            else:
                print(f"Unexpected response format: {type(data)}")
                return []
                
        except requests.exceptions.RequestException as e:
            print(f"Error fetching AJAX data: {e}")
            raise
        except json.JSONDecodeError as e:
            print(f"Error parsing JSON: {e}")
            raise
    
    def _scrape_html_table(self, soup: BeautifulSoup) -> List[Dict]:
        """Scrape data directly from HTML table (client-side pagination)"""
        rows = []
        table = soup.find('table')
        
        if not table:
            print("No table found on page")
            return rows
        
        # Get headers
        headers = []
        thead = table.find('thead')
        if thead:
            header_row = thead.find('tr')
            if header_row:
                headers = [th.get_text(strip=True) for th in header_row.find_all(['th', 'td'])]
        
        # Get data rows
        tbody = table.find('tbody')
        if tbody:
            for tr in tbody.find_all('tr'):
                cells = [td.get_text(strip=True) for td in tr.find_all(['td', 'th'])]
                if cells:  # Skip empty rows
                    row_dict = {}
                    for i, cell in enumerate(cells):
                        key = headers[i] if i < len(headers) else f"Column_{i}"
                        row_dict[key] = cell
                    rows.append(row_dict)
        
        return rows
    
    def scrape_all_pages_ajax(self, ajax_url: str, records_per_page: int = 100) -> List[Dict]:
        """
        Scrape all pages using AJAX endpoint (server-side pagination)
        
        Args:
            ajax_url: The AJAX endpoint URL
            records_per_page: Number of records to fetch per request
            
        Returns:
            List of dictionaries containing all records
        """
        all_records = []
        start = 0
        page = 1
        
        print(f"Scraping data via AJAX endpoint: {ajax_url}")
        
        while True:
            print(f"Fetching page {page} (records {start} to {start + records_per_page})...")
            
            # DataTables standard parameters
            params = {
                'draw': page,
                'start': start,
                'length': records_per_page,
            }
            
            try:
                data = self._scrape_ajax_data(ajax_url, params)
                
                # Extract records from DataTables JSON response
                if 'data' in data:
                    records = data['data']
                    all_records.extend(records)
                    
                    total_records = data.get('recordsTotal', 0)
                    print(f"  Retrieved {len(records)} records (Total: {total_records})")
                    
                    # Check if we've got all records
                    if start + len(records) >= total_records or len(records) == 0:
                        break
                else:
                    print("  No data found in response")
                    break
                
            except Exception as e:
                print(f"Error on page {page}: {e}")
                break
            
            start += records_per_page
            page += 1
            time.sleep(self.delay)  # Be polite
        
        print(f"\nTotal records scraped: {len(all_records)}")
        return all_records
    
    def scrape_all_pages_html(self, max_pages: Optional[int] = None) -> List[Dict]:
        """
        Scrape all pages by following pagination links (client-side pagination)
        
        Args:
            max_pages: Maximum number of pages to scrape (None for all)
            
        Returns:
            List of dictionaries containing all records
        """
        all_records = []
        page = 1
        current_url = self.base_url
        
        print("Scraping data via HTML pagination...")
        
        while True:
            if max_pages and page > max_pages:
                break
                
            print(f"Scraping page {page}...")
            
            try:
                response = self.session.get(current_url, timeout=30)
                response.raise_for_status()
                soup = BeautifulSoup(response.text, 'lxml')
                
                # Extract table data
                records = self._scrape_html_table(soup)
                all_records.extend(records)
                print(f"  Retrieved {len(records)} records")
                
                # Find next page link
                next_link = self._find_next_page_link(soup)
                if not next_link:
                    print("  No more pages found")
                    break
                
                # Build full URL for next page
                from urllib.parse import urljoin
                current_url = urljoin(self.base_url, next_link)
                
            except Exception as e:
                print(f"Error on page {page}: {e}")
                break
            
            page += 1
            time.sleep(self.delay)  # Be polite
        
        print(f"\nTotal records scraped: {len(all_records)}")
        return all_records
    
    def _find_next_page_link(self, soup: BeautifulSoup) -> Optional[str]:
        """Find the 'next' pagination link"""
        # Look for DataTables pagination
        pagination = soup.find('div', class_='dataTables_paginate')
        if pagination:
            next_button = pagination.find('a', class_='paginate_button next')
            if next_button and 'disabled' not in next_button.get('class', []):
                return next_button.get('href')
        
        # Fallback: look for standard pagination
        next_link = soup.find('a', string=re.compile(r'Next|»|>', re.I))
        if next_link:
            return next_link.get('href')
        
        return None
    
    def scrape(self, max_pages: Optional[int] = None) -> List[Dict]:
        """
        Main scraping method - automatically detects best approach
        
        Args:
            max_pages: Maximum pages to scrape (only for HTML pagination)
            
        Returns:
            List of dictionaries containing all records
        """
        print("Initializing scraper...")
        soup, ajax_url, query_params = self._get_initial_page()
        
        # Check if this is a people-ajax endpoint (UMData specific)
        if 'people' in self.base_url:
            ajax_url = 'https://www.umdata.org/people-ajax'
            print(f"Detected UMData people endpoint, using: {ajax_url}")
            return self._scrape_people_ajax(ajax_url, query_params)
        elif ajax_url:
            print(f"Detected AJAX endpoint: {ajax_url}")
            return self.scrape_all_pages_ajax(ajax_url)
        else:
            print("No AJAX endpoint detected, using HTML pagination")
            return self.scrape_all_pages_html(max_pages)
    
    def save_to_csv(self, records: List[Dict], filename: str):
        """Save records to CSV file"""
        if not records:
            print("No records to save")
            return
        
        # Flatten nested structures for CSV
        flattened_records = []
        for record in records:
            if isinstance(record, dict):
                flat_record = {}
                for key, value in record.items():
                    if isinstance(value, list) and value:
                        # Extract label or Name from first item
                        if isinstance(value[0], dict):
                            flat_record[key] = value[0].get('label') or value[0].get('Name') or str(value[0])
                        else:
                            flat_record[key] = str(value[0])
                    elif value is None:
                        flat_record[key] = ''
                    else:
                        flat_record[key] = value
                
                # Add URL for all people based on GCFAId
                if 'GCFAId' in flat_record and flat_record['GCFAId']:
                    flat_record['URL'] = f"https://www.umdata.org/pastor?pastor={flat_record['GCFAId']}"
                
                flattened_records.append(flat_record)
            else:
                flattened_records.append(record)
        
        # Get all unique keys across all records
        all_keys = set()
        for record in flattened_records:
            if isinstance(record, dict):
                all_keys.update(record.keys())
        
        fieldnames = sorted(all_keys) if all_keys else []
        
        with open(filename, 'w', newline='', encoding='utf-8') as f:
            if flattened_records and isinstance(flattened_records[0], dict):
                writer = csv.DictWriter(f, fieldnames=fieldnames)
                writer.writeheader()
                writer.writerows(flattened_records)
            else:
                # Handle list records
                writer = csv.writer(f)
                writer.writerows(flattened_records)
        
        print(f"Data saved to {filename}")
    
    def save_to_json(self, records: List[Dict], filename: str):
        """Save records to JSON file"""
        # Add URL to each record
        enriched_records = []
        for record in records:
            if isinstance(record, dict):
                enriched_record = record.copy()
                if 'GCFAId' in enriched_record and enriched_record['GCFAId']:
                    enriched_record['URL'] = f"https://www.umdata.org/pastor?pastor={enriched_record['GCFAId']}"
                enriched_records.append(enriched_record)
            else:
                enriched_records.append(record)
        
        with open(filename, 'w', encoding='utf-8') as f:
            json.dump(enriched_records, f, indent=2, ensure_ascii=False)
        print(f"Data saved to {filename}")


def scrape_conference(conf_id: str, conf_name: str, delay: float = 1.0) -> List[Dict]:
    """Scrape people from a single conference"""
    url = f"https://www.umdata.org/people?confType=us&lastName=&firstName=&middleName=&gcfaId=&jur=all&conf={conf_id}&historic=true"
    
    print(f"\nScraping conference: {conf_name} (ID: {conf_id})")
    print("=" * 80)
    
    scraper = UMDataScraper(url, delay=delay)
    
    try:
        records = scraper.scrape()
        return records
    except Exception as e:
        print(f"Error scraping conference {conf_name}: {e}")
        import traceback
        traceback.print_exc()
        return []


def main():
    """Main CLI function"""
    parser = argparse.ArgumentParser(
        description='Scrape UMData.org people data from conference(s)'
    )
    parser.add_argument(
        '--conference',
        type=str,
        help='Single conference ID to scrape (e.g., 3067919)'
    )
    parser.add_argument(
        '--all',
        action='store_true',
        help='Scrape all conferences from ../data/conferences.json'
    )
    parser.add_argument(
        '--delay',
        type=float,
        default=1.0,
        help='Delay between requests in seconds (default: 1.0)'
    )
    parser.add_argument(
        '--output-dir',
        type=str,
        default='./data',
        help='Output directory for data files (default: ./data)'
    )
    
    args = parser.parse_args()
    
    # Create output directory if it doesn't exist
    os.makedirs(args.output_dir, exist_ok=True)
    
    all_records = []
    
    if args.all:
        # Load conferences from JSON file
        conferences_file = './data/conferences.json'
        try:
            with open(conferences_file, 'r', encoding='utf-8') as f:
                conferences = json.load(f)
            
            print(f"Found {len(conferences)} conferences to scrape")
            
            for i, conf in enumerate(conferences, 1):
                conf_id = str(conf.get('id', ''))
                conf_name = conf.get('name', 'Unknown')
                
                if not conf_id:
                    print(f"Skipping conference {conf_name} - no ID found")
                    continue
                
                print(f"\n[{i}/{len(conferences)}]")
                records = scrape_conference(conf_id, conf_name, args.delay)
                
                if records:
                    # Add conference info to each record
                    for record in records:
                        if isinstance(record, dict):
                            record['ConferenceId'] = conf_id
                            record['ConferenceName'] = conf_name
                    all_records.extend(records)
                    print(f"  Added {len(records)} records (Total so far: {len(all_records)})")
                
                # Be extra polite between conferences
                if i < len(conferences):
                    time.sleep(args.delay * 2)
            
            # Save combined results
            if all_records:
                csv_file = os.path.join(args.output_dir, 'umdata_people_all.csv')
                json_file = os.path.join(args.output_dir, 'umdata_people_all.json')
                
                scraper = UMDataScraper("", delay=args.delay)  # Dummy scraper for save methods
                scraper.save_to_csv(all_records, csv_file)
                scraper.save_to_json(all_records, json_file)
                
                print(f"\n{'='*80}")
                print(f"Total records scraped from all conferences: {len(all_records)}")
                print(f"Saved to {csv_file} and {json_file}")
            else:
                print("\nNo records were scraped from any conference")
                
        except FileNotFoundError:
            print(f"Error: {conferences_file} not found.")
            print("Please run stats.py first to create the conferences file.")
            return
        except Exception as e:
            print(f"Error reading conferences file: {e}")
            import traceback
            traceback.print_exc()
            return
    
    elif args.conference:
        # Scrape single conference
        conf_id = args.conference
        records = scrape_conference(conf_id, f"Conference {conf_id}", args.delay)
        
        if records:
            csv_file = os.path.join(args.output_dir, f'umdata_people_{conf_id}.csv')
            json_file = os.path.join(args.output_dir, f'umdata_people_{conf_id}.json')
            
            scraper = UMDataScraper("", delay=args.delay)  # Dummy scraper for save methods
            scraper.save_to_csv(records, csv_file)
            scraper.save_to_json(records, json_file)
            
            print(f"\nSample of first record:")
            print(json.dumps(records[0], indent=2))
        else:
            print("No records were scraped")
    
    else:
        parser.print_help()
        print("\nError: Must specify either --conference ID or --all")


if __name__ == "__main__":
    main()