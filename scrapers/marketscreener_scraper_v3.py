"""
MarketScreener Scraper V3 - With Selenium for JavaScript Rendering
===================================================================
Uses Selenium to wait for JavaScript-rendered content (Market Cap, P/E, etc.)
Then uses BeautifulSoup for fast table parsing (historical data).

Installation:
    pip install selenium webdriver-manager

Usage:
    python scrapers/marketscreener_scraper_v3.py --symbol IAM
"""

import re
import time
import logging
import json
from datetime import datetime
from pathlib import Path
from typing import Optional, Dict, Any, List
from dataclasses import dataclass, field, asdict
import argparse

try:
    from selenium import webdriver
    from selenium.webdriver.common.by import By
    from selenium.webdriver.support.ui import WebDriverWait
    from selenium.webdriver.support import expected_conditions as EC
    from selenium.webdriver.chrome.service import Service
    from selenium.webdriver.chrome.options import Options
    from webdriver_manager.chrome import ChromeDriverManager
    from bs4 import BeautifulSoup
    HAS_DEPENDENCIES = True
except ImportError as e:
    HAS_DEPENDENCIES = False
    print("Missing dependencies. Install with:")
    print("pip install selenium webdriver-manager beautifulsoup4 lxml")
    print(f"\nError: {e}")
    exit(1)

# =============================================================================
# Configuration
# =============================================================================
_ROOT = Path(__file__).resolve().parent.parent
CONFIG_PATH = _ROOT / "data" / "scrapers" / "instruments_marketscreener.json"
DATA_DIR = _ROOT / "data" / "historical"
DATA_DIR.mkdir(parents=True, exist_ok=True)

BASE_URL = "https://www.marketscreener.com/quote/stock"

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# =============================================================================
# Data Model
# =============================================================================

@dataclass
class StockData:
    symbol: str
    scrape_timestamp: str = field(default_factory=lambda: datetime.utcnow().isoformat() + "Z")
    
    # Price & Market Data
    price: Optional[float] = None
    market_cap: Optional[float] = None
    volume: Optional[int] = None
    high_52w: Optional[float] = None
    low_52w: Optional[float] = None
    
    # Valuation Ratios
    pe_ratio: Optional[float] = None
    dividend_yield: Optional[float] = None
    price_to_book: Optional[float] = None
    
    # Consensus
    consensus: Optional[str] = None
    target_price: Optional[float] = None
    num_analysts: Optional[int] = None
    
    # Historical Data
    hist_revenue: Dict[str, float] = field(default_factory=dict)
    hist_net_income: Dict[str, float] = field(default_factory=dict)
    hist_eps: Dict[str, float] = field(default_factory=dict)
    hist_ebitda: Dict[str, float] = field(default_factory=dict)
    hist_fcf: Dict[str, float] = field(default_factory=dict)
    hist_ocf: Dict[str, float] = field(default_factory=dict)
    hist_capex: Dict[str, float] = field(default_factory=dict)
    
    scrape_warnings: List[str] = field(default_factory=list)
    
    def validate(self) -> None:
        """Validate scraped data."""
        if self.pe_ratio and self.pe_ratio > 300:
            self.scrape_warnings.append(f"Suspicious P/E: {self.pe_ratio}")
            self.pe_ratio = None
        
        if self.target_price and self.price:
            ratio = self.target_price / self.price
            if ratio > 100 or ratio < 0.01:
                self.scrape_warnings.append(f"Suspicious target price: {self.target_price}")
                self.target_price = None

# =============================================================================
# Parsing Utilities
# =============================================================================

def parse_number(text: Optional[str]) -> Optional[float]:
    """Parse numbers with K/M/B suffixes."""
    if not text:
        return None
    
    text = str(text).strip().upper()
    
    mult = 1
    if text.endswith('B'):
        mult = 1e9
        text = text[:-1]
    elif text.endswith('M'):
        mult = 1e6
        text = text[:-1]
    elif text.endswith('K'):
        mult = 1e3
        text = text[:-1]
    
    text = re.sub(r'[^-0-9,.]', '', text).replace(',', '.')
    
    if text.count('.') > 1:
        parts = text.split('.')
        text = "".join(parts[:-1]) + "." + parts[-1]
    
    try:
        return float(text) * mult
    except (ValueError, AttributeError):
        return None

# =============================================================================
# Selenium Scraper
# =============================================================================

class SeleniumScraper:
    def __init__(self, headless: bool = True):
        """Initialize Selenium driver."""
        chrome_options = Options()
        if headless:
            chrome_options.add_argument('--headless=new')
        chrome_options.add_argument('--no-sandbox')
        chrome_options.add_argument('--disable-dev-shm-usage')
        chrome_options.add_argument('--disable-gpu')
        chrome_options.add_argument('--window-size=1920,1080')
        chrome_options.add_argument('--user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36')
        
        logger.info("🌐 Starting Chrome browser...")
        try:
            service = Service(ChromeDriverManager().install())
            self.driver = webdriver.Chrome(service=service, options=chrome_options)
            self.driver.set_page_load_timeout(30)
        except Exception as e:
            logger.error(f"Failed to start Chrome: {e}")
            logger.info("Trying with default Chrome driver...")
            self.driver = webdriver.Chrome(options=chrome_options)
    
    def scrape_main_page(self, data: StockData, url_code: str) -> None:
        """Scrape main quote page with JavaScript rendering."""
        url = f"{BASE_URL}/{url_code}/"
        
        logger.info(f"📄 Loading {url}")
        self.driver.get(url)
        
        # Wait for page to load (JavaScript rendering)
        logger.info("⏳ Waiting for JavaScript to render (5s)...")
        time.sleep(5)
        
        # Get page source after JavaScript rendering
        html = self.driver.page_source
        soup = BeautifulSoup(html, 'lxml')
        page_text = soup.get_text()
        
        # Price - look for the main quote
        for price_pattern in [
            r'(\d+\.?\d*)\s*MAD',
            r'Last\s*(?:Price|Quote)?[:\s]*(\d+\.?\d*)',
        ]:
            match = re.search(price_pattern, page_text, re.IGNORECASE)
            if match:
                price = parse_number(match.group(1))
                if price and 10 < price < 10000:  # Reasonable stock price range
                    data.price = price
                    logger.info(f"✓ Price: {price} MAD")
                    break
        
        # Market Cap - multiple patterns
        for mcap_pattern in [
            r'Market\s+Cap(?:italization)?[:\s]*([\d,.]+\s*[BMK])',
            r'Cap\.\s*Bourse[:\s]*([\d,.]+\s*[BMK])',
            r'Capitalisation[:\s]*([\d,.]+\s*[BMK])',
        ]:
            match = re.search(mcap_pattern, page_text, re.IGNORECASE)
            if match:
                mcap = parse_number(match.group(1))
                if mcap and mcap > 1e6:
                    data.market_cap = mcap
                    logger.info(f"✓ Market Cap: {mcap:,.0f} MAD")
                    break
        
        # P/E Ratio
        for pe_pattern in [
            r'P/E\s*Ratio?[:\s]*(\d+\.?\d*)',
            r'PER[:\s]*(\d+\.?\d*)',
        ]:
            match = re.search(pe_pattern, page_text, re.IGNORECASE)
            if match:
                pe = parse_number(match.group(1))
                if pe and 0.1 <= pe <= 300:
                    data.pe_ratio = pe
                    logger.info(f"✓ P/E Ratio: {pe}")
                    break
        
        # Dividend Yield
        for div_pattern in [
            r'Dividend\s+Yield[:\s]*(\d+\.?\d*)\s*%',
            r'Yield[:\s]*(\d+\.?\d*)\s*%',
        ]:
            match = re.search(div_pattern, page_text, re.IGNORECASE)
            if match:
                div_yield = parse_number(match.group(1))
                if div_yield and 0 <= div_yield <= 20:
                    data.dividend_yield = div_yield
                    logger.info(f"✓ Dividend Yield: {div_yield}%")
                    break
        
        # 52-week High/Low
        high_match = re.search(r'52.*?(?:Week|w).*?High[:\s]*([\d,.]+)', page_text, re.IGNORECASE)
        if high_match:
            high = parse_number(high_match.group(1))
            if high and data.price and 0.5 <= high / data.price <= 3:
                data.high_52w = high
                logger.info(f"✓ 52w High: {high}")
        
        low_match = re.search(r'52.*?(?:Week|w).*?Low[:\s]*([\d,.]+)', page_text, re.IGNORECASE)
        if low_match:
            low = parse_number(low_match.group(1))
            if low and data.price and 0.3 <= low / data.price <= 2:
                data.low_52w = low
                logger.info(f"✓ 52w Low: {low}")
    
    def scrape_finances_page(self, data: StockData, url_code: str) -> None:
        """Scrape financial tables."""
        url = f"{BASE_URL}/{url_code}/finances/"
        
        logger.info(f"📊 Loading financials...")
        self.driver.get(url)
        time.sleep(3)  # Wait for tables to load
        
        html = self.driver.page_source
        soup = BeautifulSoup(html, 'lxml')
        
        for table in soup.find_all('table'):
            rows = list(table.find_all('tr'))
            if not rows:
                continue
            
            header_row = rows[0]
            headers = [th.get_text(strip=True) for th in header_row.find_all(['th', 'td'])]
            
            years = []
            year_indices = []
            for i, h in enumerate(headers):
                if re.match(r'^20\d{2}$', h):
                    years.append(h)
                    year_indices.append(i)
            
            if not years:
                continue
            
            for row in rows[1:]:
                cells = row.find_all(['td', 'th'])
                if len(cells) < 2:
                    continue
                
                label = cells[0].get_text(strip=True).lower()
                target = None
                
                if any(t in label for t in ['revenue', 'sales', 'turnover']) and 'per share' not in label:
                    target = data.hist_revenue
                elif any(t in label for t in ['net income', 'net profit']) and 'margin' not in label:
                    target = data.hist_net_income
                elif 'eps' in label or 'earnings per share' in label:
                    target = data.hist_eps
                elif 'ebitda' in label and 'margin' not in label:
                    target = data.hist_ebitda
                elif 'free cash flow' in label or 'fcf' in label:
                    target = data.hist_fcf
                elif 'operating cash flow' in label and 'per share' not in label:
                    target = data.hist_ocf
                elif 'capex' in label or 'capital expenditure' in label:
                    target = data.hist_capex
                
                if target is not None:
                    for idx, year in zip(year_indices, years):
                        if idx < len(cells):
                            val = parse_number(cells[idx].get_text(strip=True))
                            if val is not None:
                                target[year] = val
    
    def scrape_consensus_page(self, data: StockData, url_code: str) -> None:
        """Scrape consensus page."""
        url = f"{BASE_URL}/{url_code}/consensus/"
        
        logger.info(f"📈 Loading consensus...")
        self.driver.get(url)
        time.sleep(3)
        
        html = self.driver.page_source
        soup = BeautifulSoup(html, 'lxml')
        page_text = soup.get_text()
        
        # Target price
        for pattern in [
            r'(?:Average|Mean|Consensus)\s+Target\s+Price[:\s]*([\d,.]+)',
        ]:
            match = re.search(pattern, page_text, re.IGNORECASE)
            if match:
                target = parse_number(match.group(1))
                if target and data.price and 0.3 <= target / data.price <= 5:
                    data.target_price = target
                    logger.info(f"✓ Target Price: {target}")
                    break
        
        # Consensus
        for keyword in ['BUY', 'HOLD', 'SELL', 'ACCUMULATE', 'OUTPERFORM']:
            if re.search(rf'\b{keyword}\b', page_text, re.IGNORECASE):
                data.consensus = keyword
                logger.info(f"✓ Consensus: {keyword}")
                break
    
    def scrape(self, symbol: str, url_code: str) -> StockData:
        """Main scraping orchestrator."""
        logger.info(f"\n{'='*60}")
        logger.info(f"Scraping {symbol} with Selenium")
        logger.info(f"{'='*60}")
        
        data = StockData(symbol=symbol)
        
        self.scrape_main_page(data, url_code)
        self.scrape_finances_page(data, url_code)
        self.scrape_consensus_page(data, url_code)
        
        data.validate()
        
        return data
    
    def close(self):
        """Close browser."""
        logger.info("🔒 Closing browser...")
        self.driver.quit()

# =============================================================================
# Main
# =============================================================================

def main():
    parser = argparse.ArgumentParser(description='MarketScreener Scraper V3 (Selenium)')
    parser.add_argument('--symbol', help='Stock symbol')
    parser.add_argument('--all', action='store_true', help='Scrape all symbols')
    parser.add_argument('--headful', action='store_true', help='Show browser (not headless)')
    args = parser.parse_args()
    
    with open(CONFIG_PATH, 'r') as f:
        instruments = json.load(f)['instruments']
    
    to_process = []
    if args.symbol:
        to_process = [i for i in instruments if i['symbol'].upper() == args.symbol.upper()]
        if not to_process:
            print(f"❌ Symbol {args.symbol} not found")
            return
    elif args.all:
        to_process = instruments
    else:
        print("\n📊 MarketScreener Scraper V3 (Selenium)")
        print("=" * 60)
        for i, inst in enumerate(instruments, 1):
            print(f"  [{i}] {inst['symbol']:5s} - {inst['name']}")
        
        try:
            choice = int(input("\nSelect number: ")) - 1
            to_process = [instruments[choice]]
        except (ValueError, IndexError):
            print("❌ Invalid selection")
            return
    
    scraper = SeleniumScraper(headless=not args.headful)
    
    try:
        for inst in to_process:
            stock_data = scraper.scrape(inst['symbol'], inst['url_code'])
            
            output_file = DATA_DIR / f"{inst['symbol']}_marketscreener_v3.json"
            with open(output_file, 'w') as f:
                json.dump(asdict(stock_data), f, indent=2, default=str)
            
            print(f"\n✅ Completed {inst['symbol']}")
            print(f"   Price: {stock_data.price} MAD" if stock_data.price else "   Price: N/A")
            print(f"   Market Cap: {stock_data.market_cap:,.0f} MAD" if stock_data.market_cap else "   Market Cap: N/A")
            print(f"   P/E: {stock_data.pe_ratio}" if stock_data.pe_ratio else "   P/E: N/A")
            print(f"   Div Yield: {stock_data.dividend_yield}%" if stock_data.dividend_yield else "   Div: N/A")
            print(f"   Revenue: {len(stock_data.hist_revenue)} years")
            print(f"   EPS: {len(stock_data.hist_eps)} years")
            
            total_fields = 13
            filled = sum([
                bool(stock_data.price), bool(stock_data.market_cap),
                bool(stock_data.pe_ratio), bool(stock_data.dividend_yield),
                bool(stock_data.high_52w), bool(stock_data.low_52w),
                bool(stock_data.consensus), bool(stock_data.target_price),
                bool(stock_data.hist_revenue), bool(stock_data.hist_net_income),
                bool(stock_data.hist_eps), bool(stock_data.hist_fcf),
                bool(stock_data.hist_ocf),
            ])
            quality = (filled / total_fields) * 100
            print(f"   Data Quality: {quality:.0f}% ({filled}/{total_fields})")
            print(f"   📁 Saved to: {output_file.name}")
    
    finally:
        scraper.close()

if __name__ == "__main__":
    main()
