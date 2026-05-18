#!/usr/bin/env python3
"""
Hartford Institute Megachurch Database Scraper
Scrapes the full list of megachurches from Hartford International University
"""

import requests
from bs4 import BeautifulSoup
import csv
import time
import re
from typing import List, Dict, Optional


class MegachurchScraper:
    """Scraper for Hartford Institute's Megachurch Database"""
    
    def __init__(self, delay: float = 1.0):
        """
        Initialize the scraper
        
        Args:
            delay: Delay between requests in seconds (be polite!)
        """
        self.delay = delay
        self.base_url = 'https://hirr.hartfordinternational.edu/research/megachurch-database/full-list-of-megachurches/'
        self.session = requests.Session()
        self.session.headers.update({
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
            'Accept-Language': 'en-US,en;q=0.9',
        })
    
    def get_total_pages(self) -> int:
        """
        Get the total number of pages from the pagination
        
        Returns:
            Total number of pages
        """
        try:
            # Need to include query parameters to get pagination
            url = f"{self.base_url}?sort_order=title%20asc&sf_paged=1"
            response = self.session.get(url, timeout=30)
            response.raise_for_status()
            
            # Look for text like "Page 1 of 67" in the raw HTML
            match = re.search(r'Page\s+\d+\s+of\s+(\d+)', response.text, re.IGNORECASE)
            if match:
                total_pages = int(match.group(1))
                print(f"Found {total_pages} pages to scrape")
                return total_pages
            
            # Parse with BeautifulSoup if regex didn't work
            soup = BeautifulSoup(response.text, 'html.parser')
            page_text = soup.get_text()
            match = re.search(r'Page\s+\d+\s+of\s+(\d+)', page_text, re.IGNORECASE)
            if match:
                total_pages = int(match.group(1))
                print(f"Found {total_pages} pages from parsed text")
                return total_pages
            
            # Fallback: look for pagination div
            pagination = soup.find('div', class_='pagination')
            if pagination:
                pagination_text = pagination.get_text(strip=True)
                match = re.search(r'Page\s+\d+\s+of\s+(\d+)', pagination_text, re.IGNORECASE)
                if match:
                    total_pages = int(match.group(1))
                    print(f"Found {total_pages} pages from pagination div")
                    return total_pages
            
            # Another fallback: look for page links
            page_links = soup.find_all('a', class_='page-numbers')
            if page_links:
                # Get the highest page number
                page_numbers = []
                for link in page_links:
                    text = link.get_text(strip=True)
                    if text.isdigit():
                        page_numbers.append(int(text))
                if page_numbers:
                    total_pages = max(page_numbers)
                    print(f"Found {total_pages} pages from page links")
                    return total_pages
            
            print("Could not determine total pages, defaulting to 1")
            return 1
            
        except Exception as e:
            print(f"Error getting total pages: {e}")
            return 1
    
    def scrape_page(self, page_num: int) -> List[Dict]:
        """
        Scrape churches from a single page
        
        Args:
            page_num: Page number to scrape
            
        Returns:
            List of church dictionaries
        """
        url = f"{self.base_url}?sort_order=title%20asc&sf_paged={page_num}"
        
        try:
            print(f"Scraping page {page_num}: {url}")
            response = self.session.get(url, timeout=30)
            response.raise_for_status()
            soup = BeautifulSoup(response.text, 'html.parser')
            
            churches = []
            
            # Find the table with church data
            table = soup.find('table')
            if not table:
                print(f"  No table found on page {page_num}")
                return churches
            
            # Get all rows except the header
            rows = table.find_all('tr')[1:]  # Skip header row
            
            for row in rows:
                church = self._extract_church_info(row)
                if church:
                    churches.append(church)
            
            print(f"  Found {len(churches)} churches on page {page_num}")
            return churches
            
        except Exception as e:
            print(f"Error scraping page {page_num}: {e}")
            return []
    
    def _extract_church_info(self, row: BeautifulSoup) -> Optional[Dict]:
        """
        Extract church information from a table row
        
        Args:
            row: BeautifulSoup tr element containing church data
            
        Returns:
            Dictionary with church information
        """
        try:
            church = {
                'church_name': '',
                'church_url': '',
                'city': '',
                'state': '',
                'size': '',
                'denomination': ''
            }
            
            # Use data-label attributes to extract cells correctly
            # (The HTML has malformed td tags for City)
            church_name_cell = row.find('td', {'data-label': 'Church Name'})
            city_cell = row.find('td', {'data-label': 'City'})
            state_cell = row.find('td', {'data-label': 'State'})
            size_cell = row.find('td', {'data-label': 'Size'})
            denom_cell = row.find('td', {'data-label': 'Denomination'})
            
            # Skip header rows
            if not church_name_cell:
                return None
            
            # Extract church name and URL
            church['church_name'] = church_name_cell.get_text(strip=True)
            link = church_name_cell.find('a')
            if link:
                church['church_url'] = link.get('href', '')
            
            # Extract other fields, handling None values
            if city_cell:
                # Extract only direct text from city cell (not nested cells)
                city_text = list(city_cell.stripped_strings)[0] if city_cell.stripped_strings else ''
                church['city'] = city_text
            if state_cell:
                church['state'] = state_cell.get_text(strip=True)
            if size_cell:
                church['size'] = size_cell.get_text(strip=True)
            if denom_cell:
                church['denomination'] = denom_cell.get_text(strip=True)
            
            # Only return if we have at least a church name
            if church['church_name']:
                return church
            
            return None
            
        except Exception as e:
            print(f"Error extracting church info: {e}")
            return None
    
    def scrape_all_pages(self) -> List[Dict]:
        """
        Scrape all pages of the megachurch database
        
        Returns:
            List of all churches
        """
        total_pages = self.get_total_pages()
        all_churches = []
        
        for page_num in range(1, total_pages + 1):
            churches = self.scrape_page(page_num)
            all_churches.extend(churches)
            
            # Be polite - delay between requests
            if page_num < total_pages:
                time.sleep(self.delay)
        
        print(f"\nTotal churches scraped: {len(all_churches)}")
        return all_churches
    
    def save_to_csv(self, churches: List[Dict], filename: str = 'megachurches.csv'):
        """
        Save churches to CSV file
        
        Args:
            churches: List of church dictionaries
            filename: Output filename
        """
        if not churches:
            print("No churches to save")
            return
        
        fieldnames = ['church_name', 'church_url', 'city', 'state', 'size', 'denomination']
        
        with open(filename, 'w', newline='', encoding='utf-8') as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()
            writer.writerows(churches)
        
        print(f"Saved {len(churches)} churches to {filename}")


def main():
    """Main function"""
    scraper = MegachurchScraper(delay=1.0)
    
    print("Starting megachurch database scraper...")
    churches = scraper.scrape_all_pages()
    
    if churches:
        scraper.save_to_csv(churches, 'megachurches.csv')
        
        # Print sample
        print("\nSample of first church:")
        for key, value in churches[0].items():
            print(f"  {key}: {value}")
    else:
        print("No churches were scraped")


if __name__ == "__main__":
    main()
