#!/usr/bin/env python3
"""
UMData Statistics Scraper
Scrapes Jurisdictions, Annual Conferences, and Districts from the statistics page
"""

import requests
from bs4 import BeautifulSoup
import json
import re
from typing import List, Dict, Optional


class StatsScraper:
    """Scraper for UMData.org statistics page"""
    
    def __init__(self):
        """Initialize the scraper"""
        self.session = requests.Session()
        self.session.headers.update({
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
            'Accept-Language': 'en-US,en;q=0.9',
        })
        self.base_url = 'https://www.umdata.org'
    
    def scrape_statistics_page(self, url: str = 'https://www.umdata.org/statistics') -> Dict:
        """
        Scrape the statistics page for Jurisdictions, Annual Conferences, and Districts
        
        Args:
            url: URL to the statistics page
            
        Returns:
            Dictionary containing all three sections
        """
        try:
            response = self.session.get(url, timeout=30)
            response.raise_for_status()
            soup = BeautifulSoup(response.text, 'lxml')
            
            # Get jurisdictions from the page
            jurisdictions = self._extract_section(soup, 'Jurisdictions')
            
            # Extract jurisdiction IDs from the dropdown (different from URL IDs)
            jur_dropdown_ids = self._extract_jurisdiction_dropdown_ids(soup)
            
            # Get all conferences and districts by querying each jurisdiction
            print("Fetching conferences and districts for each jurisdiction...")
            all_conferences = []
            all_districts = []
            
            for jur in jurisdictions:
                jur_name = jur['name']
                jur_id = jur_dropdown_ids.get(jur_name)
                
                if jur_id:
                    print(f"  Processing {jur_name} (ID: {jur_id})...")
                    
                    # Get conferences for this jurisdiction
                    conferences = self._get_conferences_for_jurisdiction(jur_id)
                    all_conferences.extend(conferences)
                    
                    # Get districts for this jurisdiction
                    districts = self._get_districts_for_jurisdiction(jur_id)
                    all_districts.extend(districts)
                else:
                    print(f"  Warning: No dropdown ID found for {jur_name}")
            
            return {
                'jurisdictions': jurisdictions,
                'annual_conferences': all_conferences,
                'districts': all_districts
            }
            
        except requests.exceptions.RequestException as e:
            print(f"Error fetching {url}: {e}")
            raise
    
    def _extract_jurisdiction_dropdown_ids(self, soup: BeautifulSoup) -> Dict[str, str]:
        """Extract jurisdiction IDs from the dropdown menu"""
        jur_ids = {}
        select = soup.find('select', id='jurConferences')
        if select:
            for option in select.find_all('option'):
                value = option.get('value')
                text = option.get_text(strip=True)
                if value and text:
                    jur_ids[text] = value
        return jur_ids
    
    def _extract_section(self, soup: BeautifulSoup, section_name: str) -> List[Dict]:
        """
        Extract names and URLs from a section
        
        Args:
            soup: BeautifulSoup object of the page
            section_name: Name of the section (e.g., 'Jurisdictions')
            
        Returns:
            List of dictionaries with name and URL
        """
        results = []
        
        # Find the section header (use string content matching)
        headers = soup.find_all('h2')
        header = None
        for h in headers:
            if section_name.lower() in h.get_text(strip=True).lower():
                header = h
                break
        
        if not header:
            print(f"Section '{section_name}' not found")
            return results
        
        # Get the parent container
        container = header.find_parent(['div', 'section'])
        if not container:
            # Try finding the next sibling
            container = header.find_next_sibling()
        
        if not container:
            print(f"Container for '{section_name}' not found")
            return results
        
        # Find the table in this section
        table = container.find('table')
        if not table:
            # Look in accordion content
            accordion = container.find('div', class_=lambda x: x and 'accordion' in str(x).lower())
            if accordion:
                table = accordion.find('table')
        
        if not table:
            print(f"Table for '{section_name}' not found")
            return results
        
        # Get all rows (skip header)
        rows = table.find_all('tr')[1:]  # Skip the header row
        
        for row in rows:
            cells = row.find_all(['td', 'th'])
            if not cells:
                continue
            
            # First cell should have the name and link
            first_cell = cells[0]
            link = first_cell.find('a')
            
            if link:
                name = link.get_text(strip=True)
                href = link.get('href')
                
                # Make absolute URL if relative
                if href and not href.startswith('http'):
                    href = f"{self.base_url}{href}"
                
                results.append({
                    'name': name,
                    'url': href
                })
        
        return results
    
    def save_to_json(self, data: Dict, filename: str):
        """Save data to JSON file"""
        with open(filename, 'w', encoding='utf-8') as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
        print(f"Data saved to {filename}")
    
    def save_sections_separately(self, data: Dict):
        """Save each section to its own JSON file"""
        for section_key, section_data in data.items():
            filename = f"{section_key}.json"
            with open(filename, 'w', encoding='utf-8') as f:
                json.dump(section_data, f, indent=2, ensure_ascii=False)
            print(f"Saved {len(section_data)} records to {filename}")
    
    def _get_conferences_for_jurisdiction(self, jur_id: str, year: str = "2024") -> List[Dict]:
        """Get annual conferences for a specific jurisdiction via AJAX"""
        ajax_url = f"{self.base_url}/stats-conferences-ajax?jur={jur_id}&year={year}"
        
        try:
            response = self.session.get(ajax_url, timeout=30)
            response.raise_for_status()
            soup = BeautifulSoup(response.text, 'lxml')
            
            conferences = []
            table = soup.find('table')
            if table:
                rows = table.find_all('tr')[1:]  # Skip header
                for row in rows:
                    cells = row.find_all(['td', 'th'])
                    if cells:
                        link = cells[0].find('a')
                        if link:
                            name = link.get_text(strip=True)
                            href = link.get('href')
                            if href and not href.startswith('http'):
                                href = f"{self.base_url}{href}"
                            conferences.append({'name': name, 'url': href})
            
            return conferences
        except Exception as e:
            print(f"    Error fetching conferences for jurisdiction {jur_id}: {e}")
            return []
    
    def _get_districts_for_jurisdiction(self, jur_id: str, year: str = "2024") -> List[Dict]:
        """Get districts for a specific jurisdiction via AJAX"""
        ajax_url = f"{self.base_url}/stats-districts-ajax?jur={jur_id}&year={year}"
        
        try:
            response = self.session.get(ajax_url, timeout=30)
            response.raise_for_status()
            soup = BeautifulSoup(response.text, 'lxml')
            
            districts = []
            table = soup.find('table')
            if table:
                rows = table.find_all('tr')[1:]  # Skip header
                for row in rows:
                    cells = row.find_all(['td', 'th'])
                    if cells:
                        link = cells[0].find('a')
                        if link:
                            name = link.get_text(strip=True)
                            href = link.get('href')
                            if href and not href.startswith('http'):
                                href = f"{self.base_url}{href}"
                            districts.append({'name': name, 'url': href})
            
            return districts
        except Exception as e:
            print(f"    Error fetching districts for jurisdiction {jur_id}: {e}")
            return []
    
    def _get_districts_for_conference(self, conf_id: str, year: str = "2024") -> List[Dict]:
        """Get districts for a specific conference via AJAX"""
        ajax_url = f"{self.base_url}/stats-districts-ajax?conf={conf_id}&year={year}"
        
        try:
            response = self.session.get(ajax_url, timeout=30)
            response.raise_for_status()
            soup = BeautifulSoup(response.text, 'lxml')
            
            districts = []
            table = soup.find('table')
            if table:
                rows = table.find_all('tr')[1:]  # Skip header
                for row in rows:
                    cells = row.find_all(['td', 'th'])
                    if cells:
                        link = cells[0].find('a')
                        if link:
                            name = link.get_text(strip=True)
                            href = link.get('href')
                            if href and not href.startswith('http'):
                                href = f"{self.base_url}{href}"
                            districts.append({'name': name, 'url': href})
            
            return districts
        except Exception as e:
            print(f"    Error fetching districts for conference {conf_id}: {e}")
            return []
    
    def scrape_districts_from_conferences(self, conferences: List[Dict], output_file: str = '../data/districts.json') -> List[Dict]:
        """
        Scrape districts from all conferences
        
        Args:
            conferences: List of conference dictionaries with 'name' and 'url'
            output_file: Filename to save the districts data
            
        Returns:
            List of district dictionaries with conference information
        """
        all_districts = []
        
        print(f"\nScraping districts from {len(conferences)} conferences...")
        
        for i, conf in enumerate(conferences, 1):
            conf_name = conf['name']
            conf_url = conf['url']
            
            # Extract conference ID from URL
            conf_match = re.search(r'conf=(\d+)', conf_url)
            if not conf_match:
                print(f"  {i}/{len(conferences)}: {conf_name} - No conference ID found")
                continue
            
            conf_id = conf_match.group(1)
            print(f"  {i}/{len(conferences)}: {conf_name} (ID: {conf_id})...")
            
            # Get districts for this conference
            districts = self._get_districts_for_conference(conf_id)
            
            # Add conference information to each district
            for district in districts:
                district['conference_name'] = conf_name
                district['conference_url'] = conf_url
                district['conference_id'] = conf_id
                all_districts.append(district)
            
            print(f"    Found {len(districts)} districts")
            
            # Small delay to be polite
            import time
            time.sleep(0.5)
        
        print(f"\nTotal districts found: {len(all_districts)}")
        
        # Save to file
        if all_districts:
            with open(output_file, 'w', encoding='utf-8') as f:
                json.dump(all_districts, f, indent=2, ensure_ascii=False)
            print(f"Saved to {output_file}")
        
        return all_districts


def main():
    """Main function"""
    scraper = StatsScraper()
    
    print("Scraping statistics page...")
    data = scraper.scrape_statistics_page()
    
    print(f"\nResults:")
    print(f"  Jurisdictions: {len(data['jurisdictions'])}")
    print(f"  Annual Conferences: {len(data['annual_conferences'])}")
    print(f"  Districts: {len(data['districts'])}")
    
    # Save all to one file
    scraper.save_to_json(data, '../data/statistics_all.json')
    
    # Save each section separately
    print("\nSaving individual files...")
    import os
    os.makedirs('../data', exist_ok=True)
    for section_key, section_data in data.items():
        filename = f"../data/{section_key}.json"
        with open(filename, 'w', encoding='utf-8') as f:
            json.dump(section_data, f, indent=2, ensure_ascii=False)
        print(f"Saved {len(section_data)} records to {filename}")
    
    # Print samples
    if data['jurisdictions']:
        print("\nSample Jurisdiction:")
        print(json.dumps(data['jurisdictions'][0], indent=2))
    
    if data['annual_conferences']:
        print("\nSample Annual Conference:")
        print(json.dumps(data['annual_conferences'][0], indent=2))
    
    # Now scrape districts from all conferences
    if data['annual_conferences']:
        districts = scraper.scrape_districts_from_conferences(data['annual_conferences'])
        
        if districts:
            print("\nSample District (with conference info):")
            print(json.dumps(districts[0], indent=2))
        else:
            print("\nNote: No districts were found. Districts may not be publicly available")
            print("via the statistics AJAX endpoints or may require different parameters.")


if __name__ == "__main__":
    main()
