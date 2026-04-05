"""
MarketScreener Stock Scraper (Robust Production Version)
=============================================================
High-performance async scraper for Moroccan stocks on MarketScreener.
Captures: Current price, 52w High/Low, Historical Financials (3-5 years),
Valuation Ratios, and Analyst Consensus.

Usage:
    python scrapers/marketscreener_scraper.py --symbol ADH
"""

import re
import asyncio
import random
import logging
import json
import csv
import os
import sys
import argparse
from datetime import datetime
from pathlib import Path
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
# Path & Global Config
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
    scrape_timestamp: str = field(default_factory=lambda: datetime.utcnow().isoformat() + "Z")
    
    # Snapshot
    price: Optional[float] = None
    change_1d: Optional[float] = None
    volume: Optional[int] = None
    high_52w: Optional[float] = None
    low_52w: Optional[float] = None
    
    # Valuation
    market_cap: Optional[float] = None
    pe_ratio: Optional[float] = None
    dividend_yield: Optional[float] = None
    
    # Consensus
    consensus: Optional[str] = None
    target_price: Optional[float] = None
    upside_pct: Optional[float] = None
    
    # Historical Dictionaries {Year: Value}
    hist_revenue: Dict[str, float] = field(default_factory=dict)
    hist_net_income: Dict[str, float] = field(default_factory=dict)
    hist_eps: Dict[str, float] = field(default_factory=dict)
    hist_pe: Dict[str, float] = field(default_factory=dict)
    hist_yield: Dict[str, float] = field(default_factory=dict)

    def to_flat_dict(self) -> Dict[str, Any]:
        flat = asdict(self)
        # Flatten historical dicts into columns like rev_2022, rev_2023
        for prefix, d in [("rev", self.hist_revenue), ("ni", self.hist_net_income), ("eps", self.hist_eps), ("pe", self.hist_pe)]:
            for year, val in d.items():
                flat[f"{prefix}_{year}"] = val
        # Clean up the dictionaries from the final flat output
        for k in ["hist_revenue", "hist_net_income", "hist_eps", "hist_pe", "hist_yield"]:
            if k in flat: del flat[k]
        return flat

# =============================================================================
# Parsing Logic
# =============================================================================

def parse_number(text: Optional[str]) -> Optional[float]:
    if not text: return None
    text = text.strip().upper()
    mult = 1
    if text.endswith('B'): mult = 1e9; text = text[:-1]
    elif text.endswith('M'): mult = 1e6; text = text[:-1]
    elif text.endswith('K'): mult = 1e3; text = text[:-1]
    
    text = re.sub(r'[^-0-9,.]', '', text).replace(',', '.')
    if text.count('.') > 1: # Handle European "1.234.567" format
        parts = text.split('.')
        text = "".join(parts[:-1]) + "." + parts[-1]
    try: return float(text) * mult
    except: return None

def clean(text: Optional[str]) -> str:
    return re.sub(r'\s+', ' ', text.strip()) if text else ""

# =============================================================================
# Scraper Core
# =============================================================================

class RobustScraper:
    def __init__(self):
        self.session = None

    async def get(self, url: str) -> Optional[str]:
        if not self.session:
            self.session = aiohttp.ClientSession(headers={"User-Agent": random.choice(USER_AGENTS)})
        await asyncio.sleep(random.uniform(1, 3))
        try:
            async with self.session.get(url) as resp:
                if resp.status == 200: return await resp.text()
        except Exception as e:
            logger.error(f"Error fetching {url}: {e}")
        return None

    async def scrape(self, symbol: str, url_code: str) -> StockData:
        data = StockData(symbol=symbol)
        
        # 1. Main Quote Page (Price, MCAP, Snapshot)
        html = await self.get(f"{BASE_URL}/{url_code}/")
        if html:
            soup = BeautifulSoup(html, 'lxml')
            
            # Price & Change
            price_elem = soup.find('span', class_='last')
            if price_elem: data.price = parse_number(price_elem.text)
            
            # Market Cap: Look specifically in the card with id 'valoData' or header badges
            valo_data = soup.find('div', id='valoData')
            if valo_data:
                for row in valo_data.find_all('tr'):
                    cells = row.find_all('td')
                    if len(cells) >= 2:
                        lbl = cells[0].text.lower()
                        if 'capitalization' in lbl:
                            data.market_cap = parse_number(cells[1].text)
            
            # Fallback for Market Cap in page text if valoData failed
            if not data.market_cap:
                cap_match = re.search(r'Capitalization.*?([\d,.]+.*?B|M)', soup.get_text(), re.S | re.I)
                if cap_match: data.market_cap = parse_number(cap_match.group(1))

            # 52w High/Low
            page_text = soup.get_text()
            high_match = re.search(r'52w High.*?([\d,.]+)', page_text, re.S | re.I)
            if high_match: data.high_52w = parse_number(high_match.group(1))
            low_match = re.search(r'52w Low.*?([\d,.]+)', page_text, re.S | re.I)
            if low_match: data.low_52w = parse_number(low_match.group(1))

        # 2. Financials Page (Historical Data)
        html_fin = await self.get(f"{BASE_URL}/{url_code}/finances/")
        if html_fin:
            soup = BeautifulSoup(html_fin, 'lxml')
            
            # Check for generic year columns
            for table in soup.find_all('table'):
                rows = list(table.find_all('tr'))
                if not rows: continue
                
                header_cells = [clean(c.text) for c in rows[0].find_all(['th', 'td'])]
                years = [y for y in header_cells if re.match(r'^20\d{2}$', y)]
                if not years: continue
                
                for row in rows[1:]:
                    cells = row.find_all(['td', 'th'])
                    if len(cells) < len(years) + 1: continue
                    label = clean(cells[0].text).lower()
                    
                    target_dict = None
                    if any(term in label for term in ['net sales', 'revenue', 'revenues']): target_dict = data.hist_revenue
                    elif 'net income' in label: target_dict = data.hist_net_income
                    elif 'eps' == label.strip() or 'earnings per share' in label: target_dict = data.hist_eps
                    elif 'p/e ratio' in label: target_dict = data.hist_pe
                    
                    if target_dict is not None:
                        for i, year in enumerate(years):
                            cell_text = clean(cells[i+1].text)
                            val = parse_number(cell_text)
                            if val is not None: target_dict[year] = val

        # 3. Consensus Page
        html_cons = await self.get(f"{BASE_URL}/{url_code}/consensus/")
        if html_cons:
            soup = BeautifulSoup(html_cons, 'lxml')
            page_text = soup.get_text()
            
            # Mean Target Price
            target_match = re.search(r'Average Target Price.*?([\d,.]+)', page_text, re.S | re.I)
            if target_match: data.target_price = parse_number(target_match.group(1))
            
            # Upside
            upside_match = re.search(r'Spread / Average Target.*?([+-]?\d+\.?\d*)%', page_text, re.S | re.I)
            if upside_match: data.upside_pct = float(upside_match.group(1))
            
            # Rating Badge
            for badge in soup.find_all(['span', 'div'], class_=re.compile(r'badge|rating')):
                txt = badge.text.strip().upper()
                if txt in ['BUY', 'HOLD', 'SELL', 'ACCUMULATE', 'OUTPERFORM']:
                    data.consensus = txt
                    break

        return data

    async def close(self):
        if self.session: await self.session.close()

# =============================================================================
# Execution Loop
# =============================================================================

async def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--symbol", help="Target symbol")
    parser.add_argument("--all", action="store_true")
    args = parser.parse_args()

    with open(CONFIG_PATH, 'r') as f:
        instruments = json.load(f)["instruments"]

    to_process = []
    if args.symbol: to_process = [i for i in instruments if i['symbol'].upper() == args.symbol.upper()]
    elif args.all: to_process = instruments
    else:
        print("\nAvailable Markets:")
        for i, inst in enumerate(instruments, 1): print(f"  [{i}] {inst['symbol']}")
        choice = input("\nSelect Index: ")
        to_process = [instruments[int(choice)-1]]

    scraper = RobustScraper()
    for inst in to_process:
        print(f"🚀 Scraping {inst['symbol']}...")
        stock_data = await scraper.scrape(inst['symbol'], inst['url_code'])
        
        # Save JSON
        with open(DATA_DIR / f"{inst['symbol']}_marketscreener.json", 'w') as f:
            json.dump(stock_data.to_flat_dict(), f, indent=2)
        
        # Save CSV
        flat = stock_data.to_flat_dict()
        with open(DATA_DIR / f"{inst['symbol']}_marketscreener.csv", 'w', newline='') as f:
            writer = csv.DictWriter(f, fieldnames=flat.keys())
            writer.writeheader()
            writer.writerow(flat)
        print(f"✅ Finished {inst['symbol']}")

    await scraper.close()

if __name__ == "__main__":
    asyncio.run(main())
