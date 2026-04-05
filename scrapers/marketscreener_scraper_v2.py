"""
MarketScreener Stock Scraper V2 - Fixed for 2026 HTML Structure
==========================================================
Uses multiple extraction strategies:
1. JSON-LD structured data (most reliable)
2. Meta tags
3. Regex patterns on page text
4. Table parsing for historical data

Author: AI Agent
Date: 2026-04-05
"""

import re
import asyncio
import random
import logging
import json
from datetime import datetime
from pathlib import Path
from typing import Optional, Dict, Any, List
from dataclasses import dataclass, field, asdict
import argparse

try:
    import aiohttp
    from bs4 import BeautifulSoup
    HAS_DEPENDENCIES = True
except ImportError:
    HAS_DEPENDENCIES = False
    print("Missing dependencies. Install with: pip install aiohttp beautifulsoup4 lxml")
    exit(1)

# =============================================================================
# Configuration
# =============================================================================
_ROOT = Path(__file__).resolve().parent.parent
CONFIG_PATH = _ROOT / "data" / "scrapers" / "instruments_marketscreener.json"
DATA_DIR = _ROOT / "data" / "historical"
DATA_DIR.mkdir(parents=True, exist_ok=True)

BASE_URL = "https://www.marketscreener.com/quote/stock"

USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.3 Safari/605.1.15",
]

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# =============================================================================
# Data Architecture
# =============================================================================

@dataclass
class StockData:
    symbol: str
    scrape_timestamp: str = field(default_factory=lambda: datetime.now(datetime.UTC if hasattr(datetime, 'UTC') else None).isoformat() if hasattr(datetime, 'UTC') else datetime.utcnow().isoformat() + "Z")
    
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
    
    # Historical Data (year -> value)
    # NOTE: Units may be mixed (millions vs billions) - normalize in data_normalizer.py
    hist_revenue: Dict[str, float] = field(default_factory=dict)
    hist_net_income: Dict[str, float] = field(default_factory=dict)
    hist_eps: Dict[str, float] = field(default_factory=dict)
    hist_ebitda: Dict[str, float] = field(default_factory=dict)
    hist_fcf: Dict[str, float] = field(default_factory=dict)
    hist_ocf: Dict[str, float] = field(default_factory=dict)
    hist_capex: Dict[str, float] = field(default_factory=dict)
    
    # Metadata for data quality
    scrape_warnings: List[str] = field(default_factory=list)
    
    def validate(self) -> None:
        """Post-scrape validation to catch obvious errors."""
        
        # Check for suspicious P/E (likely a year)
        if self.pe_ratio and self.pe_ratio > 300:
            self.scrape_warnings.append(f"Suspicious P/E ratio: {self.pe_ratio} (likely a year)")
            self.pe_ratio = None
        
        # Check for suspicious target price (likely an ISIN code)
        if self.target_price and self.price:
            ratio = self.target_price / self.price
            if ratio > 100 or ratio < 0.01:
                self.scrape_warnings.append(
                    f"Suspicious target price: {self.target_price} (ratio to price: {ratio:.1f}x)"
                )
                self.target_price = None
        
        # Check for empty historical data
        if not any([self.hist_revenue, self.hist_net_income, self.hist_eps]):
            self.scrape_warnings.append("No historical financial data found")
        
        # Log warnings
        if self.scrape_warnings:
            for warning in self.scrape_warnings:
                logger.warning(f"⚠️  {self.symbol}: {warning}")

# =============================================================================
# Parsing Utilities
# =============================================================================

def parse_number(text: Optional[str]) -> Optional[float]:
    """Parse numbers with K/M/B suffixes and handle European format."""
    if not text:
        return None
    
    text = str(text).strip().upper()
    
    # Handle multipliers
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
    
    # Clean the string
    text = re.sub(r'[^-0-9,.]', '', text).replace(',', '.')
    
    # Handle multiple dots (European format like 1.234.567)
    if text.count('.') > 1:
        parts = text.split('.')
        text = "".join(parts[:-1]) + "." + parts[-1]
    
    try:
        return float(text) * mult
    except (ValueError, AttributeError):
        return None

def extract_json_ld(soup: BeautifulSoup) -> Dict[str, Any]:
    """Extract JSON-LD structured data from the page."""
    data = {}
    
    for script in soup.find_all('script', type='application/ld+json'):
        try:
            ld_data = json.loads(script.string)
            if ld_data.get('@type') == 'FinancialProduct':
                # Extract price and other data
                offers = ld_data.get('offers', {})
                if 'price' in offers:
                    data['price'] = parse_number(offers['price'])
                if 'identifier' in offers:
                    data['isin'] = offers['identifier']
                
                # Aggregate rating (consensus)
                agg_rating = ld_data.get('aggregateRating', {})
                if 'ratingValue' in agg_rating:
                    data['rating_value'] = float(agg_rating['ratingValue'])
                if 'ratingCount' in agg_rating:
                    data['num_analysts'] = int(agg_rating['ratingCount'])
        except (json.JSONDecodeError, TypeError, KeyError) as e:
            logger.debug(f"Failed to parse JSON-LD: {e}")
            continue
    
    return data

# =============================================================================
# Scraper Class
# =============================================================================

class MarketScreenerScraper:
    def __init__(self):
        self.session = None
    
    async def get(self, url: str) -> Optional[str]:
        """Fetch URL with retry logic."""
        if not self.session:
            self.session = aiohttp.ClientSession(
                headers={"User-Agent": random.choice(USER_AGENTS)}
            )
        
        await asyncio.sleep(random.uniform(1.5, 3.0))
        
        try:
            async with self.session.get(url, timeout=aiohttp.ClientTimeout(total=30)) as resp:
                if resp.status == 200:
                    return await resp.text()
                else:
                    logger.warning(f"HTTP {resp.status} for {url}")
        except Exception as e:
            logger.error(f"Error fetching {url}: {e}")
        
        return None
    
    async def scrape_main_page(self, data: StockData, url_code: str) -> None:
        """Scrape the main quote page."""
        url = f"{BASE_URL}/{url_code}/"
        html = await self.get(url)
        
        if not html:
            logger.error(f"Failed to fetch main page for {data.symbol}")
            return
        
        soup = BeautifulSoup(html, 'lxml')
        page_text = soup.get_text()
        
        # Strategy 1: JSON-LD structured data (most reliable)
        json_ld_data = extract_json_ld(soup)
        if json_ld_data.get('price'):
            data.price = json_ld_data['price']
            logger.info(f"✓ Price: {data.price} MAD")
        
        if json_ld_data.get('num_analysts'):
            data.num_analysts = json_ld_data['num_analysts']
        
        # Strategy 2: Pattern matching with validation
        
        # Market Cap - look for patterns with billions/millions
        for pattern in [
            r'Market\s+Cap[^:]*:\s*([\d,.]+\s*[BMK])',
            r'Capitalisation[^:]*:\s*([\d,.]+\s*[BMK])',
            r'Market Cap[^\d]*([\d,.]+)\s*B',  # Specific billions pattern
        ]:
            match = re.search(pattern, page_text, re.IGNORECASE)
            if match:
                mcap = parse_number(match.group(1))
                if mcap and mcap > 1e6:  # At least 1 million
                    data.market_cap = mcap
                    logger.info(f"✓ Market Cap: {mcap:,.0f} MAD")
                    break
        
        # P/E Ratio - with strict validation
        for pe_pattern in [
            r'P/E\s+Ratio[^:]*:\s*(\d+\.?\d*)',
            r'PER[^:]*:\s*(\d+\.?\d*)',
            r'(?:^|\s)P/E\s+(\d+\.?\d*)(?:\s|$)',
        ]:
            match = re.search(pe_pattern, page_text, re.IGNORECASE | re.MULTILINE)
            if match:
                pe = parse_number(match.group(1))
                # Validate: P/E should be 0.1 to 300 (exclude years like 2025)
                if pe and 0.1 <= pe <= 300:
                    data.pe_ratio = pe
                    logger.info(f"✓ P/E Ratio: {pe}")
                    break
        
        # Dividend Yield - must have % symbol
        for div_pattern in [
            r'Dividend\s+Yield[^:]*:\s*(\d+\.?\d*)\s*%',
            r'Yield[^:]*:\s*(\d+\.?\d*)\s*%',
            r'Rendement[^:]*:\s*(\d+\.?\d*)\s*%',
        ]:
            match = re.search(div_pattern, page_text, re.IGNORECASE)
            if match:
                div_yield = parse_number(match.group(1))
                # Validate: dividend yield 0-20%
                if div_yield and 0 <= div_yield <= 20:
                    data.dividend_yield = div_yield
                    logger.info(f"✓ Dividend Yield: {div_yield}%")
                    break
        
        # 52-week High/Low - must be close to current price
        high_match = re.search(r'52.*?(?:Week|w).*?High[^:]*:\s*([\d,.]+)', page_text, re.IGNORECASE)
        if high_match:
            high = parse_number(high_match.group(1))
            # Validate: should be within reasonable range of current price
            if high and data.price and 0.5 <= high / data.price <= 3:
                data.high_52w = high
                logger.info(f"✓ 52w High: {high}")
        
        low_match = re.search(r'52.*?(?:Week|w).*?Low[^:]*:\s*([\d,.]+)', page_text, re.IGNORECASE)
        if low_match:
            low = parse_number(low_match.group(1))
            # Validate: should be within reasonable range of current price
            if low and data.price and 0.3 <= low / data.price <= 2:
                data.low_52w = low
                logger.info(f"✓ 52w Low: {low}")
    
    async def scrape_finances_page(self, data: StockData, url_code: str) -> None:
        """Scrape historical financial data from finances page."""
        url = f"{BASE_URL}/{url_code}/finances/"
        html = await self.get(url)
        
        if not html:
            logger.warning(f"Failed to fetch finances page for {data.symbol}")
            return
        
        soup = BeautifulSoup(html, 'lxml')
        
        # Find tables with historical data
        for table in soup.find_all('table'):
            rows = list(table.find_all('tr'))
            if not rows:
                continue
            
            # Extract year headers
            header_row = rows[0]
            headers = [th.get_text(strip=True) for th in header_row.find_all(['th', 'td'])]
            
            # Find years (format: 2019-2030)
            years = []
            year_indices = []
            for i, h in enumerate(headers):
                if re.match(r'^20\d{2}$', h):
                    years.append(h)
                    year_indices.append(i)
            
            if not years:
                continue
            
            # Parse data rows with enhanced label matching
            for row in rows[1:]:
                cells = row.find_all(['td', 'th'])
                if len(cells) < 2:
                    continue
                
                label = cells[0].get_text(strip=True).lower()
                
                # Enhanced label matching with multiple variants
                target = None
                
                # Revenue (multiple variants)
                if any(term in label for term in [
                    'revenue', 'sales', 'turnover', 'net sales', 
                    'chiffre d\'affaires', 'ca'
                ]):
                    if 'per share' not in label:  # Exclude "revenue per share"
                        target = data.hist_revenue
                
                # Net Income (multiple variants)
                elif any(term in label for term in [
                    'net income', 'net profit', 'net earnings',
                    'résultat net', 'profit net'
                ]):
                    if 'margin' not in label and 'per share' not in label:
                        target = data.hist_net_income
                
                # EPS (multiple variants)
                elif any(term in label for term in [
                    'earnings per share', 'eps', 'bénéfice par action'
                ]):
                    target = data.hist_eps
                
                # EBITDA (multiple variants)
                elif 'ebitda' in label and 'margin' not in label:
                    target = data.hist_ebitda
                
                # Free Cash Flow (multiple variants)
                elif any(term in label for term in [
                    'free cash flow', 'fcf', 'free cash-flow',
                    'flux de trésorerie libre'
                ]):
                    target = data.hist_fcf
                
                # Operating Cash Flow (multiple variants)
                elif any(term in label for term in [
                    'operating cash flow', 'cash from operations',
                    'operating cash-flow', 'flux de trésorerie opérationnel',
                    'cash flow from operating'
                ]):
                    if 'per share' not in label:
                        target = data.hist_ocf
                
                # CapEx (multiple variants)
                elif any(term in label for term in [
                    'capex', 'capital expenditure', 'capital spending',
                    'dépenses d\'investissement', 'capex'
                ]):
                    target = data.hist_capex
                
                # If we found a matching field, extract values
                if target is not None:
                    for idx, year in zip(year_indices, years):
                        if idx < len(cells):
                            val = parse_number(cells[idx].get_text(strip=True))
                            if val is not None:
                                target[year] = val
                    
                    # Log what we found
                    if target:
                        field_name = {
                            id(data.hist_revenue): 'Revenue',
                            id(data.hist_net_income): 'Net Income',
                            id(data.hist_eps): 'EPS',
                            id(data.hist_ebitda): 'EBITDA',
                            id(data.hist_fcf): 'FCF',
                            id(data.hist_ocf): 'OCF',
                            id(data.hist_capex): 'CapEx',
                        }.get(id(target), 'Unknown')
                        logger.info(f"✓ {field_name}: {len(target)} years")
    
    async def scrape_consensus_page(self, data: StockData, url_code: str) -> None:
        """Scrape analyst consensus data."""
        url = f"{BASE_URL}/{url_code}/consensus/"
        html = await self.get(url)
        
        if not html:
            logger.warning(f"Failed to fetch consensus page for {data.symbol}")
            return
        
        soup = BeautifulSoup(html, 'lxml')
        page_text = soup.get_text()
        
        # Target price - STRICT pattern to avoid ISIN codes
        for target_pattern in [
            r'(?:Average|Mean|Consensus)\s+Target\s+Price[^:]*:\s*([\d,.]+)',
            r'Target\s+Price[^:]*:\s*([\d,.]+)\s*(?:MAD|USD|EUR)',  # Must have currency
        ]:
            match = re.search(target_pattern, page_text, re.IGNORECASE)
            if match:
                target = parse_number(match.group(1))
                # Validate: target price should be within 0.3x to 5x current price
                if target and data.price and 0.3 <= target / data.price <= 5:
                    data.target_price = target
                    logger.info(f"✓ Target Price: {target}")
                    break
        
        # Consensus rating
        for keyword in ['BUY', 'HOLD', 'SELL', 'ACCUMULATE', 'OUTPERFORM', 'UNDERPERFORM']:
            # Look for keyword as whole word (not part of other words)
            if re.search(rf'\b{keyword}\b', page_text, re.IGNORECASE):
                data.consensus = keyword
                logger.info(f"✓ Consensus: {keyword}")
                break
    
    async def scrape(self, symbol: str, url_code: str) -> StockData:
        """Main scraping orchestrator."""
        logger.info(f"\n{'='*60}")
        logger.info(f"Scraping {symbol}")
        logger.info(f"{'='*60}")
        
        data = StockData(symbol=symbol)
        
        # Scrape all pages
        await self.scrape_main_page(data, url_code)
        await self.scrape_finances_page(data, url_code)
        await self.scrape_consensus_page(data, url_code)
        
        # Validate data quality
        data.validate()
        
        return data
    
    async def close(self):
        """Close the HTTP session."""
        if self.session:
            await self.session.close()

# =============================================================================
# Main Execution
# =============================================================================

async def main():
    parser = argparse.ArgumentParser(description='MarketScreener Scraper V2')
    parser.add_argument('--symbol', help='Stock symbol (e.g., IAM)')
    parser.add_argument('--all', action='store_true', help='Scrape all symbols')
    args = parser.parse_args()
    
    # Load instrument config
    with open(CONFIG_PATH, 'r') as f:
        instruments = json.load(f)['instruments']
    
    # Select instruments to scrape
    to_process = []
    if args.symbol:
        to_process = [i for i in instruments if i['symbol'].upper() == args.symbol.upper()]
        if not to_process:
            print(f"❌ Symbol {args.symbol} not found")
            print(f"Available symbols: {', '.join(i['symbol'] for i in instruments)}")
            return
    elif args.all:
        to_process = instruments
    else:
        # Interactive menu
        print("\n📊 MarketScreener Scraper V2 (2026-04-05)")
        print("=" * 60)
        print("Available symbols:")
        for i, inst in enumerate(instruments, 1):
            print(f"  [{i}] {inst['symbol']:5s} - {inst['name']}")
        
        try:
            choice = int(input("\nSelect number: ")) - 1
            to_process = [instruments[choice]]
        except (ValueError, IndexError):
            print("❌ Invalid selection")
            return
    
    # Scrape
    scraper = MarketScreenerScraper()
    
    try:
        for inst in to_process:
            stock_data = await scraper.scrape(inst['symbol'], inst['url_code'])
            
            # Save JSON
            output_file = DATA_DIR / f"{inst['symbol']}_marketscreener_v2.json"
            with open(output_file, 'w') as f:
                json.dump(asdict(stock_data), f, indent=2, default=str)
            
            # Print summary
            print(f"\n✅ Completed {inst['symbol']}")
            print(f"   Price: {stock_data.price} MAD" if stock_data.price else "   Price: N/A")
            print(f"   Market Cap: {stock_data.market_cap:,.0f} MAD" if stock_data.market_cap else "   Market Cap: N/A")
            print(f"   P/E Ratio: {stock_data.pe_ratio}" if stock_data.pe_ratio else "   P/E: N/A")
            print(f"   Dividend Yield: {stock_data.dividend_yield}%" if stock_data.dividend_yield else "   Div Yield: N/A")
            print(f"   Revenue years: {sorted(stock_data.hist_revenue.keys())}" if stock_data.hist_revenue else "   Revenue: No data")
            print(f"   EPS years: {sorted(stock_data.hist_eps.keys())}" if stock_data.hist_eps else "   EPS: No data")
            
            # Data quality summary
            total_fields = 13  # price, mcap, pe, div, 52w high/low, consensus, target, 4 historical
            filled_fields = sum([
                bool(stock_data.price),
                bool(stock_data.market_cap),
                bool(stock_data.pe_ratio),
                bool(stock_data.dividend_yield),
                bool(stock_data.high_52w),
                bool(stock_data.low_52w),
                bool(stock_data.consensus),
                bool(stock_data.target_price),
                bool(stock_data.hist_revenue),
                bool(stock_data.hist_net_income),
                bool(stock_data.hist_eps),
                bool(stock_data.hist_fcf),
                bool(stock_data.hist_ocf),
            ])
            quality_pct = (filled_fields / total_fields) * 100
            print(f"   Data Quality: {quality_pct:.0f}% ({filled_fields}/{total_fields} fields)")
            
            if stock_data.scrape_warnings:
                print(f"   ⚠️  Warnings: {len(stock_data.scrape_warnings)}")
            
            print(f"   📁 Saved to: {output_file.name}")
    
    finally:
        await scraper.close()

if __name__ == "__main__":
    asyncio.run(main())
