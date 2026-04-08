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
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional, Dict, Any, List, Tuple
from dataclasses import dataclass, field, asdict
import argparse
import random

try:
    from selenium import webdriver
    from selenium.webdriver.common.by import By
    from selenium.webdriver.support.ui import WebDriverWait
    from selenium.webdriver.support import expected_conditions as EC
    from selenium.webdriver.chrome.service import Service
    from selenium.webdriver.chrome.options import Options
    from selenium.common.exceptions import TimeoutException, WebDriverException
    from webdriver_manager.chrome import ChromeDriverManager
    from bs4 import BeautifulSoup, Tag
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
CASA_CONFIG_PATH = _ROOT / "data" / "scrapers" / "instruments_bourse_casa.json"
DATA_DIR = _ROOT / "data" / "historical"
DATA_DIR.mkdir(parents=True, exist_ok=True)

BASE_URL = "https://www.marketscreener.com/quote/stock"

# Used by SeleniumScraper to rotate User-Agent strings between sessions.
USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/123.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.3 Safari/605.1.15",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
]

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# =============================================================================
# Data Model
# =============================================================================

@dataclass
class StockData:
    symbol: str
    scrape_timestamp: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    
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
    """
    Parse a numeric value with K/M/B/T suffixes, supporting both English
    (thousand=',', decimal='.') and French (thousand=' '/'.', decimal=',')
    formats. Returns None for inputs that don't look like a single sane number.
    """
    if not text:
        return None

    text = str(text).strip().upper()

    # Detect K/M/B/T multiplier even when followed by a currency code,
    # e.g. "83.5B MAD", "92,52 M €". The suffix must immediately follow a
    # digit and be a standalone token (not part of a word).
    mult = 1.0
    suffix_match = re.search(r'(?<=\d)\s*([KMBT])\b', text)
    if suffix_match:
        mult = {'K': 1e3, 'M': 1e6, 'B': 1e9, 'T': 1e12}[suffix_match.group(1)]
        text = text[:suffix_match.start()] + text[suffix_match.end():]

    # Strip currency symbols and other unit text. Keep digits, signs, separators.
    text = re.sub(r'[^\-0-9,.\s]', '', text).strip()
    if not text:
        return None

    # Defensive cap: real stock-page values never have more than ~16 digits.
    # If the text is much longer it almost certainly comes from a wide cell
    # that bundled multiple numbers together — refuse to guess.
    digit_count = sum(1 for c in text if c.isdigit())
    if digit_count == 0 or digit_count > 16:
        return None

    has_comma = ',' in text
    has_dot = '.' in text
    compact = text.replace(' ', '')

    if has_comma and has_dot:
        # Whichever separator appears LAST is the decimal point.
        if compact.rfind(',') > compact.rfind('.'):
            cleaned = compact.replace('.', '').replace(',', '.')
        else:
            cleaned = compact.replace(',', '')
    elif has_comma:
        # Pure comma. Distinguish thousand-grouping from decimal.
        if re.fullmatch(r'-?\d{1,3}(?:,\d{3})+', compact):
            cleaned = compact.replace(',', '')
        elif re.fullmatch(r'-?\d+,\d{1,3}', compact):
            cleaned = compact.replace(',', '.')
        else:
            cleaned = compact.replace(',', '')
    else:
        # Only dots (or none). Could be thousand separators or decimal.
        if re.fullmatch(r'-?\d{1,3}(?:\.\d{3})+', compact):
            cleaned = compact.replace('.', '')
        else:
            cleaned = compact

    try:
        return float(cleaned) * mult
    except (ValueError, AttributeError):
        return None


def parse_percent(text: Optional[str]) -> Optional[float]:
    """Parse percentage values like '4.47%' or '4,47 %' -> 4.47."""
    if not text:
        return None
    cleaned = re.sub(r'[^\-0-9,.]', '', str(text)).replace(',', '.')
    if not cleaned:
        return None
    try:
        return float(cleaned)
    except ValueError:
        return None


# =============================================================================
# DOM extraction helpers (key/value pairs from MarketScreener tables)
# =============================================================================

# Hard caps so a wide cell with concatenated junk can't poison parsing.
_MAX_LABEL_LEN = 60
_MAX_VALUE_LEN = 30


def _is_sane_kv(label: str, value: str) -> bool:
    if not label or not value or label == value:
        return False
    if len(label) > _MAX_LABEL_LEN or len(value) > _MAX_VALUE_LEN:
        return False
    # The value cell should look "atomic": at most one inner whitespace gap,
    # and no more than ~16 digits. Concatenated multi-number cells are noise.
    digits = sum(1 for c in value if c.isdigit())
    if digits > 16:
        return False
    return True


def extract_kv_pairs(soup: BeautifulSoup) -> List[Tuple[str, str]]:
    """
    Walk the DOM and collect every (label, value) pair where the label and
    value live in adjacent cells of a table row, or in a <dt>/<dd> pair.

    Returned as a list (not dict) so duplicate labels are preserved — useful
    when MS shows the same metric under multiple year columns.
    """
    pairs: List[Tuple[str, str]] = []

    # Tables: pair every cell with the cell immediately to its right.
    for table in soup.find_all('table'):
        for row in table.find_all('tr'):
            cells = row.find_all(['td', 'th'])
            if len(cells) < 2:
                continue
            for i in range(len(cells) - 1):
                label = cells[i].get_text(' ', strip=True)
                value = cells[i + 1].get_text(' ', strip=True)
                if _is_sane_kv(label, value):
                    pairs.append((label, value))

    # <dl> definition lists.
    for dl in soup.find_all('dl'):
        terms = dl.find_all('dt')
        defs = dl.find_all('dd')
        for t, d in zip(terms, defs):
            label = t.get_text(' ', strip=True)
            value = d.get_text(' ', strip=True)
            if _is_sane_kv(label, value):
                pairs.append((label, value))

    # MarketScreener also uses sibling <span>/<div> patterns inside cards,
    # e.g. <span class="c-table__field-name">Cap.</span><span ...>92.52B</span>
    for span in soup.find_all(['span', 'div']):
        cls = ' '.join(span.get('class') or [])
        if not cls:
            continue
        if 'field-name' in cls or 'label' in cls or 'title' in cls.lower():
            label = span.get_text(' ', strip=True)
            if not label or len(label) > _MAX_LABEL_LEN:
                continue
            sib = span.find_next_sibling(['span', 'div', 'td'])
            if sib:
                value = sib.get_text(' ', strip=True)
                if _is_sane_kv(label, value):
                    pairs.append((label, value))

    return pairs


def find_in_kv(pairs: List[Tuple[str, str]], label_patterns: List[str]) -> Optional[str]:
    """Return the first value whose label matches any of the given regex patterns."""
    compiled = [re.compile(p, re.IGNORECASE) for p in label_patterns]
    for label, value in pairs:
        for rx in compiled:
            if rx.search(label):
                return value
    return None


# =============================================================================
# Selenium Scraper
# =============================================================================

class SeleniumScraper:
    def __init__(self, headless: bool = True, debug: bool = False, user_agent: Optional[str] = None):
        """Initialize Selenium driver."""
        self.debug = debug

        chrome_options = Options()
        if headless:
            chrome_options.add_argument('--headless=new')
        chrome_options.add_argument('--no-sandbox')
        chrome_options.add_argument('--disable-dev-shm-usage')
        chrome_options.add_argument('--disable-gpu')
        chrome_options.add_argument('--window-size=1920,1080')
        chrome_options.add_argument('--lang=en-US,en')
        ua = user_agent or random.choice(USER_AGENTS)
        chrome_options.add_argument(f'--user-agent={ua}')

        logger.info("🌐 Starting Chrome browser...")
        # webdriver-manager hits a CA bundle that doesn't exist on this box
        # (PostgreSQL's bundle is shadowing the system CA), so try the
        # bundled selenium-manager driver first and only fall back to
        # ChromeDriverManager if that path fails.
        try:
            self.driver = webdriver.Chrome(options=chrome_options)
        except WebDriverException as primary_exc:
            logger.warning(f"Default Chrome driver failed ({primary_exc}); trying ChromeDriverManager...")
            try:
                service = Service(ChromeDriverManager().install())
                self.driver = webdriver.Chrome(service=service, options=chrome_options)
            except Exception as fallback_exc:
                logger.error(f"Failed to start Chrome: {fallback_exc}")
                raise
        self.driver.set_page_load_timeout(30)
    
    def _wait_and_get_soup(self, wait_seconds: int = 5) -> BeautifulSoup:
        """Wait for page body to be present, then return parsed soup."""
        try:
            WebDriverWait(self.driver, 15).until(
                EC.presence_of_element_located((By.TAG_NAME, "body"))
            )
        except TimeoutException:
            logger.warning("⚠ Body element not found within 15s")
        # Give JavaScript widgets a chance to populate.
        time.sleep(wait_seconds)
        return BeautifulSoup(self.driver.page_source, 'lxml')

    def _maybe_dump_html(self, symbol: str, page_name: str) -> None:
        """Dump rendered HTML to disk when --debug is set, for inspection."""
        if not self.debug:
            return
        try:
            debug_dir = DATA_DIR / "_debug"
            debug_dir.mkdir(parents=True, exist_ok=True)
            out = debug_dir / f"{symbol}_{page_name}.html"
            out.write_text(self.driver.page_source, encoding='utf-8')
            logger.info(f"🐞 Dumped HTML → {out}")
        except Exception as exc:
            logger.warning(f"Failed to dump HTML: {exc}")

    def scrape_main_page(self, data: StockData, url_code: str) -> None:
        """Scrape main quote page with JavaScript rendering."""
        url = f"{BASE_URL}/{url_code}/"

        logger.info(f"📄 Loading {url}")
        self.driver.get(url)

        logger.info("⏳ Waiting for JavaScript to render...")
        soup = self._wait_and_get_soup(wait_seconds=5)
        self._maybe_dump_html(data.symbol, "main")

        # Build a key/value map from the DOM. MarketScreener lays out their
        # "Key Data" / "Trading Info" widgets as <td>label</td><td>value</td>,
        # which the old regex-on-flattened-text approach couldn't reach.
        kv = extract_kv_pairs(soup)
        if self.debug:
            logger.info(f"🐞 Extracted {len(kv)} KV pairs from main page")
            for label, value in kv[:40]:
                logger.info(f"   {label!r} -> {value!r}")

        page_text = soup.get_text(' ', strip=True)

        # ----- Price -----
        # Prefer DOM-anchored extraction; fall back to regex on flattened text.
        price_value = find_in_kv(kv, [
            r'^(?:Last|Cours|Dernier)\b',
            r'^Quote\b',
        ])
        price = parse_number(price_value) if price_value else None
        if not price:
            for price_pattern in [
                r'(\d+(?:[.,]\d+)?)\s*MAD\b',
                r'Last\s*(?:Price|Quote)?[:\s]+(\d+(?:[.,]\d+)?)',
            ]:
                match = re.search(price_pattern, page_text, re.IGNORECASE)
                if match:
                    candidate = parse_number(match.group(1))
                    if candidate and 1 < candidate < 100000:
                        price = candidate
                        break
        if price and 1 < price < 100000:
            data.price = price
            logger.info(f"✓ Price: {price} MAD")

        # ----- Market Cap -----
        # MS labels: "Cap.", "Cap. boursière", "Capitalization", "Market cap."
        mcap_value = find_in_kv(kv, [
            r'^Cap\.?\s*(?:bours|market)?',
            r'^Market\s*Cap',
            r'^Capitali[sz]ation',
            r'^Capitalisation',
        ])
        if mcap_value:
            mcap = parse_number(mcap_value)
            if mcap and mcap > 1e6:
                data.market_cap = mcap
                logger.info(f"✓ Market Cap: {mcap:,.0f} MAD")

        # ----- P/E Ratio -----
        # MS labels include the year suffix: "P/E ratio 2025", "PER 2025".
        pe_value = find_in_kv(kv, [
            r'^P\s*/\s*E\b',
            r'^PER\b',
            r'Price\s*/\s*Earnings',
        ])
        if pe_value:
            pe = parse_number(pe_value)
            if pe and 0.1 <= pe <= 300:
                data.pe_ratio = pe
                logger.info(f"✓ P/E Ratio: {pe}")

        # ----- Dividend Yield -----
        div_value = find_in_kv(kv, [
            r'^(?:Dividend\s+)?Yield\b',
            r'^Rendement',
            r'^Div\.?\s*Yield',
        ])
        if div_value:
            div_yield = parse_percent(div_value)
            if div_yield is not None and 0 <= div_yield <= 30:
                data.dividend_yield = div_yield
                logger.info(f"✓ Dividend Yield: {div_yield}%")

        # ----- Price / Book -----
        pb_value = find_in_kv(kv, [
            r'^P\s*/\s*B(?:V)?\b',
            r'^Price\s*/\s*Book',
        ])
        if pb_value:
            pb = parse_number(pb_value)
            if pb and 0.01 <= pb <= 100:
                data.price_to_book = pb
                logger.info(f"✓ P/B: {pb}")

        # ----- 52-week High/Low -----
        high_value = find_in_kv(kv, [
            r'52[\s\-]*(?:weeks?|w)\s*high',
            r'(?:Plus|Highest).*52',
        ])
        if high_value:
            high = parse_number(high_value)
            if high and data.price and 0.5 <= high / data.price <= 3:
                data.high_52w = high
                logger.info(f"✓ 52w High: {high}")

        low_value = find_in_kv(kv, [
            r'52[\s\-]*(?:weeks?|w)\s*low',
            r'(?:Plus|Lowest).*52',
        ])
        if low_value:
            low = parse_number(low_value)
            if low and data.price and 0.3 <= low / data.price <= 2:
                data.low_52w = low
                logger.info(f"✓ 52w Low: {low}")

        # ----- Volume -----
        vol_value = find_in_kv(kv, [
            r'^Volume\b',
            r'^Vol\.?\s*(?:moyen|avg)?',
        ])
        if vol_value:
            vol = parse_number(vol_value)
            if vol and vol >= 0:
                data.volume = int(vol)
    
    def scrape_finances_page(self, data: StockData, url_code: str) -> None:
        """Scrape financial tables."""
        url = f"{BASE_URL}/{url_code}/finances/"

        logger.info(f"📊 Loading financials...")
        self.driver.get(url)
        soup = self._wait_and_get_soup(wait_seconds=3)
        self._maybe_dump_html(data.symbol, "finances")
        
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
        soup = self._wait_and_get_soup(wait_seconds=3)
        self._maybe_dump_html(data.symbol, "consensus")

        kv = extract_kv_pairs(soup)
        page_text = soup.get_text(' ', strip=True)

        # ----- Target price -----
        target_value = find_in_kv(kv, [
            r'(?:Average|Mean|Consensus|Target)\s+(?:Target\s+)?Price',
            r'Objectif\s+de\s+cours',
            r'Cours\s+cible',
        ])
        target = parse_number(target_value) if target_value else None
        if not target:
            match = re.search(
                r'(?:Average|Mean|Consensus)\s+Target\s+Price[\s:]+([\d.,]+)',
                page_text,
                re.IGNORECASE,
            )
            if match:
                target = parse_number(match.group(1))
        if target and data.price and 0.3 <= target / data.price <= 5:
            data.target_price = target
            logger.info(f"✓ Target Price: {target}")

        # ----- Number of analysts -----
        analysts_value = find_in_kv(kv, [
            r'(?:Number\s+of\s+)?Analysts',
            r'Nombre\s+d.?analystes',
        ])
        if analysts_value:
            n = parse_number(analysts_value)
            if n and 1 <= n <= 100:
                data.num_analysts = int(n)
                logger.info(f"✓ Analysts: {data.num_analysts}")

        # ----- Consensus rating -----
        # MS shows the rating in a labelled cell, e.g. "Mean recommendation : Outperform".
        # Avoid scanning the entire page text — that produced false positives by
        # matching unrelated occurrences of BUY/HOLD/SELL anywhere on the page.
        consensus_value = find_in_kv(kv, [
            r'(?:Mean|Consensus|Average)\s+recommendation',
            r'Recommendation',
            r'Recommandation',
        ])
        if consensus_value:
            cv = consensus_value.upper()
            for keyword in ['BUY', 'OUTPERFORM', 'ACCUMULATE', 'HOLD', 'NEUTRAL', 'UNDERPERFORM', 'SELL']:
                if keyword in cv:
                    data.consensus = keyword
                    logger.info(f"✓ Consensus: {keyword}")
                    break
    
    # ------------------------------------------------------------------
    # Rate-limit / bot-challenge detection
    # ------------------------------------------------------------------
    _RATE_LIMIT_MARKERS = (
        "just a moment",          # Cloudflare challenge
        "verify you are human",
        "access denied",
        "rate limit",
        "too many requests",
        "temporarily blocked",
        "captcha",
    )

    def looks_rate_limited(self) -> bool:
        try:
            title = (self.driver.title or "").lower()
            body = self.driver.find_element(By.TAG_NAME, "body").text[:2000].lower()
        except Exception:
            return False
        haystack = f"{title}\n{body}"
        return any(marker in haystack for marker in self._RATE_LIMIT_MARKERS)

    # ------------------------------------------------------------------
    # MarketScreener URL slug discovery
    # ------------------------------------------------------------------
    def discover_url_code(self, symbol: str, name: str) -> Optional[str]:
        """
        Resolve a stock to its MarketScreener URL slug by querying the search
        page. Returns the slug (e.g. ITISSALAT-AL-MAGHRIB-IAM--1408717) or
        None if no plausible result is found.
        """
        # Query without parenthetical aliases — MS doesn't index those.
        query = re.sub(r'\([^)]*\)', '', name).strip()
        encoded = re.sub(r'\s+', '+', query)
        search_url = f"https://www.marketscreener.com/search/?q={encoded}"

        logger.info(f"🔎 Discovering MS slug for {symbol}: {query}")
        try:
            self.driver.get(search_url)
            self._wait_and_get_soup(wait_seconds=2)
        except Exception as exc:
            logger.warning(f"   search failed: {exc}")
            return None

        if self.looks_rate_limited():
            return None

        soup = BeautifulSoup(self.driver.page_source, 'lxml')
        # Quote pages live at /quote/stock/<SLUG>/...
        candidates = []
        for a in soup.find_all('a', href=True):
            m = re.match(r'^/?quote/stock/([A-Za-z0-9\-]+)/?', a['href'])
            if not m:
                continue
            slug = m.group(1)
            anchor_text = a.get_text(' ', strip=True).upper()
            score = 0
            if symbol.upper() in anchor_text or symbol.upper() in slug.upper():
                score += 10
            # Penalise non-Morocco listings (we only want Casablanca tickers).
            if 'MOROC' in anchor_text or symbol.upper() in slug.upper():
                score += 5
            candidates.append((score, slug, anchor_text))

        if not candidates:
            logger.warning(f"   no candidates for {symbol}")
            return None

        candidates.sort(key=lambda c: c[0], reverse=True)
        best = candidates[0]
        logger.info(f"   ✓ matched {best[1]}  (score={best[0]}, label={best[2][:50]!r})")
        return best[1]

    def scrape(self, symbol: str, url_code: str) -> StockData:
        """Main scraping orchestrator."""
        logger.info(f"\n{'='*60}")
        logger.info(f"Scraping {symbol} with Selenium")
        logger.info(f"{'='*60}")

        data = StockData(symbol=symbol)

        self.scrape_main_page(data, url_code)
        if self.looks_rate_limited():
            data.scrape_warnings.append("Rate-limited on main page")
            return data
        self.scrape_finances_page(data, url_code)
        self.scrape_consensus_page(data, url_code)

        data.validate()

        return data

    def close(self):
        """Close browser."""
        logger.info("🔒 Closing browser...")
        try:
            self.driver.quit()
        except Exception:
            pass

# =============================================================================
# Main
# =============================================================================

def _load_ms_instruments() -> List[Dict[str, Any]]:
    if not CONFIG_PATH.exists():
        return []
    with open(CONFIG_PATH, 'r', encoding='utf-8') as f:
        return json.load(f).get('instruments', [])


def _save_ms_instruments(instruments: List[Dict[str, Any]]) -> None:
    CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(CONFIG_PATH, 'w', encoding='utf-8') as f:
        json.dump({'instruments': instruments}, f, indent=2, ensure_ascii=False)


def _load_casa_instruments() -> List[Dict[str, Any]]:
    if not CASA_CONFIG_PATH.exists():
        raise FileNotFoundError(f"Missing {CASA_CONFIG_PATH}")
    with open(CASA_CONFIG_PATH, 'r', encoding='utf-8') as f:
        return json.load(f).get('instruments', [])


def _was_scraped_recently(symbol: str, max_age_hours: float) -> bool:
    f = DATA_DIR / f"{symbol}_marketscreener_v3.json"
    if not f.exists():
        return False
    age_h = (time.time() - f.stat().st_mtime) / 3600
    return age_h < max_age_hours


def _print_summary(stock_data: StockData, output_file: Path) -> None:
    print(f"\n✅ Completed {stock_data.symbol}")
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


def _resolve_targets(args, ms_instruments: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Build the work list, merging Casablanca symbols with MS slugs as needed."""
    ms_by_symbol = {i['symbol'].upper(): i for i in ms_instruments}

    if args.all_casa:
        casa = _load_casa_instruments()
        merged = []
        for inst in casa:
            sym = inst['symbol'].upper()
            if sym in ms_by_symbol and ms_by_symbol[sym].get('url_code'):
                merged.append(ms_by_symbol[sym])
            else:
                merged.append({'symbol': sym, 'name': inst['name'], 'url_code': None})
        return merged

    if args.symbol:
        sym = args.symbol.upper()
        if sym in ms_by_symbol:
            return [ms_by_symbol[sym]]
        # Allow lookup of unknown symbols by checking the Casablanca list.
        try:
            casa = _load_casa_instruments()
            for inst in casa:
                if inst['symbol'].upper() == sym:
                    return [{'symbol': sym, 'name': inst['name'], 'url_code': None}]
        except FileNotFoundError:
            pass
        print(f"❌ Symbol {args.symbol} not found")
        return []

    if args.all:
        return ms_instruments

    # Interactive picker (only MS-known instruments).
    print("\n📊 MarketScreener Scraper V3 (Selenium)")
    print("=" * 60)
    for i, inst in enumerate(ms_instruments, 1):
        print(f"  [{i}] {inst['symbol']:5s} - {inst['name']}")
    try:
        choice = int(input("\nSelect number: ")) - 1
        return [ms_instruments[choice]]
    except (ValueError, IndexError):
        print("❌ Invalid selection")
        return []


def main():
    parser = argparse.ArgumentParser(description='MarketScreener Scraper V3 (Selenium)')
    parser.add_argument('--symbol', help='Stock symbol')
    parser.add_argument('--all', action='store_true', help='Scrape all symbols listed in instruments_marketscreener.json')
    parser.add_argument('--all-casa', action='store_true',
                        help='Scrape every Casablanca SE instrument from instruments_bourse_casa.json '
                             '(auto-discovers MarketScreener URL slugs).')
    parser.add_argument('--headful', action='store_true', help='Show browser (not headless)')
    parser.add_argument('--debug', action='store_true', help='Dump rendered HTML and KV pairs to data/historical/_debug/')
    parser.add_argument('--resume', action='store_true',
                        help='Skip instruments whose JSON output is younger than --max-age-hours.')
    parser.add_argument('--max-age-hours', type=float, default=12.0,
                        help='With --resume, skip files newer than this many hours (default 12).')
    parser.add_argument('--delay-min', type=float, default=6.0,
                        help='Minimum random delay (seconds) between instruments (default 6).')
    parser.add_argument('--delay-max', type=float, default=14.0,
                        help='Maximum random delay (seconds) between instruments (default 14).')
    parser.add_argument('--cooldown', type=float, default=300.0,
                        help='Cooldown (seconds) when MarketScreener appears to rate-limit us (default 300).')
    parser.add_argument('--restart-every', type=int, default=15,
                        help='Restart the Chrome session every N instruments to clear cookies (default 15).')
    args = parser.parse_args()

    ms_instruments = _load_ms_instruments()
    to_process = _resolve_targets(args, ms_instruments)
    if not to_process:
        return

    scraper: Optional[SeleniumScraper] = SeleniumScraper(headless=not args.headful, debug=args.debug)
    processed = 0
    rate_limit_hits = 0

    def restart_browser():
        nonlocal scraper
        if scraper is not None:
            scraper.close()
        logger.info("♻ Restarting Chrome with a fresh profile / user-agent...")
        scraper = SeleniumScraper(headless=not args.headful, debug=args.debug)

    try:
        for idx, inst in enumerate(to_process, 1):
            symbol = inst['symbol']

            # Skip recently-scraped if --resume.
            if args.resume and _was_scraped_recently(symbol, args.max_age_hours):
                logger.info(f"⏭  [{idx}/{len(to_process)}] {symbol}: skipped (recent file < {args.max_age_hours}h)")
                continue

            logger.info(f"\n▶ [{idx}/{len(to_process)}] {symbol} — {inst.get('name', '')}")

            # Discover MS slug if missing.
            url_code = inst.get('url_code')
            if not url_code:
                url_code = scraper.discover_url_code(symbol, inst.get('name', symbol))
                if not url_code:
                    logger.warning(f"   skipped: no MS slug found for {symbol}")
                    continue
                # Cache discovery back into the MS instruments file.
                ms_instruments = _load_ms_instruments()
                if not any(i['symbol'].upper() == symbol.upper() for i in ms_instruments):
                    ms_instruments.append({
                        'symbol': symbol,
                        'name': inst.get('name', symbol),
                        'url_code': url_code,
                    })
                else:
                    for i in ms_instruments:
                        if i['symbol'].upper() == symbol.upper():
                            i['url_code'] = url_code
                _save_ms_instruments(ms_instruments)

            # Scrape with rate-limit handling.
            try:
                stock_data = scraper.scrape(symbol, url_code)
            except WebDriverException as exc:
                logger.error(f"   browser error: {exc}; restarting...")
                restart_browser()
                continue

            if scraper.looks_rate_limited() or any('Rate-limited' in w for w in stock_data.scrape_warnings):
                rate_limit_hits += 1
                logger.warning(f"⚠ Rate-limit signal detected (hit #{rate_limit_hits}); cooling down for {args.cooldown:.0f}s")
                time.sleep(args.cooldown)
                restart_browser()
                if rate_limit_hits >= 3:
                    logger.error("❌ Too many rate-limit hits — stopping to avoid daily ban.")
                    break
                continue

            # Persist result.
            output_file = DATA_DIR / f"{symbol}_marketscreener_v3.json"
            with open(output_file, 'w', encoding='utf-8') as f:
                json.dump(asdict(stock_data), f, indent=2, default=str, ensure_ascii=False)
            _print_summary(stock_data, output_file)
            processed += 1

            # Periodic Chrome restart to drop cookies + rotate UA.
            if args.restart_every and processed > 0 and processed % args.restart_every == 0:
                restart_browser()

            # Random polite delay (skip after the last item).
            if idx < len(to_process):
                delay = random.uniform(args.delay_min, args.delay_max)
                logger.info(f"   ⏱  sleeping {delay:.1f}s before next instrument...")
                time.sleep(delay)

        logger.info(f"\n🏁 Done. Processed {processed}/{len(to_process)} instruments.")

    finally:
        if scraper is not None:
            scraper.close()


if __name__ == "__main__":
    main()
