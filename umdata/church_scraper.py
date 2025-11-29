#!/usr/bin/env python3
"""
UMData Church Scraper
Scrapes church details from individual church pages
"""

import requests
from bs4 import BeautifulSoup
import json
import time
import csv
from typing import List, Dict, Optional
import re


class ChurchScraper:
    """Scraper for UMData.org church pages"""
    
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
    
    def scrape_church_details(self, church_url: str) -> Dict:
        """
        Scrape church details from a church page
        
        Args:
            church_url: URL to the church page (e.g., https://www.umdata.org/church?church=950642)
            
        Returns:
            Dictionary containing church info and quick facts
        """
        try:
            response = self.session.get(church_url, timeout=30)
            response.raise_for_status()
            soup = BeautifulSoup(response.text, 'lxml')
            
            # Extract church ID from URL
            church_match = re.search(r'church=(\d+)', church_url)
            church_id = church_match.group(1) if church_match else None
            
            # Extract church name from page
            church_name = self._extract_church_name(soup)
            
            # Extract quick facts year
            quick_facts_year = self._extract_quick_facts_year(soup)
            
            # Extract quick facts
            quick_facts = self._extract_quick_facts(soup)
            
            # Check if HCI data is available
            hci_available = self._check_hci_available(soup)
            
            result = {
                'ChurchId': church_id,
                'URL': church_url,
                'ChurchName': church_name,
                'QuickFactsYear': quick_facts_year,
                'HCI_DataAvailable': hci_available,
                **quick_facts
            }
            
            return result
            
        except requests.exceptions.RequestException as e:
            print(f"Error fetching {church_url}: {e}")
            return {
                'ChurchId': church_id,
                'URL': church_url,
                'ChurchName': None,
                'Error': str(e)
            }
    
    def _extract_church_name(self, soup: BeautifulSoup) -> Optional[str]:
        """Extract the church name from the page"""
        # Look for the main heading
        h1 = soup.find('h1')
        if h1:
            name = h1.get_text(strip=True)
            # Split on newline and take only the first part
            if '\n' in name:
                name = name.split('\n')[0].strip()
            return name
        
        # Alternative: look for title tag
        title = soup.find('title')
        if title:
            title_text = title.get_text(strip=True)
            # Remove " - UMData" suffix if present
            return title_text.replace(' - UMData', '').strip()
        
        return None
    
    def _extract_quick_facts_year(self, soup: BeautifulSoup) -> Optional[str]:
        """Extract the year from Quick Facts header"""
        quick_facts_header = soup.find('h3', string=re.compile(r'Quick Facts', re.I))
        if quick_facts_header:
            text = quick_facts_header.get_text(strip=True)
            # Extract year in parentheses
            year_match = re.search(r'\((\d{4})\)', text)
            if year_match:
                return year_match.group(1)
        return None
    
    def _extract_quick_facts(self, soup: BeautifulSoup) -> Dict:
        """Extract quick facts from the page"""
        facts = {}
        
        # Find the Quick Facts card
        quick_facts_header = soup.find('h3', string=re.compile(r'Quick Facts', re.I))
        if not quick_facts_header:
            return facts
        
        # Get the card body containing the facts
        card = quick_facts_header.find_parent('div', class_='card')
        if not card:
            return facts
        
        card_body = card.find('div', class_='card-body')
        if not card_body:
            return facts
        
        # Find all list items with facts
        list_items = card_body.find_all('li', class_='list-group-item')
        
        for item in list_items:
            # Get the label (everything except the span)
            span = item.find('span')
            if span:
                # Get label text by removing the span content
                label = item.get_text(strip=True).replace(span.get_text(strip=True), '').strip()
                value = span.get_text(strip=True)
                
                # Clean up the label
                label = label.strip()
                
                # Convert value to appropriate type
                # Remove $ and commas for numeric values
                if value.startswith('$'):
                    value = value.replace('$', '').replace(',', '')
                elif ',' in value:
                    value = value.replace(',', '')
                
                # Store the fact
                if label and value:
                    facts[label] = value
        
        return facts
    
    def _check_hci_available(self, soup: BeautifulSoup) -> bool:
        """Check if Healthy Church Initiative data is available"""
        # The HCI button triggers a client-side Excel export of data already in the HTML
        # Check if the hci-download table exists
        hci_table = soup.find('table', id='hci-download')
        return hci_table is not None
    
    def scrape_multiple_churches(self, church_urls: List[str]) -> List[Dict]:
        """
        Scrape details for multiple churches
        
        Args:
            church_urls: List of church page URLs
            
        Returns:
            List of dictionaries containing church info
        """
        all_results = []
        
        for i, url in enumerate(church_urls, 1):
            print(f"Scraping {i}/{len(church_urls)}: {url}")
            result = self.scrape_church_details(url)
            all_results.append(result)
            
            if i < len(church_urls):
                time.sleep(self.delay)
        
        return all_results
    
    def scrape_from_work_history_json(self, work_history_file: str, max_records: Optional[int] = None) -> List[Dict]:
        """
        Scrape church details from Appointment URLs in work history JSON file
        
        Args:
            work_history_file: Path to the JSON file with work history data
            max_records: Maximum number of records to process (None for all)
            
        Returns:
            List of dictionaries containing church data
        """
        print(f"Loading work history data from {work_history_file}...")
        with open(work_history_file, 'r', encoding='utf-8') as f:
            work_history_data = json.load(f)
        
        # Extract unique church URLs from Appointment_URL fields
        church_urls = set()
        for record in work_history_data:
            work_history = record.get('WorkHistory', [])
            for entry in work_history:
                appointment_url = entry.get('Appointment_URL')
                if appointment_url and 'church?' in appointment_url:
                    church_urls.add(appointment_url)
        
        church_urls = sorted(list(church_urls))
        
        if max_records:
            church_urls = church_urls[:max_records]
        
        print(f"Found {len(church_urls)} unique church URLs to scrape")
        return self.scrape_multiple_churches(church_urls)
    
    def save_to_json(self, results: List[Dict], filename: str):
        """Save results to JSON file"""
        with open(filename, 'w', encoding='utf-8') as f:
            json.dump(results, f, indent=2, ensure_ascii=False)
        print(f"Data saved to {filename}")
    
    def save_to_csv(self, results: List[Dict], filename: str):
        """Save results to CSV file"""
        if not results:
            print("No results to save")
            return
        
        # Get all unique keys across all records
        all_keys = set()
        for result in results:
            all_keys.update(result.keys())
        
        # Define preferred field order
        main_fields = ['ChurchId', 'URL', 'ChurchName', 'QuickFactsYear']
        other_fields = sorted([k for k in all_keys if k not in main_fields])
        fieldnames = main_fields + other_fields
        
        with open(filename, 'w', newline='', encoding='utf-8') as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()
            writer.writerows(results)
        
        print(f"Data saved to {filename}")


def main():
    """Example usage"""
    scraper = ChurchScraper(delay=1.0)
    
    # Test with one URL
    test_url = "https://www.umdata.org/church?church=950642"
    print(f"Testing with: {test_url}\n")
    
    result = scraper.scrape_church_details(test_url)
    print(f"\nResult:")
    print(json.dumps(result, indent=2))
    
    # To scrape all churches from work history:
    # Uncomment the following lines:
    #
    # print("\n\nScraping all churches from ./data/work_history.json...")
    # all_results = scraper.scrape_from_work_history_json('./data/work_history.json')
    # scraper.save_to_json(all_results, './data/churches.json')
    # scraper.save_to_csv(all_results, './data/churches.csv')


if __name__ == "__main__":
    main()
