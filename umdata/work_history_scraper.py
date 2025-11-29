#!/usr/bin/env python3
"""
UMData Work History Scraper
Scrapes work history from individual pastor pages
"""

import requests
from bs4 import BeautifulSoup
import json
import time
import csv
from typing import List, Dict, Optional
import re


class WorkHistoryScraper:
    """Scraper for UMData.org pastor work history pages"""
    
    def __init__(self, delay: float = 1.0):
        """
        Initialize the scraper
        
        Args:
            delay: Delay between requests in seconds (be polite!)
        """
        self.delay = delay
        self.session = requests.Session()
        self.session.headers.update({
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
            'Accept-Language': 'en-US,en;q=0.9',
        })
    
    def scrape_work_history(self, pastor_url: str) -> Dict:
        """
        Scrape work history from a pastor's page
        
        Args:
            pastor_url: URL to the pastor's page (e.g., https://www.umdata.org/pastor?pastor=0124740)
            
        Returns:
            Dictionary containing pastor info and work history
        """
        try:
            response = self.session.get(pastor_url, timeout=30)
            response.raise_for_status()
            soup = BeautifulSoup(response.text, 'lxml')
            
            # Extract GCFAId from URL
            gcfa_match = re.search(r'pastor=(\d+)', pastor_url)
            gcfa_id = gcfa_match.group(1) if gcfa_match else None
            
            # Extract pastor name from page
            pastor_name = self._extract_pastor_name(soup)
            
            # Extract work history table
            work_history = self._extract_work_history_table(soup)
            
            return {
                'GCFAId': gcfa_id,
                'URL': pastor_url,
                'Name': pastor_name,
                'WorkHistory': work_history
            }
            
        except requests.exceptions.RequestException as e:
            print(f"Error fetching {pastor_url}: {e}")
            return {
                'GCFAId': gcfa_id,
                'URL': pastor_url,
                'Name': None,
                'WorkHistory': [],
                'Error': str(e)
            }
    
    def _extract_pastor_name(self, soup: BeautifulSoup) -> Optional[str]:
        """Extract the pastor's name from the page"""
        # Look for the main heading or title
        h1 = soup.find('h1')
        if h1:
            return h1.get_text(strip=True)
        
        # Alternative: look for a specific element with the name
        name_elem = soup.find('div', class_='pastor-name')
        if name_elem:
            return name_elem.get_text(strip=True)
        
        return None
    
    def _parse_dates(self, date_string: str) -> tuple[Optional[str], Optional[str]]:
        """
        Parse date range string into start and end dates
        
        Args:
            date_string: Date string like "7/1/2018 -Present" or "1/1/2015 - 6/30/2018"
            
        Returns:
            Tuple of (start_date, end_date) where end_date is None if "Present"
        """
        if not date_string:
            return None, None
        
        # Split on dash or hyphen
        parts = re.split(r'\s*-\s*', date_string)
        
        if len(parts) == 1:
            # Single date
            return parts[0].strip(), None
        elif len(parts) == 2:
            start_date = parts[0].strip()
            end_date = parts[1].strip()
            
            # Check if end date is "Present" (case insensitive)
            if end_date.lower() == 'present':
                end_date = None
            
            return start_date, end_date
        else:
            # Unexpected format, return original
            return date_string, None
    
    def _extract_work_history_table(self, soup: BeautifulSoup) -> List[Dict]:
        """Extract work history from the table on the page"""
        work_history = []
        
        # Find the work history table
        table = soup.find('table')
        if not table:
            # Try to find any table with relevant headers
            tables = soup.find_all('table')
            for t in tables:
                thead = t.find('thead')
                if thead and ('appointment' in thead.get_text().lower() or 'church' in thead.get_text().lower()):
                    table = t
                    break
        
        if not table:
            return work_history
        
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
            rows = tbody.find_all('tr')
        else:
            # If no tbody, get all rows except the first (header)
            all_rows = table.find_all('tr')
            rows = all_rows[1:] if len(all_rows) > 1 else []
        
        for tr in rows:
            cells = tr.find_all(['td', 'th'])
            if not cells:
                continue
            
            row_dict = {}
            
            # Process each cell
            for i, cell in enumerate(cells):
                header_name = headers[i] if i < len(headers) else f"Column_{i}"
                
                # Check for links in the cell (View Charts column)
                link = cell.find('a')
                if link and link.get('href'):
                    href = link.get('href')
                    # Make absolute URL if relative
                    if href and not href.startswith('http'):
                        href = f"https://www.umdata.org{href}"
                    row_dict[f"{header_name}_URL"] = href
                
                # Get the text content
                text = cell.get_text(strip=True)
                
                # Skip adding the text for "View Charts" column (keep only the URL)
                if header_name != 'View Charts':
                    row_dict[header_name] = text
                
                # Split dates if this is the Dates column
                if header_name == 'Dates' and text:
                    start_date, end_date = self._parse_dates(text)
                    row_dict['StartDate'] = start_date
                    row_dict['EndDate'] = end_date
            
            if row_dict:  # Only add non-empty rows
                work_history.append(row_dict)
        
        return work_history
    
    def scrape_multiple_pastors(self, pastor_urls: List[str]) -> List[Dict]:
        """
        Scrape work history for multiple pastors
        
        Args:
            pastor_urls: List of pastor page URLs
            
        Returns:
            List of dictionaries containing pastor info and work history
        """
        all_results = []
        
        for i, url in enumerate(pastor_urls, 1):
            print(f"Scraping {i}/{len(pastor_urls)}: {url}")
            result = self.scrape_work_history(url)
            all_results.append(result)
            
            if i < len(pastor_urls):
                time.sleep(self.delay)
        
        return all_results
    
    def scrape_from_people_json(self, people_json_file: str, max_records: Optional[int] = None) -> List[Dict]:
        """
        Scrape work history from URLs in people JSON file
        
        Args:
            people_json_file: Path to the JSON file with people data
            max_records: Maximum number of records to process (None for all)
            
        Returns:
            List of dictionaries containing work history data
        """
        print(f"Loading people data from {people_json_file}...")
        with open(people_json_file, 'r', encoding='utf-8') as f:
            people_data = json.load(f)
        
        # Extract URLs
        urls = []
        for person in people_data:
            if 'URL' in person and person['URL']:
                urls.append(person['URL'])
        
        if max_records:
            urls = urls[:max_records]
        
        print(f"Found {len(urls)} pastor URLs to scrape")
        return self.scrape_multiple_pastors(urls)
    
    def save_to_json(self, results: List[Dict], filename: str):
        """Save results to JSON file"""
        with open(filename, 'w', encoding='utf-8') as f:
            json.dump(results, f, indent=2, ensure_ascii=False)
        print(f"Data saved to {filename}")
    
    def save_to_csv(self, results: List[Dict], filename: str):
        """Save results to CSV file (flattened work history)"""
        if not results:
            print("No results to save")
            return
        
        # Flatten the data - one row per work history entry
        flattened_rows = []
        for result in results:
            gcfa_id = result.get('GCFAId', '')
            url = result.get('URL', '')
            name = result.get('Name', '')
            
            work_history = result.get('WorkHistory', [])
            if work_history:
                for entry in work_history:
                    row = {
                        'GCFAId': gcfa_id,
                        'PastorURL': url,
                        'Name': name,
                        **entry
                    }
                    flattened_rows.append(row)
            else:
                # Include record even if no work history
                flattened_rows.append({
                    'GCFAId': gcfa_id,
                    'PastorURL': url,
                    'Name': name
                })
        
        if not flattened_rows:
            print("No data to save")
            return
        
        # Get all unique keys
        all_keys = set()
        for row in flattened_rows:
            all_keys.update(row.keys())
        
        # Determine field order (put main fields first)
        main_fields = ['GCFAId', 'PastorURL', 'Name']
        other_fields = sorted([k for k in all_keys if k not in main_fields])
        fieldnames = main_fields + other_fields
        
        with open(filename, 'w', newline='', encoding='utf-8') as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()
            writer.writerows(flattened_rows)
        
        print(f"Data saved to {filename}")


def main():
    """Example usage"""
    # Example: scrape a single pastor
    scraper = WorkHistoryScraper(delay=1.0)
    
    # Test with one URL
    test_url = "https://www.umdata.org/pastor?pastor=0124740"
    print(f"Testing with: {test_url}\n")
    
    result = scraper.scrape_work_history(test_url)
    print(f"\nResult for {result.get('Name')}:")
    print(f"  GCFAId: {result.get('GCFAId')}")
    print(f"  Work History Entries: {len(result.get('WorkHistory', []))}")
    
    if result.get('WorkHistory'):
        print(f"\nFirst work history entry:")
        print(json.dumps(result['WorkHistory'][0], indent=2))
    
    # To scrape all pastors from the people JSON file:
    # Uncomment the following lines:
    #
    # print("\n\nScraping all pastors from ../data/umdata_people.json...")
    # all_results = scraper.scrape_from_people_json('../data/umdata_people.json')
    # scraper.save_to_json(all_results, '../data/work_history.json')
    # scraper.save_to_csv(all_results, '../data/work_history.csv')


if __name__ == "__main__":
    main()
