"""
MarketScreener Stock Scraper (Async Version)
=============================================
Async web scraper using aiohttp + asyncio + BeautifulSoup to extract 
financial data for Moroccan stocks from MarketScreener.com.

Usage:
    python scraper.py
    
Output:
    - testing/stock_data.csv: Flattened CSV with all scraped data
    - testing/stock_data.json: Full JSON with nested structure
"""

import re
import asyncio
import random
import logging
import json
import csv
import os
from datetime import datetime
from typing import Optional, Dict, List, Any
from dataclasses import dataclass, field, asdict

try:
    import aiohttp
    from bs4 import BeautifulSoup
    HAS_DEPENDENCIES = True
except ImportError:
    HAS_DEPENDENCIES = False
    print("Missing dependencies. Install with: pip install aiohttp beautifulsoup4 lxml")

# =============================================================================
# Configuration
# =============================================================================

BASE_URL = "https://www.marketscreener.com/quote/stock"

STOCKS = {
    "IAM": {
        "url_code": "ITISSALAT-AL-MAGHRIB-IAM--1408717",
        "full_name": "Itissalat Al-Maghrib (IAM) S.A.",
        "ticker": "IAM",
        "exchange": "Casablanca S.E.",
        "currency": "MAD"
    }
}

PAGES = {
    "main": "/",
    "finances": "/finances/",
    "consensus": "/consensus/",
    "valuation": "/valuation/",
    "calendar": "/calendar/",
    "company": "/company/"
}

REQUEST_CONFIG = {
    "timeout": 30,
    "max_retries": 3,
    "retry_delay": 2,
    "min_delay": 2,
    "max_delay": 5
}

DEFAULT_HEADERS = {
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.5",
    "Accept-Encoding": "gzip, deflate, br",
    "Connection": "keep-alive",
    "Upgrade-Insecure-Requests": "1"
}

USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:123.0) Gecko/20100101 Firefox/123.0",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.3 Safari/605.1.15",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36 Edg/121.0.0.0",
]

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


# =============================================================================
# Data Classes
# =============================================================================

@dataclass
class StockIdentity:
    full_name: Optional[str] = None
    ticker: Optional[str] = None
    isin: Optional[str] = None
    exchange: Optional[str] = None
    sector: Optional[str] = None
    currency: Optional[str] = None
    url_code: Optional[str] = None


@dataclass
class PricePerformance:
    last_price: Optional[float] = None
    last_date: Optional[str] = None
    change_1d: Optional[float] = None
    change_1w: Optional[float] = None
    change_1m: Optional[float] = None
    change_3m: Optional[float] = None
    change_6m: Optional[float] = None
    change_ytd: Optional[float] = None
    change_1y: Optional[float] = None
    volume: Optional[int] = None
    high_52w: Optional[float] = None
    low_52w: Optional[float] = None


@dataclass
class ValuationMetrics:
    market_cap: Optional[float] = None
    enterprise_value: Optional[float] = None
    free_float_pct: Optional[float] = None
    pe_ratio: Optional[float] = None
    pe_ratio_next_year: Optional[float] = None
    ev_sales: Optional[float] = None
    dividend_yield: Optional[float] = None
    price_to_book: Optional[float] = None
    ev_ebitda: Optional[float] = None
    # Historical data by year
    pe_ratio_hist: Optional[Dict[str, float]] = None
    pbr_hist: Optional[Dict[str, float]] = None  # Price to Book Ratio
    peg_hist: Optional[Dict[str, float]] = None
    ev_revenue_hist: Optional[Dict[str, float]] = None
    ev_ebitda_hist: Optional[Dict[str, float]] = None
    ev_ebit_hist: Optional[Dict[str, float]] = None
    ev_fcf_hist: Optional[Dict[str, float]] = None
    fcf_yield_hist: Optional[Dict[str, float]] = None
    dividend_per_share_hist: Optional[Dict[str, float]] = None
    eps_hist: Optional[Dict[str, float]] = None
    distribution_rate_hist: Optional[Dict[str, float]] = None
    num_shares: Optional[float] = None  # Number of shares in thousands


@dataclass
class FinancialEstimates:
    # Income Statement
    net_sales: Optional[Dict[str, float]] = None
    revenues: Optional[Dict[str, float]] = None
    cost_of_sales: Optional[Dict[str, float]] = None
    gross_profit: Optional[Dict[str, float]] = None
    operating_income: Optional[Dict[str, float]] = None
    ebitda: Optional[Dict[str, float]] = None
    ebit: Optional[Dict[str, float]] = None
    net_income: Optional[Dict[str, float]] = None
    eps: Optional[Dict[str, float]] = None
    # Balance Sheet
    total_assets: Optional[Dict[str, float]] = None
    total_liabilities: Optional[Dict[str, float]] = None
    shareholders_equity: Optional[Dict[str, float]] = None
    net_debt: Optional[Dict[str, float]] = None
    cash_and_equivalents: Optional[Dict[str, float]] = None
    total_debt: Optional[Dict[str, float]] = None
    working_capital: Optional[Dict[str, float]] = None
    # Cash Flow
    operating_cash_flow: Optional[Dict[str, float]] = None
    capex: Optional[Dict[str, float]] = None
    free_cash_flow: Optional[Dict[str, float]] = None
    dividends_paid: Optional[Dict[str, float]] = None
    # Ratios
    ebitda_margin: Optional[Dict[str, float]] = None
    operating_margin: Optional[Dict[str, float]] = None
    net_margin: Optional[Dict[str, float]] = None
    roe: Optional[Dict[str, float]] = None
    roa: Optional[Dict[str, float]] = None
    roce: Optional[Dict[str, float]] = None
    debt_to_equity: Optional[Dict[str, float]] = None
    current_ratio: Optional[Dict[str, float]] = None


@dataclass
class AnalystConsensus:
    consensus: Optional[str] = None
    num_analysts: Optional[int] = None
    target_price_avg: Optional[float] = None
    target_price_high: Optional[float] = None
    target_price_low: Optional[float] = None
    upside_pct: Optional[float] = None


@dataclass
class Ratings:
    trader_rating: Optional[str] = None
    investor_rating: Optional[str] = None
    global_rating: Optional[str] = None
    quality_rating: Optional[str] = None
    esg_rating: Optional[str] = None


@dataclass
class CalendarEvents:
    ex_dividend_date: Optional[str] = None
    dividend_amount: Optional[float] = None
    dividend_payment_date: Optional[str] = None
    next_earnings_date: Optional[str] = None


@dataclass
class CompanyProfile:
    employees: Optional[int] = None
    description: Optional[str] = None
    international_revenue_pct: Optional[float] = None


@dataclass
class NewsArticle:
    title: Optional[str] = None
    date: Optional[str] = None
    source: Optional[str] = None
    snippet: Optional[str] = None
    url: Optional[str] = None
    full_content: Optional[str] = None


@dataclass
class StockNews:
    articles: List[Any] = field(default_factory=list)  # List[NewsArticle]
    total_count: int = 0


@dataclass
class StockData:
    scrape_timestamp: str = field(default_factory=lambda: datetime.utcnow().isoformat() + "Z")
    identity: StockIdentity = field(default_factory=StockIdentity)
    price_performance: PricePerformance = field(default_factory=PricePerformance)
    valuation: ValuationMetrics = field(default_factory=ValuationMetrics)
    financials: FinancialEstimates = field(default_factory=FinancialEstimates)
    consensus: AnalystConsensus = field(default_factory=AnalystConsensus)
    ratings: Ratings = field(default_factory=Ratings)
    calendar: CalendarEvents = field(default_factory=CalendarEvents)
    company: CompanyProfile = field(default_factory=CompanyProfile)
    news: StockNews = field(default_factory=StockNews)

    def to_flat_dict(self) -> Dict[str, Any]:
        """Flatten nested structure for CSV export."""
        flat = {"scrape_timestamp": self.scrape_timestamp}
        
        # Identity
        for k, v in asdict(self.identity).items():
            flat[f"identity_{k}"] = v
        
        # Price Performance
        for k, v in asdict(self.price_performance).items():
            flat[f"price_{k}"] = v
        
        # Valuation - flatten year-based dicts
        val_dict = asdict(self.valuation)
        for metric, value in val_dict.items():
            if isinstance(value, dict):
                for year, val in value.items():
                    flat[f"valuation_{metric}_{year}"] = val
            else:
                flat[f"valuation_{metric}"] = value
        
        # Financials - flatten year-based dicts
        fin_dict = asdict(self.financials)
        for metric, years in fin_dict.items():
            if isinstance(years, dict):
                for year, value in years.items():
                    flat[f"fin_{metric}_{year}"] = value
            else:
                flat[f"fin_{metric}"] = years
        
        # Consensus
        for k, v in asdict(self.consensus).items():
            flat[f"consensus_{k}"] = v
        
        # Ratings
        for k, v in asdict(self.ratings).items():
            flat[f"rating_{k}"] = v
        
        # Calendar
        for k, v in asdict(self.calendar).items():
            flat[f"calendar_{k}"] = v
        
        # Company
        for k, v in asdict(self.company).items():
            flat[f"company_{k}"] = v

        # News summary
        flat["news_total_count"] = self.news.total_count
        for i, article in enumerate(self.news.articles[:5]):
            a = asdict(article) if not isinstance(article, dict) else article
            flat[f"news_{i}_title"] = a.get("title")
            flat[f"news_{i}_date"] = a.get("date")
            flat[f"news_{i}_source"] = a.get("source")

        return flat
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to nested dictionary."""
        return {
            "scrape_timestamp": self.scrape_timestamp,
            "identity": asdict(self.identity),
            "price_performance": asdict(self.price_performance),
            "valuation": asdict(self.valuation),
            "financials": asdict(self.financials),
            "consensus": asdict(self.consensus),
            "ratings": asdict(self.ratings),
            "calendar": asdict(self.calendar),
            "company": asdict(self.company),
            "news": {
                "total_count": self.news.total_count,
                "articles": [asdict(a) if not isinstance(a, dict) else a
                             for a in self.news.articles]
            }
        }


# =============================================================================
# Parsing Utilities
# =============================================================================

def clean_text(text: Optional[str]) -> Optional[str]:
    """Clean and normalize text."""
    if not text:
        return None
    cleaned = re.sub(r'\s+', ' ', text.strip())
    return cleaned if cleaned else None


def parse_number(text: Optional[str]) -> Optional[float]:
    """Parse a number from text, handling various formats."""
    if not text:
        return None
    
    text = text.strip()
    
    # Handle suffixes
    multiplier = 1
    text_upper = text.upper()
    if text_upper.endswith('B'):
        multiplier = 1_000_000_000
        text = text[:-1]
    elif text_upper.endswith('M'):
        multiplier = 1_000_000
        text = text[:-1]
    elif text_upper.endswith('K'):
        multiplier = 1_000
        text = text[:-1]
    
    # Remove currency symbols and percent signs
    text = re.sub(r'[€$£¥₹%]', '', text)
    text = text.replace('MAD', '').replace('USD', '').replace('EUR', '')
    
    # Remove spaces (thousand separator)
    text = text.replace(' ', '').replace('\xa0', '')
    
    # Handle European/US number formats
    if ',' in text and '.' in text:
        if text.rfind(',') > text.rfind('.'):
            text = text.replace('.', '').replace(',', '.')
        else:
            text = text.replace(',', '')
    elif ',' in text:
        parts = text.split(',')
        if len(parts) == 2 and len(parts[1]) <= 2:
            text = text.replace(',', '.')
        else:
            text = text.replace(',', '')
    
    try:
        value = float(text) * multiplier
        return value
    except (ValueError, TypeError):
        return None


def parse_percentage(text: Optional[str]) -> Optional[float]:
    """Parse a percentage value."""
    if not text:
        return None
    
    text = text.strip().replace('%', '').strip()
    is_negative = text.startswith('-') or '−' in text
    text = text.replace('-', '').replace('−', '').replace('+', '')
    
    value = parse_number(text)
    if value is not None and is_negative:
        value = -value
    
    return value


# =============================================================================
# Async HTTP Client
# =============================================================================

class AsyncHTTPClient:
    """Async HTTP client with aiohttp, retry logic, and rate limiting."""
    
    def __init__(self):
        if not HAS_DEPENDENCIES:
            raise RuntimeError("Missing dependencies")
        self.session: Optional[aiohttp.ClientSession] = None
        self._semaphore = asyncio.Semaphore(3)  # Limit concurrent requests
    
    async def _get_session(self) -> aiohttp.ClientSession:
        if self.session is None or self.session.closed:
            timeout = aiohttp.ClientTimeout(total=REQUEST_CONFIG["timeout"])
            connector = aiohttp.TCPConnector(limit=10, limit_per_host=3)
            self.session = aiohttp.ClientSession(timeout=timeout, connector=connector)
        return self.session
    
    async def _rate_limit(self):
        """Add random delay between requests."""
        delay = random.uniform(REQUEST_CONFIG["min_delay"], REQUEST_CONFIG["max_delay"])
        await asyncio.sleep(delay)
    
    async def get(self, url: str, retries: int = 3) -> Optional[str]:
        """Async GET request with retry logic."""
        async with self._semaphore:
            await self._rate_limit()
            
            headers = DEFAULT_HEADERS.copy()
            headers["User-Agent"] = random.choice(USER_AGENTS)
            
            session = await self._get_session()
            
            for attempt in range(retries):
                try:
                    logger.info(f"Fetching: {url}")
                    async with session.get(url, headers=headers) as response:
                        if response.status == 200:
                            return await response.text()
                        elif response.status in [429, 500, 502, 503, 504]:
                            wait = (attempt + 1) * REQUEST_CONFIG["retry_delay"]
                            logger.warning(f"Got {response.status}, retrying in {wait}s...")
                            await asyncio.sleep(wait)
                        else:
                            logger.error(f"HTTP {response.status} for {url}")
                            return None
                except asyncio.TimeoutError:
                    logger.warning(f"Timeout for {url}, attempt {attempt + 1}/{retries}")
                except aiohttp.ClientError as e:
                    logger.error(f"Client error for {url}: {e}")
                    if attempt < retries - 1:
                        await asyncio.sleep(REQUEST_CONFIG["retry_delay"])
            
            return None
    
    async def get_many(self, urls: List[str]) -> Dict[str, Optional[str]]:
        """Fetch multiple URLs concurrently."""
        tasks = [self.get(url) for url in urls]
        results = await asyncio.gather(*tasks, return_exceptions=True)
        
        return {
            url: (result if isinstance(result, str) else None)
            for url, result in zip(urls, results)
        }
    
    async def close(self):
        if self.session and not self.session.closed:
            await self.session.close()


# =============================================================================
# Async Scraper Classes
# =============================================================================

class BaseScraper:
    """Base async scraper class."""
    
    def __init__(self, http_client: AsyncHTTPClient):
        self.client = http_client
    
    async def get_soup(self, url: str) -> Optional[BeautifulSoup]:
        html = await self.client.get(url)
        if html:
            return BeautifulSoup(html, 'lxml')
        return None
    
    def find_by_text(self, soup: BeautifulSoup, text: str, tag: str = None) -> Optional[str]:
        """Find element containing text and return its next sibling value."""
        elements = soup.find_all(tag) if tag else soup.find_all()
        for elem in elements:
            if text.lower() in elem.get_text().lower():
                next_elem = elem.find_next_sibling()
                if next_elem:
                    return clean_text(next_elem.get_text())
        return None


class QuoteScraper(BaseScraper):
    """Scrape main quote page for price and performance data."""
    
    async def scrape(self, stock_config: Dict, stock_data: StockData) -> None:
        url = f"{BASE_URL}/{stock_config['url_code']}/"
        soup = await self.get_soup(url)
        
        if not soup:
            logger.error("Failed to fetch main quote page")
            return
        
        # Set identity from config
        stock_data.identity.full_name = stock_config.get("full_name")
        stock_data.identity.ticker = stock_config.get("ticker")
        stock_data.identity.exchange = stock_config.get("exchange")
        stock_data.identity.currency = stock_config.get("currency")
        stock_data.identity.url_code = stock_config.get("url_code")
        
        # Extract from JSON-LD structured data
        self._parse_json_ld(soup, stock_data)
        
        # Get price from span with class "last" and data attributes
        price_elem = soup.find('span', class_='last')
        if price_elem:
            stock_data.price_performance.last_price = parse_number(price_elem.get_text())
        
        # Get daily change from variation span (first one in price section)
        price_section = soup.find('td', class_='is__realtime-var')
        if price_section:
            change_elem = price_section.find('span', class_=re.compile(r'variation'))
            if change_elem:
                stock_data.price_performance.change_1d = parse_percentage(change_elem.get_text())
        else:
            # Fallback to first variation span
            change_elem = soup.find('span', class_=re.compile(r'variation'))
            if change_elem:
                stock_data.price_performance.change_1d = parse_percentage(change_elem.get_text())
        
        # Get 5-day and YTD changes from the price table
        # They are in separate cells with txt-align-center class
        change_cells = soup.find_all('td', class_='txt-align-center')
        change_values = []
        for cell in change_cells:
            var_span = cell.find('span', class_=re.compile(r'variation'))
            if var_span:
                text = var_span.get_text()
                if '%' in text:
                    change_values.append(parse_percentage(text))
        
        # Based on HTML structure: 5-day change comes first, then YTD
        if len(change_values) >= 1:
            stock_data.price_performance.change_1w = change_values[0]  # 5-day change
        if len(change_values) >= 2:
            stock_data.price_performance.change_ytd = change_values[1]  # YTD change
        
        # Parse valuation table on main page
        self._parse_valuation_table(soup, stock_data)
        
        # Get ISIN and sector from badges
        badges = soup.find_all('h2', class_='m-0')
        for badge in badges:
            text = clean_text(badge.get_text())
            if text and re.match(r'^[A-Z]{2}\d+$', text):  # ISIN pattern
                stock_data.identity.isin = text
            elif text and 'Telecommunications' in text:
                stock_data.identity.sector = text
    
    def _parse_json_ld(self, soup: BeautifulSoup, stock_data: StockData) -> None:
        """Extract data from JSON-LD structured data."""
        scripts = soup.find_all('script', type='application/ld+json')
        for script in scripts:
            try:
                data = json.loads(script.string)
                if data.get('@type') == 'FinancialProduct':
                    offers = data.get('offers', {})
                    if offers.get('price'):
                        stock_data.price_performance.last_price = float(offers['price'])
                    if offers.get('identifier'):
                        stock_data.identity.isin = offers['identifier']
                    
                    brand = data.get('brand', {})
                    if brand.get('name'):
                        stock_data.identity.full_name = brand['name']
                    # Don't use brand description as company description - it's truncated
                    # We'll get the full description from the company page instead
                    
                    broker = data.get('broker', {})
                    if broker.get('name'):
                        stock_data.identity.exchange = broker['name']
                        
            except (json.JSONDecodeError, TypeError):
                continue
    
    def _parse_valuation_table(self, soup: BeautifulSoup, stock_data: StockData) -> None:
        """Parse valuation table from main page."""
        # Find the valuation card
        valo_card = soup.find('div', id='valoData')
        if not valo_card:
            return
        
        table = valo_card.find('table')
        if not table:
            return
        
        for row in table.find_all('tr'):
            cells = row.find_all(['td', 'th'])
            i = 0
            while i < len(cells) - 1:
                label = clean_text(cells[i].get_text()) or ""
                value_cell = cells[i + 1]
                label_lower = label.lower()
                
                # Get value - prefer the 'title' attribute from span for full number,
                # or text for ratios/percentages
                value_span = value_cell.find('span', class_='efd_MAD')
                if value_span:
                    # Use title attribute for full number (e.g., "83,953,604,970")
                    inner_span = value_span.find('span', title=True)
                    if inner_span and inner_span.get('title'):
                        value_text = inner_span['title']
                    else:
                        value_text = clean_text(value_span.get_text())
                else:
                    # For non-currency values like P/E, yield
                    div = value_cell.find('div')
                    if div:
                        value_text = clean_text(div.get_text())
                    else:
                        value_text = clean_text(value_cell.get_text())
                
                if 'capitalization' in label_lower:
                    stock_data.valuation.market_cap = parse_number(value_text)
                elif 'enterprise value' in label_lower:
                    stock_data.valuation.enterprise_value = parse_number(value_text)
                elif 'free-float' in label_lower:
                    stock_data.valuation.free_float_pct = parse_percentage(value_text)
                elif 'p/e ratio' in label_lower:
                    pe_value = parse_number(value_text.replace('x', ''))
                    if '2026' in label or '2027' not in label:
                        if stock_data.valuation.pe_ratio is None:
                            stock_data.valuation.pe_ratio = pe_value
                    if '2027' in label:
                        stock_data.valuation.pe_ratio_next_year = pe_value
                elif 'ev / sales' in label_lower or 'ev/sales' in label_lower:
                    stock_data.valuation.ev_sales = parse_number(value_text.replace('x', ''))
                elif 'yield' in label_lower:
                    stock_data.valuation.dividend_yield = parse_percentage(value_text)
                
                i += 2

        # Additional extraction: volume, 52w high/low, other changes
        self._parse_additional_metrics(soup, stock_data)

    def _parse_additional_metrics(self, soup: BeautifulSoup, stock_data: StockData) -> None:
        """Extract additional price metrics from various sources."""
        page_text = soup.get_text()

        # Try to find volume (often displayed with "Vol." or "Volume")
        vol_patterns = [
            r'(?:Volume|Vol\.)[:\s]+([0-9,]+(?:\.[0-9]+)?)',
            r'(?:Volume|Vol\.)\s*\([^)]*\)[:\s]+([0-9,]+(?:\.[0-9]+)?)',
            r'trading[^0-9]*([0-9,]+(?:\.[0-9]+)?)\s*(?:shares|units)',
        ]
        for pattern in vol_patterns:
            vol_match = re.search(pattern, page_text, re.IGNORECASE)
            if vol_match:
                stock_data.price_performance.volume = int(parse_number(vol_match.group(1)) or 0)
                if stock_data.price_performance.volume:
                    break

        # 52-week high and low
        high_patterns = [
            r'52w[^0-9]*high[:\s]+([0-9,]+(?:\.[0-9]+)?)',
            r'high\s+\(52w\)[:\s]+([0-9,]+(?:\.[0-9]+)?)',
            r'(?:52-?week|year)[^0-9]*high[:\s]+([0-9,]+(?:\.[0-9]+)?)',
        ]
        for pattern in high_patterns:
            high_match = re.search(pattern, page_text, re.IGNORECASE)
            if high_match:
                stock_data.price_performance.high_52w = parse_number(high_match.group(1))
                if stock_data.price_performance.high_52w:
                    break

        low_patterns = [
            r'52w[^0-9]*low[:\s]+([0-9,]+(?:\.[0-9]+)?)',
            r'low\s+\(52w\)[:\s]+([0-9,]+(?:\.[0-9]+)?)',
            r'(?:52-?week|year)[^0-9]*low[:\s]+([0-9,]+(?:\.[0-9]+)?)',
        ]
        for pattern in low_patterns:
            low_match = re.search(pattern, page_text, re.IGNORECASE)
            if low_match:
                stock_data.price_performance.low_52w = parse_number(low_match.group(1))
                if stock_data.price_performance.low_52w:
                    break

        # Try to extract other time period changes from tables
        change_cells = soup.find_all('td')
        for i, cell in enumerate(change_cells):
            cell_text = clean_text(cell.get_text()) or ""
            cell_text_lower = cell_text.lower()
            value_text = ""

            # Look for next sibling with percentage value
            if i + 1 < len(change_cells):
                next_cell = change_cells[i + 1]
                next_text = clean_text(next_cell.get_text()) or ""
                if '%' in next_text:
                    value_text = next_text

            # 1-month change
            if '1 month' in cell_text_lower and value_text and not stock_data.price_performance.change_1m:
                stock_data.price_performance.change_1m = parse_percentage(value_text)

            # 3-month change
            if '3 month' in cell_text_lower and value_text and not stock_data.price_performance.change_3m:
                stock_data.price_performance.change_3m = parse_percentage(value_text)

            # 6-month change
            if '6 month' in cell_text_lower and value_text and not stock_data.price_performance.change_6m:
                stock_data.price_performance.change_6m = parse_percentage(value_text)

            # 1-year change
            if '1 year' in cell_text_lower and value_text and not stock_data.price_performance.change_1y:
                stock_data.price_performance.change_1y = parse_percentage(value_text)

            # Last trading date
            if 'last' in cell_text_lower and ('date' in cell_text_lower or 'trading' in cell_text_lower):
                if i + 1 < len(change_cells):
                    date_text = clean_text(change_cells[i + 1].get_text())
                    if date_text:
                        stock_data.price_performance.last_date = date_text


class FinanceScraper(BaseScraper):
    """Scrape financial data from all financial pages."""
    
    async def scrape(self, stock_config: Dict, stock_data: StockData) -> None:
        # Initialize all financial dictionaries
        fin = stock_data.financials
        fin.net_sales = {}
        fin.revenues = {}
        fin.cost_of_sales = {}
        fin.gross_profit = {}
        fin.operating_income = {}
        fin.net_income = {}
        fin.eps = {}
        fin.ebitda = {}
        fin.ebit = {}
        fin.ebitda_margin = {}
        fin.operating_margin = {}
        fin.net_margin = {}
        fin.roe = {}
        fin.roa = {}
        fin.roce = {}
        fin.net_debt = {}
        fin.total_assets = {}
        fin.total_liabilities = {}
        fin.shareholders_equity = {}
        fin.cash_and_equivalents = {}
        fin.total_debt = {}
        fin.working_capital = {}
        fin.operating_cash_flow = {}
        fin.free_cash_flow = {}
        fin.capex = {}
        fin.dividends_paid = {}
        fin.debt_to_equity = {}
        fin.current_ratio = {}
        
        # Scrape all financial pages concurrently
        pages = [
            ('finances/', 'forecasts'),
            ('finances-income-statement/', 'income'),
            ('finances-balance-sheet/', 'balance'),
            ('finances-cash-flow-statement/', 'cashflow'),
            ('finances-ratios/', 'ratios'),
        ]
        
        for page_suffix, page_type in pages:
            url = f"{BASE_URL}/{stock_config['url_code']}/{page_suffix}"
            soup = await self.get_soup(url)
            if soup:
                self._parse_financial_page(soup, fin, page_type)
    
    def _parse_financial_page(self, soup, fin: FinancialEstimates, page_type: str) -> None:
        """Parse financial page based on type."""
        tables = soup.find_all('table', class_=re.compile(r'table'))
        for table in tables:
            self._parse_financial_table(table, fin, page_type)
    
    def _parse_financial_table(self, table, fin: FinancialEstimates, page_type: str) -> None:
        """Parse financial table - extracts data-raw attributes for precise values."""
        rows = table.find_all('tr')
        if not rows:
            return
        
        # Find header row with years
        years = []
        for row in rows[:3]:
            cells = row.find_all(['th', 'td'])
            for cell in cells:
                text = clean_text(cell.get_text())
                if text and re.match(r'^20\d{2}[eE]?$', text.strip()):
                    years.append(text.rstrip('eE'))
            if years:
                break
        
        if not years:
            return
        
        for row in rows:
            cells = row.find_all(['td', 'th'])
            if len(cells) < 2:
                continue
            
            label = clean_text(cells[0].get_text()) or ""
            label_lower = label.lower().strip()
            
            # Skip header rows
            if any(y in label for y in years) or 'fiscal' in label_lower:
                continue
            
            # Skip CAGR/growth rate rows (these contain % changes, not absolute values)
            if any(skip in label_lower for skip in ['cagr', 'growth', 'yr.', '1 yr', '2 yr', '3 yr', '5 yr']):
                continue
            
            # Extract values from data cells
            year_idx = 0
            for cell in cells[1:]:
                if year_idx >= len(years):
                    break
                year = years[year_idx]
                
                # Try to get precise value from data-raw attribute
                currency_span = cell.find('span', class_='js-currency-type')
                if currency_span and currency_span.get('data-raw'):
                    try:
                        value = float(currency_span['data-raw'])
                    except:
                        value = None
                else:
                    # Fallback to text parsing
                    cell_text = clean_text(cell.get_text())
                    if not cell_text or cell_text == '-':
                        year_idx += 1
                        continue
                    value = parse_number(cell_text)
                
                if value is not None:
                    self._assign_value(fin, label_lower, year, value, page_type)
                
                year_idx += 1
    
    def _assign_value(self, fin: FinancialEstimates, label: str, year: str, value: float, page_type: str) -> None:
        """Assign value to appropriate field based on label."""
        # Income Statement fields
        if label == 'total revenues' or label == 'revenues':
            fin.revenues[year] = value
        elif 'net sales' in label:
            fin.net_sales[year] = value
        elif 'cost of sales' in label or 'cost of goods' in label:
            fin.cost_of_sales[year] = value
        elif label == 'gross profit':
            fin.gross_profit[year] = value
        elif 'operating income' in label or 'operating profit' in label:
            fin.operating_income[year] = value
        elif label == 'ebitda':
            fin.ebitda[year] = value
        elif label == 'ebit':
            fin.ebit[year] = value
        elif 'net income' in label or 'net profit' in label or label == 'net income group share':
            fin.net_income[year] = value
        # EPS - match various formats
        elif label == 'eps' or 'earnings per share' in label or 'net eps' in label or 'diluted eps' in label or 'basic eps' in label:
            fin.eps[year] = value
        
        # Balance Sheet fields
        elif label == 'total assets':
            fin.total_assets[year] = value
        elif label == 'total liabilities' or 'total debt and liabilities' in label:
            fin.total_liabilities[year] = value
        # Shareholders equity - match various formats
        elif 'total common equity' in label or 'total equity' in label or ('shareholder' in label and 'equity' in label):
            fin.shareholders_equity[year] = value
        elif 'net debt' in label or 'net financial debt' in label:
            fin.net_debt[year] = value
        elif 'total cash' in label or ('cash' in label and 'short term' in label):
            fin.cash_and_equivalents[year] = value
        elif label == 'total debt' or 'financial debt' in label:
            fin.total_debt[year] = value
        elif 'working capital' in label:
            fin.working_capital[year] = value
        
        # Cash Flow fields
        elif 'operating cash flow' in label or 'cash from operating' in label:
            fin.operating_cash_flow[year] = value
        elif 'capex' in label or 'capital expenditure' in label:
            fin.capex[year] = value
        elif 'free cash flow' in label or 'levered free cash flow' in label:
            fin.free_cash_flow[year] = value
        elif 'dividends paid' in label or 'dividend paid' in label:
            fin.dividends_paid[year] = value
        
        # Ratio fields
        elif 'ebitda margin' in label:
            fin.ebitda_margin[year] = value
        # Operating margin - also match EBIT margin
        elif 'operating margin' in label or 'ebit margin' in label:
            fin.operating_margin[year] = value
        elif 'net margin' in label or 'net income margin' in label:
            fin.net_margin[year] = value
        elif label == 'roe' or 'return on equity' in label:
            fin.roe[year] = value
        elif label == 'roa' or 'return on assets' in label:
            fin.roa[year] = value
        # ROCE - match "return on total capital"
        elif label == 'roce' or 'return on capital' in label or 'return on total capital' in label:
            fin.roce[year] = value
        elif 'debt/equity' in label or 'debt to equity' in label or 'lt debt/equity' in label:
            fin.debt_to_equity[year] = value
        elif 'current ratio' in label:
            fin.current_ratio[year] = value


class ConsensusScraper(BaseScraper):
    """Scrape analyst consensus data."""

    async def scrape(self, stock_config: Dict, stock_data: StockData) -> None:
        url = f"{BASE_URL}/{stock_config['url_code']}/consensus/"
        soup = await self.get_soup(url)

        if not soup:
            logger.error("Failed to fetch consensus page")
            return

        # Look for consensus rating in large text or badges
        for tag in ['h2', 'h3', 'span', 'div']:
            elems = soup.find_all(tag)
            for elem in elems:
                text = clean_text(elem.get_text())
                if text and text.upper() in ['BUY', 'HOLD', 'SELL', 'OUTPERFORM', 'UNDERPERFORM', 'ACCUMULATE', 'REDUCE']:
                    stock_data.consensus.consensus = text.upper()
                    break
            if stock_data.consensus.consensus:
                break

        # Parse consensus table
        tables = soup.find_all('table')
        for table in tables:
            for row in table.find_all('tr'):
                cells = row.find_all(['td', 'th'])
                if len(cells) >= 2:
                    label = clean_text(cells[0].get_text()) or ""
                    value_text = clean_text(cells[-1].get_text()) or ""
                    label_lower = label.lower()

                    if 'target' in label_lower and 'price' in label_lower:
                        if 'average' in label_lower or 'mean' in label_lower:
                            stock_data.consensus.target_price_avg = parse_number(value_text)
                        elif 'high' in label_lower or 'maximum' in label_lower:
                            stock_data.consensus.target_price_high = parse_number(value_text)
                        elif 'low' in label_lower or 'minimum' in label_lower:
                            stock_data.consensus.target_price_low = parse_number(value_text)
                    elif 'analyst' in label_lower or 'coverage' in label_lower:
                        num = parse_number(value_text)
                        if num:
                            stock_data.consensus.num_analysts = int(num)
                    elif 'upside' in label_lower or 'potential' in label_lower or 'downside' in label_lower:
                        stock_data.consensus.upside_pct = parse_percentage(value_text)

        # Fallback: search page text for analyst data
        page_text = soup.get_text()
        if not stock_data.consensus.num_analysts:
            analyst_patterns = [
                r'(\d+)\s*analyst',
                r'coverage[:\s]*(\d+)',
                r'tracked[^0-9]*(\d+)',
            ]
            for pattern in analyst_patterns:
                match = re.search(pattern, page_text, re.IGNORECASE)
                if match:
                    stock_data.consensus.num_analysts = int(match.group(1))
                    break

        if not stock_data.consensus.target_price_avg:
            target_patterns = [
                r'target[^0-9]*([0-9,]+(?:\.[0-9]+)?)',
                r'price target[:\s]*([0-9,]+(?:\.[0-9]+)?)',
            ]
            for pattern in target_patterns:
                match = re.search(pattern, page_text, re.IGNORECASE)
                if match:
                    stock_data.consensus.target_price_avg = parse_number(match.group(1))
                    break


class RatingsScraper(BaseScraper):
    """Scrape ratings from valuation page."""

    async def scrape(self, stock_config: Dict, stock_data: StockData) -> None:
        url = f"{BASE_URL}/{stock_config['url_code']}/valuation/"
        soup = await self.get_soup(url)

        if not soup:
            logger.error("Failed to fetch valuation page for ratings")
            return

        page_text = soup.get_text()

        # Look for ratings in tables
        tables = soup.find_all('table')
        for table in tables:
            for row in table.find_all('tr'):
                cells = row.find_all(['td', 'th'])
                if len(cells) >= 2:
                    label = clean_text(cells[0].get_text()) or ""
                    value_text = clean_text(cells[-1].get_text()) or ""
                    label_lower = label.lower()

                    if 'trader' in label_lower and 'rating' in label_lower:
                        # Rating might be text (BUY, HOLD, SELL) or stars
                        if value_text:
                            stock_data.ratings.trader_rating = value_text
                    elif 'investor' in label_lower and 'rating' in label_lower:
                        if value_text:
                            stock_data.ratings.investor_rating = value_text
                    elif 'global' in label_lower and 'rating' in label_lower:
                        if value_text:
                            stock_data.ratings.global_rating = value_text
                    elif 'quality' in label_lower and 'rating' in label_lower:
                        if value_text:
                            stock_data.ratings.quality_rating = value_text
                    elif 'esg' in label_lower or 'sustainability' in label_lower:
                        if value_text:
                            stock_data.ratings.esg_rating = value_text

        # Fallback: search page text for rating keywords
        rating_keywords = {
            'trader_rating': ['trader rating', 'trading rating', 'short-term'],
            'investor_rating': ['investor rating', 'long-term rating'],
            'global_rating': ['global rating', 'overall rating', 'rating'],
            'quality_rating': ['quality rating', 'quality score'],
            'esg_rating': ['esg rating', 'esg score', 'sustainability rating']
        }

        for rating_field, keywords in rating_keywords.items():
            if not getattr(stock_data.ratings, rating_field):
                for keyword in keywords:
                    pattern = f'{keyword}[:\\s]*([A-Z]+|\\*+|★+|[0-9.]+)'
                    match = re.search(pattern, page_text, re.IGNORECASE)
                    if match:
                        value = match.group(1).strip()
                        if value:
                            setattr(stock_data.ratings, rating_field, value)
                            break


class ValuationScraper(BaseScraper):
    """Scrape valuation metrics including historical data."""
    
    async def scrape(self, stock_config: Dict, stock_data: StockData) -> None:
        url = f"{BASE_URL}/{stock_config['url_code']}/valuation/"
        soup = await self.get_soup(url)
        
        if not soup:
            logger.error("Failed to fetch valuation page")
            return
        
        # Initialize historical dicts
        val = stock_data.valuation
        val.pe_ratio_hist = {}
        val.pbr_hist = {}
        val.peg_hist = {}
        val.ev_revenue_hist = {}
        val.ev_ebitda_hist = {}
        val.ev_ebit_hist = {}
        val.ev_fcf_hist = {}
        val.fcf_yield_hist = {}
        val.dividend_per_share_hist = {}
        val.eps_hist = {}
        val.distribution_rate_hist = {}
        
        # Find the main valuation table with years
        tables = soup.find_all('table', class_=re.compile(r'table'))
        for table in tables:
            self._parse_historical_table(table, val)
    
    def _parse_historical_table(self, table, val: ValuationMetrics) -> None:
        """Parse historical valuation table with year columns."""
        rows = table.find_all('tr')
        if not rows:
            return
        
        # Find header row with years
        years = []
        for row in rows[:3]:
            cells = row.find_all(['th', 'td'])
            for cell in cells:
                text = clean_text(cell.get_text())
                if text and re.match(r'^20\d{2}$', text):
                    years.append(text)
            if years:
                break
        
        if not years:
            return
        
        # Parse each data row
        for row in rows:
            cells = row.find_all(['td', 'th'])
            if len(cells) < 2:
                continue
            
            label = clean_text(cells[0].get_text()) or ""
            label_lower = label.lower()
            
            # Skip header rows
            if any(y in label for y in years) or 'fiscal' in label_lower:
                continue
            
            # Extract values for each year
            values = []
            for cell in cells[1:]:
                text = clean_text(cell.get_text())
                if text and text != '-':
                    # Handle percentage
                    if '%' in text:
                        values.append(parse_percentage(text))
                    else:
                        values.append(parse_number(text.replace('x', '')))
                else:
                    values.append(None)
            
            # Map values to years
            for i, year in enumerate(years):
                if i < len(values) and values[i] is not None:
                    value = values[i]
                    
                    if 'p/e ratio' in label_lower:
                        val.pe_ratio_hist[year] = value
                        if year == '2026' and val.pe_ratio is None:
                            val.pe_ratio = value
                    elif label_lower == 'pbr' or 'price to book' in label_lower:
                        val.pbr_hist[year] = value
                        if val.price_to_book is None:
                            val.price_to_book = value
                    elif label_lower == 'peg':
                        val.peg_hist[year] = value
                    elif 'ev / revenue' in label_lower or 'ev/revenue' in label_lower:
                        val.ev_revenue_hist[year] = value
                    elif 'ev / ebitda' in label_lower or 'ev/ebitda' in label_lower:
                        val.ev_ebitda_hist[year] = value
                        if val.ev_ebitda is None:
                            val.ev_ebitda = value
                    elif 'ev / ebit' in label_lower or 'ev/ebit' in label_lower:
                        val.ev_ebit_hist[year] = value
                    elif 'ev / fcf' in label_lower or 'ev/fcf' in label_lower:
                        val.ev_fcf_hist[year] = value
                    elif 'fcf yield' in label_lower:
                        val.fcf_yield_hist[year] = value
                    elif 'dividend per share' in label_lower:
                        val.dividend_per_share_hist[year] = value
                    # EPS - match various formats
                    elif label_lower == 'eps' or 'earnings per share' in label_lower or 'net eps' in label_lower or 'diluted eps' in label_lower:
                        val.eps_hist[year] = value
                    elif 'distribution rate' in label_lower or 'payout' in label_lower:
                        val.distribution_rate_hist[year] = value
                    elif 'rate of return' in label_lower or 'yield' in label_lower:
                        if val.dividend_yield is None and year == '2026':
                            val.dividend_yield = value
                    elif 'nbr of stock' in label_lower or 'number of share' in label_lower:
                        if val.num_shares is None:
                            val.num_shares = value


class DividendScraper(BaseScraper):
    """Scrape dividend historical data from valuation-dividend page."""
    
    async def scrape(self, stock_config: Dict, stock_data: StockData) -> None:
        url = f"{BASE_URL}/{stock_config['url_code']}/valuation-dividend/"
        soup = await self.get_soup(url)
        
        if not soup:
            logger.error("Failed to fetch valuation-dividend page")
            return
        
        val = stock_data.valuation
        # Initialize if not already done
        if val.dividend_per_share_hist is None:
            val.dividend_per_share_hist = {}
        if val.eps_hist is None:
            val.eps_hist = {}
        if val.distribution_rate_hist is None:
            val.distribution_rate_hist = {}
        
        # Find the dividend table by ID
        table = soup.find('table', id='dividendTable')
        if not table:
            # Fallback: search all tables
            tables = soup.find_all('table', class_=re.compile(r'table'))
            for t in tables:
                if 'dividend' in t.get_text().lower():
                    table = t
                    break
        
        if table:
            self._parse_dividend_table(table, val)
    
    def _parse_dividend_table(self, table, val: ValuationMetrics) -> None:
        """Parse dividend table with year columns."""
        rows = list(table.find_all('tr'))
        if not rows:
            return
        
        # Find header row with years
        years = []
        for row in rows[:2]:
            cells = row.find_all(['th', 'td'])
            for cell in cells:
                text = clean_text(cell.get_text())
                if text and re.match(r'^20\d{2}$', text.strip()):
                    years.append(text.strip())
            if years:
                break
        
        if not years:
            return
        
        # Parse data rows
        for row in rows[1:]:
            cells = row.find_all(['td', 'th'])
            if len(cells) < 2:
                continue
            
            label = clean_text(cells[0].get_text()) or ""
            label_lower = label.lower()
            
            # Skip header rows
            if any(y in label for y in years) or 'fiscal' in label_lower:
                continue
            
            # Extract values for each year column
            values = []
            for cell in cells[1:]:
                text = clean_text(cell.get_text())
                if text and text != '-':
                    if '%' in text:
                        values.append(parse_percentage(text))
                    else:
                        values.append(parse_number(text))
                else:
                    values.append(None)
            
            # Map values to years
            for i, year in enumerate(years):
                if i < len(values) and values[i] is not None:
                    value = values[i]
                    
                    if 'dividend per share' in label_lower:
                        val.dividend_per_share_hist[year] = value
                    # EPS - match various formats from dividend page
                    elif label_lower == 'eps' or 'earnings per share' in label_lower or 'net eps' in label_lower or 'diluted eps' in label_lower:
                        val.eps_hist[year] = value
                    elif 'distribution rate' in label_lower or 'payout' in label_lower:
                        val.distribution_rate_hist[year] = value
                    elif 'rate of return' in label_lower or 'yield' in label_lower:
                        if year == '2026' and val.dividend_yield is None:
                            val.dividend_yield = value
                    elif 'reference price' in label_lower:
                        pass  # Skip reference price


class CalendarScraper(BaseScraper):
    """Scrape calendar events (dividends, earnings)."""

    async def scrape(self, stock_config: Dict, stock_data: StockData) -> None:
        url = f"{BASE_URL}/{stock_config['url_code']}/calendar/"
        soup = await self.get_soup(url)

        if not soup:
            logger.error("Failed to fetch calendar page")
            return

        # Parse all tables looking for dividend/earnings info
        tables = soup.find_all('table')
        for table in tables:
            rows = table.find_all('tr')
            for row_idx, row in enumerate(rows):
                cells = row.find_all(['td', 'th'])
                row_text = row.get_text().lower()

                # For each cell in the row
                for i, cell in enumerate(cells):
                    text = clean_text(cell.get_text())
                    if not text:
                        continue

                    # Date pattern (various formats)
                    date_match = re.search(r'(\d{1,2}[/-]\d{1,2}[/-]\d{2,4})|(\w+\.\s+\d{1,2},?\s*\d{4})|(\d{4}-\d{2}-\d{2})', text)

                    if date_match:
                        date_str = date_match.group()
                        if 'ex-div' in row_text or 'ex div' in row_text or 'ex dividend' in row_text:
                            stock_data.calendar.ex_dividend_date = date_str
                        elif 'payment' in row_text or 'pay date' in row_text or 'paid' in row_text:
                            stock_data.calendar.dividend_payment_date = date_str
                        elif 'earning' in row_text or 'result' in row_text or 'earnings date' in row_text:
                            stock_data.calendar.next_earnings_date = date_str
                        elif 'dividend' in row_text and not stock_data.calendar.ex_dividend_date:
                            stock_data.calendar.ex_dividend_date = date_str

                    # Dividend amount (look for currency values in dividend rows)
                    if 'dividend' in row_text and not stock_data.calendar.dividend_amount:
                        amount = parse_number(text)
                        if amount and amount < 1000:  # Reasonable dividend per share
                            stock_data.calendar.dividend_amount = amount

        # Enhanced fallback: look for dividend information in tables with specific patterns
        page_text = soup.get_text()

        # Extract dividend payment date
        if not stock_data.calendar.dividend_payment_date:
            payment_patterns = [
                r'(?:payment|paid)[:\s]*(\d{1,2}[/-]\d{1,2}[/-]\d{2,4})',
                r'(?:payment|paid)[:\s]*(\d{4}-\d{2}-\d{2})',
                r'(?:payment|paid)[:\s]*(\w+\s+\d{1,2},?\s*\d{4})',
            ]
            for pattern in payment_patterns:
                match = re.search(pattern, page_text, re.IGNORECASE)
                if match:
                    stock_data.calendar.dividend_payment_date = match.group(1)
                    break

        # Extract dividend amount with better patterns
        if not stock_data.calendar.dividend_amount:
            amount_patterns = [
                r'dividend[^0-9]*([0-9,]+(?:\.[0-9]+)?)\s*(?:MAD|USD|EUR)',
                r'dividend per share[:\s]*([0-9,]+(?:\.[0-9]+)?)',
                r'amount[:\s]*([0-9,]+(?:\.[0-9]+)?)',
            ]
            for pattern in amount_patterns:
                match = re.search(pattern, page_text, re.IGNORECASE)
                if match:
                    amount = parse_number(match.group(1))
                    if amount and amount < 10000:  # Reasonable range
                        stock_data.calendar.dividend_amount = amount
                        break


class CompanyScraper(BaseScraper):
    """Scrape company profile information."""
    
    async def scrape(self, stock_config: Dict, stock_data: StockData) -> None:
        url = f"{BASE_URL}/{stock_config['url_code']}/company/"
        soup = await self.get_soup(url)
        
        if not soup:
            logger.error("Failed to fetch company page")
            return
        
        # Look for the company description - it's usually in a paragraph
        # that describes the business (not rating-related text)
        description_keywords = ['telecom', 'operator', 'mobile', 'telephony', 'internet', 
                                'services', 'network', 'customers', 'subscribers', 
                                'revenues', 'products', 'marketed']
        rating_keywords = ['super rating', 'weighted average', 'composite', 'rankings', 
                          'revisions', 'visibility', 'we recommend']
        
        # Search all text blocks
        for elem in soup.find_all(['p', 'div']):
            text = clean_text(elem.get_text())
            if not text or len(text) < 150:
                continue
            
            text_lower = text.lower()
            
            # Skip rating-related text
            if any(kw in text_lower for kw in rating_keywords):
                continue
            
            # Look for actual business description
            if any(kw in text_lower for kw in description_keywords):
                stock_data.company.description = text[:1000]
                break
        
        # Look for employee count in text format "Number of employees: 8,758"
        page_text = soup.get_text()
        emp_match = re.search(r'Number of employees[:\s]+([0-9,]+)', page_text, re.IGNORECASE)
        if emp_match:
            stock_data.company.employees = int(emp_match.group(1).replace(',', ''))
        
        # Also check for "Employees" followed by number
        if not stock_data.company.employees:
            emp_match2 = re.search(r'Employees\s*[:\s]*([0-9,]+)', page_text)
            if emp_match2:
                stock_data.company.employees = int(emp_match2.group(1).replace(',', ''))
        
        # Look for international revenue percentage
        intl_match = re.search(r'(\d+\.?\d*)\s*%\s*of\s*(?:net\s+)?sales.*abroad', page_text, re.IGNORECASE)
        if intl_match:
            stock_data.company.international_revenue_pct = float(intl_match.group(1))
        
        # Parse tables for employee count and other data
        tables = soup.find_all('table')
        for table in tables:
            for row in table.find_all('tr'):
                cells = row.find_all(['td', 'th'])
                if len(cells) >= 2:
                    label = clean_text(cells[0].get_text()) or ""
                    value = clean_text(cells[-1].get_text()) or ""
                    label_lower = label.lower()
                    
                    if 'employee' in label_lower or 'staff' in label_lower:
                        emp_num = parse_number(value)
                        if emp_num:
                            stock_data.company.employees = int(emp_num)
                    elif 'international' in label_lower and 'revenue' in label_lower:
                        stock_data.company.international_revenue_pct = parse_percentage(value)


class NewsScraper(BaseScraper):
    """Scrape news articles from the stock's news page."""

    async def scrape(self, stock_config: Dict, stock_data: StockData, fetch_full_articles: bool = False) -> None:
        url = f"{BASE_URL}/{stock_config['url_code']}/news/"
        soup = await self.get_soup(url)

        if not soup:
            logger.error("Failed to fetch news page")
            return

        articles = []

        # Primary Strategy: Parse the newsScreener table (MarketScreener's current layout)
        # News table has id="newsScreener" with rows containing date, title/link, source
        news_table = soup.find('table', id='newsScreener')
        if news_table:
            for row in news_table.find_all('tr'):
                article = self._parse_news_table_row(row)
                if article and article.title:
                    articles.append(article)
                if len(articles) >= 20:
                    break

        # Fallback Strategy 1: Look for any table with news links
        if not articles:
            for table in soup.find_all('table', class_=re.compile(r'table', re.IGNORECASE)):
                for row in table.find_all('tr'):
                    article = self._parse_news_table_row(row)
                    if article and article.title:
                        articles.append(article)
                    if len(articles) >= 20:
                        break
                if len(articles) >= 20:
                    break

        # Fallback Strategy 2: Find all links that look like news articles
        if not articles:
            all_links = soup.find_all('a', href=re.compile(r'/news/[a-z0-9-]+'))
            for link in all_links:
                href = link.get('href', '')
                title = clean_text(link.get_text())

                # Filter out navigation links, only keep actual news titles
                if not title or len(title) < 20:
                    continue
                # Skip menu/navigation links
                if any(skip in title.lower() for skip in ['all news', 'press releases', 'transcripts', 'insiders']):
                    continue

                article = NewsArticle(title=title, url=href)

                # Try to find date near the link (parent td/tr)
                parent = link.find_parent('tr') or link.find_parent('td')
                if parent:
                    date_elem = parent.find('span', class_='js-date-relative')
                    if date_elem and date_elem.get('data-utc-date'):
                        article.date = date_elem['data-utc-date']
                    else:
                        # Fallback: search for date text
                        date_match = re.search(
                            r'(\w{3}\.\s+\d{1,2}|\d{2}/\d{2}/\d{4}|\d{4}-\d{2}-\d{2})',
                            parent.get_text()
                        )
                        if date_match:
                            article.date = date_match.group(1)

                articles.append(article)
                if len(articles) >= 20:
                    break

        # Deduplicate by title
        seen_titles = set()
        unique_articles = []
        for a in articles:
            if a.title and a.title not in seen_titles:
                seen_titles.add(a.title)
                unique_articles.append(a)

        # Optionally fetch full article content
        if fetch_full_articles and unique_articles:
            logger.info(f"Fetching full content for {len(unique_articles)} articles...")
            for article in unique_articles:
                content = await self.fetch_full_article(article)
                if content:
                    article.full_content = content

        stock_data.news.articles = unique_articles[:20]
        stock_data.news.total_count = len(unique_articles)

        logger.info(f"Found {len(unique_articles)} news articles")

    def _parse_news_table_row(self, row) -> Optional[NewsArticle]:
        """Parse a news table row from MarketScreener's newsScreener table.
        
        Expected structure:
        <tr>
            <td><span class="js-date-relative" data-utc-date="2026-03-11T18:02:10+00:00">Mar. 11</span></td>
            <td><a href="/news/...">News Title</a></td>
            <td><span class="badge" title="Source">CI</span></td>
        </tr>
        """
        article = NewsArticle()

        # Find the news link (href contains /news/)
        link = row.find('a', href=re.compile(r'/news/'))
        if not link:
            return None

        title = clean_text(link.get_text())
        if not title or len(title) < 15:
            return None

        article.title = title
        article.url = link.get('href', '')

        # Extract date from js-date-relative span (preferred) or data-utc-date attribute
        date_elem = row.find('span', class_='js-date-relative')
        if date_elem:
            # Prefer the ISO date from data-utc-date attribute
            if date_elem.get('data-utc-date'):
                article.date = date_elem['data-utc-date']
            else:
                article.date = clean_text(date_elem.get_text())

        # Extract source from badge span
        source_elem = row.find('span', class_=re.compile(r'badge'))
        if source_elem:
            # Get source from title attribute if available
            source_title = source_elem.get('title')
            if source_title:
                article.source = source_title
            else:
                article.source = clean_text(source_elem.get_text())

        return article if article.title else None
    
    async def fetch_full_article(self, article: NewsArticle) -> Optional[str]:
        """Fetch full article content from MarketScreener news page using JSON-LD schema.
        
        Extracts 'articleBody' from the NewsArticle structured data in the page.
        """
        if not article.url:
            return None
        
        # Handle relative URLs
        url = article.url
        if url.startswith('/news/'):
            url = f"https://www.marketscreener.com{url}"
        elif not url.startswith('http'):
            url = f"https://www.marketscreener.com/news/{url}"
        
        try:
            soup = await self.get_soup(url)
            if not soup:
                return None
            
            # Look for JSON-LD NewsArticle schema
            json_ld_scripts = soup.find_all('script', type='application/ld+json')
            for script in json_ld_scripts:
                try:
                    data = json.loads(script.string)
                    # Handle both single object and array of objects
                    if isinstance(data, list):
                        data = data[0]
                    
                    if data.get('@type') == 'NewsArticle' and 'articleBody' in data:
                        content = data['articleBody']
                        # Only return if it's actual readable content (not tokens)
                        if content and len(content) > 50 and ' ' in content:
                            return content
                except (json.JSONDecodeError, KeyError, TypeError):
                    continue
            
            # Fallback: look for article content in specific divs (but be selective)
            # Try common article body selectors
            selectors = [
                'div.article-body',
                'div.news-body',
                'div.article-content',
                'article',
                'div[itemprop="articleBody"]',
            ]
            
            for selector in selectors:
                elements = soup.select(selector)
                for elem in elements:
                    text = clean_text(elem.get_text())
                    # Only return if it's actual readable content (> 100 chars with spaces)
                    if text and len(text) > 100 and ' ' in text:
                        # Make sure it's not just tokens/encoded content
                        if not self._looks_like_token(text):
                            return text
            
            # If nothing found, return None (don't return token-like content)
            return None
        
        except Exception as e:
            logger.error(f"Error fetching full article from {url}: {e}")
            return None
    
    def _looks_like_token(self, text: str) -> bool:
        """Check if text looks like an encoded token rather than actual content."""
        # Tokens usually have:
        # - High ratio of special characters
        # - No punctuation like . ! ? at proper places
        # - Lots of underscores and numbers
        # - Very short segments between spaces
        
        if not text or len(text) < 50:
            return True
        
        # Check if it's mostly a single "word" (no spaces or few spaces)
        words = text.split()
        if len(words) < 3:  # Too few words
            return True
        
        # Check for token patterns (continuous alphanumeric with underscores/dots)
        token_pattern = re.compile(r'^[a-zA-Z0-9_.]+$')
        if token_pattern.match(text.split()[0]):
            # Looks like a token word
            return True
        
        # Good content should have normal sentences
        # Check for sentence-like patterns (Capital letter + spaces + punctuation)
        if not re.search(r'[A-Z][a-z\s]+[.!?]', text):
            return True  # Doesn't look like normal sentences
        
        return False


# =============================================================================
# Main Async Orchestrator
# =============================================================================

class MarketScreenerScraper:
    """Main async orchestrator for all scrapers."""
    
    def __init__(self):
        self.client = AsyncHTTPClient()
        self.quote_scraper = QuoteScraper(self.client)
        self.finance_scraper = FinanceScraper(self.client)
        self.consensus_scraper = ConsensusScraper(self.client)
        self.ratings_scraper = RatingsScraper(self.client)
        self.valuation_scraper = ValuationScraper(self.client)
        self.dividend_scraper = DividendScraper(self.client)
        self.calendar_scraper = CalendarScraper(self.client)
        self.company_scraper = CompanyScraper(self.client)
        self.news_scraper = NewsScraper(self.client)
    
    async def scrape_stock(self, ticker: str) -> Optional[StockData]:
        """Scrape all data for a given stock asynchronously."""
        if ticker not in STOCKS:
            logger.error(f"Unknown ticker: {ticker}")
            return None
        
        stock_config = STOCKS[ticker]
        stock_data = StockData()
        
        logger.info(f"Starting async scrape for {ticker}")
        
        # Run all scrapers concurrently using asyncio.gather
        await asyncio.gather(
            self.quote_scraper.scrape(stock_config, stock_data),
            self.finance_scraper.scrape(stock_config, stock_data),
            self.consensus_scraper.scrape(stock_config, stock_data),
            self.ratings_scraper.scrape(stock_config, stock_data),
            self.valuation_scraper.scrape(stock_config, stock_data),
            self.dividend_scraper.scrape(stock_config, stock_data),
            self.calendar_scraper.scrape(stock_config, stock_data),
            self.company_scraper.scrape(stock_config, stock_data),
            self.news_scraper.scrape(stock_config, stock_data),
        )
        
        logger.info(f"Completed async scrape for {ticker}")
        return stock_data
    
    async def scrape_all_stocks(self) -> List[StockData]:
        """Scrape all configured stocks concurrently."""
        tasks = [self.scrape_stock(ticker) for ticker in STOCKS]
        results = await asyncio.gather(*tasks, return_exceptions=True)
        
        # Filter out None and exceptions
        return [r for r in results if isinstance(r, StockData)]
    
    async def close(self):
        """Close HTTP client."""
        await self.client.close()


# =============================================================================
# Export Functions
# =============================================================================

def save_to_csv(data: List[StockData], filepath: str = "testing/stock_data.csv") -> None:
    """Save scraped data to CSV file."""
    if not data:
        logger.warning("No data to save")
        return
    
    # Ensure directory exists
    os.makedirs(os.path.dirname(filepath) if os.path.dirname(filepath) else ".", exist_ok=True)
    
    # Flatten all records
    flat_data = [d.to_flat_dict() for d in data]
    
    # Get all unique keys
    all_keys = set()
    for record in flat_data:
        all_keys.update(record.keys())
    
    fieldnames = sorted(all_keys)
    
    with open(filepath, 'w', newline='', encoding='utf-8') as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(flat_data)
    
    logger.info(f"Saved CSV to {filepath}")
    
    # Print summary of scraped data
    for record in flat_data:
        print(f"\nStock Summary:")
        print(f"  Ticker: {record.get('identity_ticker', 'N/A')}")
        print(f"  Name: {record.get('identity_full_name', 'N/A')}")
        print(f"  Price: {record.get('price_last_price', 'N/A')} {record.get('identity_currency', '')}")
        print(f"  Change 1D: {record.get('price_change_1d', 'N/A')}%")
        print(f"  Market Cap: {record.get('valuation_market_cap', 'N/A')}")
        print(f"  P/E Ratio: {record.get('valuation_pe_ratio', 'N/A')}")
        print(f"  Dividend Yield: {record.get('valuation_dividend_yield', 'N/A')}%")


def save_to_json(data: List[StockData], filepath: str = "testing/stock_data.json") -> None:
    """Save scraped data to JSON file."""
    if not data:
        logger.warning("No data to save")
        return
    
    # Ensure directory exists
    os.makedirs(os.path.dirname(filepath) if os.path.dirname(filepath) else ".", exist_ok=True)
    
    json_data = {
        "scrape_info": {
            "timestamp": datetime.utcnow().isoformat() + "Z",
            "num_stocks": len(data)
        },
        "stocks": [d.to_dict() for d in data]
    }
    
    with open(filepath, 'w', encoding='utf-8') as f:
        json.dump(json_data, f, indent=2, ensure_ascii=False)
    
    logger.info(f"Saved JSON to {filepath}")


# =============================================================================
# Main Entry Point
# =============================================================================

async def async_main():
    """Async main entry point."""
    if not HAS_DEPENDENCIES:
        print("Error: Missing required dependencies.")
        print("Please install with: pip install aiohttp beautifulsoup4 lxml")
        return
    
    print("=" * 60)
    print("MarketScreener Stock Scraper (Async)")
    print("=" * 60)
    
    scraper = MarketScreenerScraper()
    
    try:
        # Scrape all configured stocks concurrently
        results = await scraper.scrape_all_stocks()
        
        if results:
            # Save to both CSV and JSON
            save_to_csv(results, "testing/stock_data.csv")
            save_to_json(results, "testing/stock_data.json")
            
            print("\n" + "=" * 60)
            print(f"Successfully scraped {len(results)} stock(s)")
            print("Output files:")
            print("  - testing/stock_data.csv")
            print("  - testing/stock_data.json")
            print("=" * 60)
        else:
            print("No data was scraped")
            
    except Exception as e:
        logger.error(f"Scraping failed: {e}")
        raise
    finally:
        await scraper.close()


def main():
    """Synchronous wrapper for async main."""
    asyncio.run(async_main())


if __name__ == "__main__":
    main()
