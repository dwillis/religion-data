# Religion Data Scrapers

A collection of Python web scrapers for extracting data from religious organization websites.

## UMData Scrapers

Tools for scraping data from [UMData.org](https://www.umdata.org), the United Methodist Church's data portal.

### Installation

```bash
uv add requests beautifulsoup4 lxml
```

### Available Scrapers

#### 1. People Scraper (`scraper.py`)

Scrapes paginated people data from UMData search results.

**Features:**
- Automatic detection of server-side DataTables pagination
- Handles HTML-encoded JSON responses
- Exports to both CSV and JSON formats
- Includes pastor profile URLs

**Usage:**
```python
from scraper import UMDataScraper

url = "https://www.umdata.org/people?confType=us&conf=3067919&historic=true"
scraper = UMDataScraper(url, delay=1.0)
records = scraper.scrape()

scraper.save_to_csv(records, '../data/umdata_people.csv')
scraper.save_to_json(records, '../data/umdata_people.json')
```

**Output Format:**
- CSV with flattened nested structures
- Includes: AccountStatus, ClergyOrLay, Conferences, FirstName, LastName, GCFAId, etc.
- Each record includes a URL field: `https://www.umdata.org/pastor?pastor={GCFAId}`

#### 2. Work History Scraper (`work_history_scraper.py`)

Scrapes appointment history from individual pastor pages.

**Features:**
- Extracts full work history including appointments, positions, and dates
- Splits date ranges into StartDate and EndDate fields
- Includes links to church pages and statistics charts
- Excludes "Present" end dates (sets to null)

**Usage:**
```python
from work_history_scraper import WorkHistoryScraper

scraper = WorkHistoryScraper(delay=1.0)

# Scrape single pastor
result = scraper.scrape_work_history("https://www.umdata.org/pastor?pastor=0124740")

# Scrape all from people JSON
all_results = scraper.scrape_from_people_json('../data/umdata_people.json')
scraper.save_to_json(all_results, '../data/work_history.json')
scraper.save_to_csv(all_results, '../data/work_history.csv')
```

**Output Fields:**
- GCFAId, PastorURL, Name
- Appointment, Appointment_URL
- Position, Status
- Dates, StartDate, EndDate
- Conference, District
- View Charts_URL (links to statistics charts)

#### 3. Church Scraper (`church_scraper.py`)

Scrapes church details and Quick Facts statistics.

**Features:**
- Extracts Quick Facts metrics (attendance, membership, financials)
- Cleans numeric values (removes $, commas)
- Indicates availability of Healthy Church Initiative data
- Can process churches from work history data

**Usage:**
```python
from church_scraper import ChurchScraper

scraper = ChurchScraper(delay=1.0)

# Scrape single church
result = scraper.scrape_church_details("https://www.umdata.org/church?church=950642")

# Scrape all from work history
all_results = scraper.scrape_from_work_history_json('../data/work_history.json')
scraper.save_to_json(all_results, '../data/churches.json')
scraper.save_to_csv(all_results, '../data/churches.csv')
```

**Output Fields:**
- ChurchId, URL, ChurchName
- QuickFactsYear, HCI_DataAvailable
- Average Attendance, Professing Members
- Professions of Faith, Baptized Members
- Sunday School Attendance, Small Group Participation
- Mission Giving, Total Spending, Total Income

#### 4. Statistics Scraper (`stats.py`)

Scrapes organizational hierarchy from the statistics page.

**Features:**
- Extracts jurisdictions, annual conferences, and districts
- Handles AJAX-loaded content
- Queries multiple jurisdictions automatically
- Includes conference information with districts

**Usage:**
```python
from stats import StatsScraper

scraper = StatsScraper()
data = scraper.scrape_statistics_page()

# Save separate files (automatically saves to ../data/ directory)
scraper.save_sections_separately(data)
# Creates: ../data/jurisdictions.json, ../data/annual_conferences.json, ../data/districts.json

# Or scrape districts from conferences
districts = scraper.scrape_districts_from_conferences(
    data['annual_conferences'],
    output_file='../data/districts.json'
)
```

**Output:**
- `jurisdictions.json` - 5 jurisdictions with names and URLs
- `annual_conferences.json` - 54 conferences with names and URLs
- `districts.json` - Districts with conference information (when available)

### Data Relationships

The scrapers are designed to work together:

```
People (scraper.py)
  └── URL → Work History (work_history_scraper.py)
        └── Appointment_URL → Church Details (church_scraper.py)

Statistics (stats.py)
  └── Jurisdictions → Annual Conferences → Districts
```

### Example Workflow

```python
# 1. Get all people in a conference
from scraper import UMDataScraper
people_scraper = UMDataScraper(
    "https://www.umdata.org/people?confType=us&conf=3067919&historic=true",
    delay=1.0
)
people = people_scraper.scrape()
people_scraper.save_to_json(people, '../data/umdata_people.json')

# 2. Get work history for all people
from work_history_scraper import WorkHistoryScraper
wh_scraper = WorkHistoryScraper(delay=1.0)
work_history = wh_scraper.scrape_from_people_json('../data/umdata_people.json')
wh_scraper.save_to_json(work_history, '../data/work_history.json')

# 3. Get church details for all appointments
from church_scraper import ChurchScraper
church_scraper = ChurchScraper(delay=1.0)
churches = church_scraper.scrape_from_work_history_json('../data/work_history.json')
church_scraper.save_to_json(churches, '../data/churches.json')

# 4. Get organizational structure
from stats import StatsScraper
stats_scraper = StatsScraper()
stats = stats_scraper.scrape_statistics_page()
# Output automatically goes to ../data/ directory
```

### Rate Limiting

All scrapers include a configurable delay between requests (default: 1.0 seconds) to be respectful of the server. Adjust as needed:

```python
scraper = UMDataScraper(url, delay=2.0)  # 2 second delay
```

### Error Handling

- Network errors are caught and reported
- Failed requests return partial results when possible
- Progress is displayed during multi-record scraping

### Notes

- Districts may not be publicly available via AJAX endpoints
- Some data requires specific query parameters (e.g., conference IDs for districts)
- HTML structure may change; scrapers may need updates if the site is redesigned

## License

MIT