"""
MarketScreener Scraper V3 - With Selenium for JavaScript Rendering
===================================================================
Uses Selenium to wait for JavaScript-rendered content (Market Cap, P/E, etc.)
Then uses BeautifulSoup for fast table parsing (historical data).

Installation:
    pip install undetected-chromedriver selenium webdriver-manager

Usage:
    python scrapers/marketscreener_scraper_v3.py --symbol IAM
    python scrapers/marketscreener_scraper_v3.py --all --workers 3
"""

import re
import time
import logging
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional, Dict, Any, List, Tuple, Set
from dataclasses import dataclass, field, asdict
import argparse
import random

try:
    import undetected_chromedriver as uc
    HAS_UC = True
except ImportError:
    HAS_UC = False

try:
    from selenium import webdriver
    from selenium.webdriver.common.by import By
    from selenium.webdriver.support.ui import WebDriverWait
    from selenium.webdriver.support import expected_conditions as EC
    from selenium.webdriver.chrome.service import Service
    from selenium.webdriver.chrome.options import Options
    from selenium.common.exceptions import TimeoutException, WebDriverException
    from bs4 import BeautifulSoup, Tag
    HAS_DEPENDENCIES = True
except ImportError as e:
    HAS_DEPENDENCIES = False
    print("Missing dependencies. Install with:")
    print("pip install undetected-chromedriver selenium beautifulsoup4 lxml")
    print(f"\nError: {e}")
    exit(1)

# =============================================================================
# Configuration
# =============================================================================
_ROOT = Path(__file__).resolve().parent.parent
CONFIG_PATH = _ROOT / "data" / "scrapers" / "instruments_marketscreener.json"
CASA_CONFIG_PATH = _ROOT / "data" / "scrapers" / "instruments_bourse_casa.json"
MARKET_LINKS_PATHS = (
    _ROOT / "markets on marketscreener link.md",
    _ROOT / "markets on marketscreener links.md",
)
DATA_DIR = _ROOT / "data" / "historical"
DATA_DIR.mkdir(parents=True, exist_ok=True)

# Persistent state: tracks the last *full* scrape (all 6 pages) per symbol.
# Daily scrapes (main + consensus only) do NOT update this timestamp.
SCRAPE_STATE_PATH = DATA_DIR / "_scrape_state.json"
# If the last full scrape is older than this, a full scrape is triggered.
FULL_SCRAPE_MAX_AGE_DAYS = 365

BASE_URL = "https://www.marketscreener.com/quote/stock"
MS_QUOTE_URL_RE = re.compile(
    r"https?://(?:www\.)?marketscreener\.com/quote/stock/([A-Za-z0-9\-]+)/?",
    re.IGNORECASE,
)

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
# Scrape-state helpers (daily vs full mode)
# =============================================================================

def _load_scrape_state() -> Dict[str, Any]:
    """Load the per-symbol scrape state from disk."""
    if not SCRAPE_STATE_PATH.exists():
        return {}
    try:
        with open(SCRAPE_STATE_PATH, 'r', encoding='utf-8') as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError):
        return {}


def _save_scrape_state(state: Dict[str, Any]) -> None:
    """Persist the per-symbol scrape state to disk."""
    SCRAPE_STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(SCRAPE_STATE_PATH, 'w', encoding='utf-8') as f:
        json.dump(state, f, indent=2, ensure_ascii=False)


def _needs_full_scrape(symbol: str, state: Dict[str, Any]) -> bool:
    """Return True if the symbol has never had a full scrape or it's older than FULL_SCRAPE_MAX_AGE_DAYS."""
    entry = state.get(symbol)
    if not entry or not entry.get("last_full_scrape"):
        return True
    try:
        last = datetime.fromisoformat(entry["last_full_scrape"])
        age_days = (datetime.now(timezone.utc) - last).total_seconds() / 86400
        return age_days >= FULL_SCRAPE_MAX_AGE_DAYS
    except (ValueError, TypeError):
        return True


def _mark_full_scrape(symbol: str, state: Dict[str, Any]) -> None:
    """Record that a full scrape just completed for this symbol."""
    if symbol not in state:
        state[symbol] = {}
    state[symbol]["last_full_scrape"] = datetime.now(timezone.utc).isoformat()


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

    # Balance sheet (8-year history)
    hist_debt: Dict[str, float] = field(default_factory=dict)
    hist_cash: Dict[str, float] = field(default_factory=dict)
    hist_equity: Dict[str, float] = field(default_factory=dict)

    # Margins (8-year history, % values)
    hist_net_margin: Dict[str, float] = field(default_factory=dict)
    # MarketScreener labels this as "EBIT Margin" — renamed from hist_operating_margin
    # for accuracy (EBIT ≠ operating income for all companies, especially banks).
    hist_ebit_margin: Dict[str, float] = field(default_factory=dict)
    hist_ebitda_margin: Dict[str, float] = field(default_factory=dict)
    hist_gross_margin: Dict[str, float] = field(default_factory=dict)

    # Returns (8-year history, % values)
    hist_roe: Dict[str, float] = field(default_factory=dict)
    hist_roce: Dict[str, float] = field(default_factory=dict)

    # Valuation multiple history
    hist_ev_ebitda: Dict[str, float] = field(default_factory=dict)

    # Dividend per share (8-year history, MAD)
    hist_dividend_per_share: Dict[str, float] = field(default_factory=dict)

    # EPS growth %: scraped directly from MS's "EPS change" row when available,
    # falls back to YoY computation from hist_eps for any missing years.
    hist_eps_growth: Dict[str, float] = field(default_factory=dict)

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

        # EPS growth %. Prefer MarketScreener's own "EPS change" row (scraped
        # directly in scrape_finances_page) since it uses adjusted/diluted EPS
        # that may differ from a naive YoY computation. For any year that MS
        # didn't report, fall back to computing from hist_eps.
        years = sorted(self.hist_eps.keys())
        for i in range(1, len(years)):
            prev_y, curr_y = years[i - 1], years[i]
            if curr_y in self.hist_eps_growth:
                continue  # MS-reported value already present — keep it
            prev = self.hist_eps.get(prev_y)
            curr = self.hist_eps.get(curr_y)
            if prev is None or curr is None:
                continue
            if abs(prev) <= 0.01 or abs(prev) >= 1000 or abs(curr) >= 1000:
                continue
            growth = (curr - prev) / abs(prev) * 100
            if -500 < growth < 500:
                self.hist_eps_growth[curr_y] = round(growth, 2)

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
        # Require at least 2 dot-groups (e.g. "1.234.567") to treat as
        # thousand separation. A single group like "6.185" is ambiguous
        # but almost always a decimal on MarketScreener.
        if re.fullmatch(r'-?\d{1,3}(?:\.\d{3}){2,}', compact):
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


def find_all_in_kv(pairs: List[Tuple[str, str]], label_patterns: List[str]) -> List[str]:
    """Return ALL values whose label matches any of the given regex patterns,
    in original order. Useful when the first match is a scale/axis label and
    a later match is the real value."""
    compiled = [re.compile(p, re.IGNORECASE) for p in label_patterns]
    out: List[str] = []
    for label, value in pairs:
        for rx in compiled:
            if rx.search(label):
                out.append(value)
                break
    return out


_CONSENSUS_KEYWORDS = (
    'OUTPERFORM', 'UNDERPERFORM', 'ACCUMULATE', 'NEUTRAL',
    'BUY', 'HOLD', 'SELL',
)


def parse_rating_keyword(text: Optional[str]) -> Optional[str]:
    """
    Return exactly one rating keyword if the text contains precisely one,
    otherwise None. This prevents scale/axis labels — which contain ALL
    keywords (e.g. "Sell Underperform Hold Buy Outperform") — from being
    misread as a specific rating.

    Uses word boundaries so "STRONG BUY" → "BUY" and "MEAN CONSENSUS: BUY"
    → "BUY" work correctly.
    """
    if not text:
        return None
    up = text.upper()
    hits = [kw for kw in _CONSENSUS_KEYWORDS if re.search(rf'\b{kw}\b', up)]
    return hits[0] if len(hits) == 1 else None


# =============================================================================
# Selenium Scraper
# =============================================================================

class SeleniumScraper:
    def __init__(self, headless: bool = True, debug: bool = False, user_agent: Optional[str] = None, worker_id: int = 0):
        """Initialize Selenium driver (uses undetected-chromedriver when available)."""
        self.debug = debug
        ua = user_agent or random.choice(USER_AGENTS)

        # Ensure workers don't collide when creating Chrome profiles
        import tempfile
        import os as _os
        base_tmp = Path(tempfile.gettempdir()) / f"marketscreener_uc_{worker_id}_{int(time.time())}"
        base_tmp.mkdir(parents=True, exist_ok=True)

        if HAS_UC:
            # -------------------------------------------------------
            # undetected-chromedriver: patches navigator.webdriver,
            # removes automation markers from the Chrome binary, and
            # bypasses Cloudflare/JS bot-detection used by MS.
            #
            # IMPORTANT for Windows / Chrome 112+:
            #   - Do NOT pass --headless=new as a flag — it crashes the
            #     renderer on Windows. Let UC manage headless itself via
            #     the headless= constructor parameter.
            #   - --no-sandbox and --disable-gpu also destabilise UC on
            #     Windows; they are omitted here intentionally.
            #
            # WinError 10053 / network abort fix:
            #   UC re-downloads chromedriver on every run if it thinks the
            #   cached binary is stale. On networks with strict firewalls
            #   this download gets aborted. Solution: if the patched driver
            #   already exists in the UC cache dir, pass it via
            #   driver_executable_path so UC skips the network step.
            # -------------------------------------------------------
            logger.info("🌐 Starting Chrome (undetected-chromedriver)...")
            uc_options = uc.ChromeOptions()
            uc_options.add_argument('--disable-dev-shm-usage')
            uc_options.add_argument('--window-size=1920,1080')
            uc_options.add_argument('--lang=en-US,en')
            uc_options.add_argument(f'--user-agent={ua}')

            # Locate the UC cache dir (Windows: %APPDATA%\undetected_chromedriver)
            _uc_cache = Path(_os.environ.get("APPDATA", "")) / "undetected_chromedriver" / "undetected_chromedriver.exe"
            _driver_path = str(_uc_cache) if _uc_cache.exists() else None
            if _driver_path:
                logger.info(f"   Using cached UC driver: {_driver_path}")
            else:
                logger.info("   UC driver not cached yet — will auto-download once.")

            try:
                # headless= is handled natively by UC — do NOT also add
                # --headless=new to uc_options or the renderer will crash.
                self.driver = uc.Chrome(
                    options=uc_options,
                    headless=headless,
                    driver_executable_path=_driver_path,  # None = let UC download
                    user_data_dir=str(base_tmp),
                )
                # Suppress annoying WinError 6 on process shutdown (UC bug on Windows)
                _uc_class = self.driver.__class__
                if not hasattr(_uc_class, '_patched_del'):
                    _orig_del = _uc_class.__del__
                    def _silent_del(instance):
                        try:
                            _orig_del(instance)
                        except OSError as e:
                            if e.winerror != 6:
                                raise
                        except Exception:
                            pass
                    _uc_class.__del__ = _silent_del
                    _uc_class._patched_del = True

            except Exception as exc:
                logger.error(f"undetected-chromedriver failed: {exc}")
                raise
        else:
            # -------------------------------------------------------
            # Fallback: plain selenium (less stealthy, may get blocked)
            # -------------------------------------------------------
            logger.warning("⚠ undetected-chromedriver not found — falling back to plain Selenium.")
            logger.warning("  Install with: pip install undetected-chromedriver")
            chrome_options = Options()
            if headless:
                chrome_options.add_argument('--headless=new')
            chrome_options.add_argument('--no-sandbox')
            chrome_options.add_argument('--disable-dev-shm-usage')
            chrome_options.add_argument('--disable-gpu')
            chrome_options.add_argument('--window-size=1920,1080')
            chrome_options.add_argument('--lang=en-US,en')
            chrome_options.add_argument(f'--user-agent={ua}')
            logger.info("🌐 Starting Chrome (plain Selenium)...")
            try:
                self.driver = webdriver.Chrome(options=chrome_options)
            except WebDriverException as exc:
                logger.error(f"Failed to start Chrome: {exc}")
                raise

        self.driver.set_page_load_timeout(60)  # increased: MS pages are slow
    
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

    def _parse_year_tables(
        self,
        soup: BeautifulSoup,
        label_map: List[Tuple[Any, Dict[str, float], bool]],
        growth_map: Optional[Dict[int, Dict[str, float]]] = None,
    ) -> None:
        """
        Generic year-column table parser reused across finances, ratios,
        cash-flow, and valuation pages.

        *label_map*: list of ``(regex_pattern, target_dict, is_primary)``
        *growth_map*: optional ``{id(primary_dict): growth_dict}`` for bare
        "Change"/"Growth" sub-rows that inherit context from the previous
        primary row.
        """
        if growth_map is None:
            growth_map = {}

        bare_change_re = re.compile(
            r'^\s*(?:%\s*)?'
            r'(?:change|growth|chg\.?|var\.?|variation|delta|δ|'
            r'y\s*[/\-\s]\s*y|yoy|y\-o\-y)'
            r'\s*(?:%|\(%\))?\s*$',
            re.IGNORECASE,
        )

        compiled_patterns = [(re.compile(pat, re.IGNORECASE), tgt, pri)
                             for pat, tgt, pri in label_map]

        for table in soup.find_all('table'):
            rows = list(table.find_all('tr'))
            if not rows:
                continue

            header_row = rows[0]
            headers = [th.get_text(strip=True) for th in header_row.find_all(['th', 'td'])]

            years: List[str] = []
            year_indices: List[int] = []
            for i, h in enumerate(headers):
                if re.match(r'^20\d{2}$', h):
                    years.append(h)
                    year_indices.append(i)

            if not years:
                continue

            last_primary: Optional[Dict[str, float]] = None

            for row in rows[1:]:
                cells = row.find_all(['td', 'th'])
                if len(cells) < 2:
                    continue

                label = cells[0].get_text(strip=True).lower()
                target: Optional[Dict[str, float]] = None
                is_primary = False

                # Bare growth/change sub-row
                if bare_change_re.match(label):
                    if last_primary is not None:
                        growth_series = growth_map.get(id(last_primary))
                        if growth_series is not None:
                            target = growth_series
                else:
                    for rx, tgt, pri in compiled_patterns:
                        if rx.search(label):
                            target = tgt
                            is_primary = pri
                            break

                if target is not None:
                    for idx, year in zip(year_indices, years):
                        if idx < len(cells):
                            val = parse_number(cells[idx].get_text(strip=True))
                            if val is not None:
                                target[year] = val

                if is_primary:
                    last_primary = target

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
                r'(\d[\d\s.,]*\d)\s*MAD\b',
                r'Last\s*(?:Price|Quote)?[:\s]+(\d[\d\s.,]*\d)',
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

        # Regex fallback on flattened text — MS sometimes renders the cap
        # outside any KV-shaped widget (e.g. inside a header banner).
        if not data.market_cap:
            for pattern in [
                r'(?:Market\s*Cap|Cap\.?\s*bours[a-z]*|Capitali[sz]ation)[\s:]+([\d.,\s]+[KMBT]?)\s*(?:MAD|EUR|USD)?',
                r'Cap\.?[\s:]+([\d.,\s]+[KMBT])\s*(?:MAD|EUR|USD)',
            ]:
                m = re.search(pattern, page_text, re.IGNORECASE)
                if m:
                    mcap = parse_number(m.group(1))
                    if mcap and mcap > 1e6:
                        data.market_cap = mcap
                        logger.info(f"✓ Market Cap (fallback): {mcap:,.0f}")
                        break

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
        # MS uses a variety of labels: "52w High", "52-Week High", "1Y High",
        # "High 1 Year", "Plus haut 1 an", "Plus haut 52 sem.", "Annual High".
        high_value = find_in_kv(kv, [
            r'52[\s\-]*(?:weeks?|w)\s*high',
            r'(?:1\s*Y(?:ear)?|Annual)\s*High',
            r'High\s*1\s*Y(?:ear)?',
            r'Plus\s+haut\s+(?:1\s*an|52)',
            r'(?:Plus|Highest).*52',
        ])
        if high_value:
            high = parse_number(high_value)
            if high and data.price and 0.5 <= high / data.price <= 3:
                data.high_52w = high
                logger.info(f"✓ 52w High: {high}")

        low_value = find_in_kv(kv, [
            r'52[\s\-]*(?:weeks?|w)\s*low',
            r'(?:1\s*Y(?:ear)?|Annual)\s*Low',
            r'Low\s*1\s*Y(?:ear)?',
            r'Plus\s+bas\s+(?:1\s*an|52)',
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
            r'^Vol\.?\s*(?:moyen|avg|average)?',
            r'Average\s+Volume',
            r'Volume\s+20\s*d',
        ])
        if vol_value:
            vol = parse_number(vol_value)
            if vol and vol >= 0:
                data.volume = int(vol)
                logger.info(f"✓ Volume: {vol:,.0f}")

        # ----- Consensus rating (also shown in the main quote page sidebar) -----
        # Try ALL matching KV cells — the first one is often a scale/axis
        # label bar (contains every rating keyword), while a later one is the
        # actual value. parse_rating_keyword() rejects multi-keyword values.
        consensus_label_patterns = [
            r'(?:Mean|Consensus|Average)\s+(?:recommendation|consensus)',
            r'^Consensus\b',
            r'^Recommendation\b',
            r'^Recommandation\b',
        ]
        for cand in find_all_in_kv(kv, consensus_label_patterns):
            parsed = parse_rating_keyword(cand)
            if parsed:
                data.consensus = parsed
                logger.info(f"✓ Consensus: {parsed}")
                break

        # ----- Number of analysts (also on the quote page summary) -----
        analysts_value = find_in_kv(kv, [
            r'(?:Number\s+of\s+)?Analysts',
            r'Nombre\s+d.?analystes',
            r'Coverage',
        ])
        if analysts_value:
            n = parse_number(analysts_value)
            if n and 1 <= n <= 100:
                data.num_analysts = int(n)
                logger.info(f"✓ Analysts: {data.num_analysts}")
    
    def scrape_finances_page(self, data: StockData, url_code: str) -> None:
        """Scrape financial tables."""
        url = f"{BASE_URL}/{url_code}/finances/"

        logger.info(f"📊 Loading financials...")
        self.driver.get(url)
        soup = self._wait_and_get_soup(wait_seconds=3)
        self._maybe_dump_html(data.symbol, "finances")

        # The label_map order matters: specific ratios and growth rows are
        # checked BEFORE broad metric rows so that labels like "EV / Sales"
        # don't bleed into hist_revenue and "EPS change" doesn't bleed into
        # hist_eps.  Entries whose target is None are matched-and-skipped by
        # _parse_year_tables (the helper skips None targets after matching).
        # We encode them here via a sentinel empty dict that we discard.
        _skip: Dict[str, float] = {}

        label_map: List[Tuple[str, Dict[str, float], bool]] = [
            # Valuation multiples
            (r'(?:ev\s*/\s*ebitda|enterprise\s*value\s*/\s*ebitda)', data.hist_ev_ebitda, True),
            # Skip all other ratio rows with '/' (EV/Sales, P/E, P/BV, etc.)
            (r'/', _skip, False),
            # Named growth / change rows
            (r'(?:eps|earnings|bpa)\s*(?:growth|change|chg|var|croissance|variation)', data.hist_eps_growth, False),
            (r'(?:revenue|sales)\s*growth', _skip, False),
            # Per-share rows (DPS and EPS matched first, then skip other per-share)
            (r'(?:dividend\s*per\s*share|dividende\s*par\s*action|^dps$)', data.hist_dividend_per_share, True),
            (r'earnings\s*per\s*share', data.hist_eps, True),
            (r'per\s*share', _skip, False),
            # Absolute metrics (income statement + cash flow)
            (r'(?:revenue|(?:net\s*)?sales|turnover)(?!.*growth)', data.hist_revenue, True),
            (r'(?:net\s*income|net\s*profit)(?!.*(?:margin|growth))', data.hist_net_income, True),
            (r'(?:^eps|earnings\s*per\s*share)', data.hist_eps, True),
            (r'ebitda(?!.*margin)', data.hist_ebitda, True),
            (r'(?:free\s*cash\s*flow|fcf)(?!.*(?:margin|growth|cagr|yield))', data.hist_fcf, True),
            (r'operating\s*cash\s*flow(?!.*(?:margin|growth|cagr))', data.hist_ocf, True),
            (r'(?:capex|capital\s*expenditure)(?!.*(?:margin|growth|cagr))', data.hist_capex, True),
            # Balance sheet
            (r'(?:net\s*debt|financial\s*debt|^debt$)', data.hist_debt, True),
            (r'cash(?!.*flow)(?!.*capex)', data.hist_cash, True),
            (r'(?:shareholders?\s*equity|stockholders?\s*equity|shareholders?\s*funds|^(?:equity|total\s*equity)$)(?!.*return)', data.hist_equity, True),
            # Margins
            (r'(?:net|profit)\s*margin', data.hist_net_margin, True),
            (r'(?:ebit|operating)\s*margin', data.hist_ebit_margin, True),
            (r'ebitda\s*margin', data.hist_ebitda_margin, True),
            # Returns
            (r'(?:return\s*on\s*equity|^roe$)', data.hist_roe, True),
            (r'(?:return\s*on\s*(?:total\s*)?capital|roce|return\s*on\s*capital\s*employed)', data.hist_roce, True),
        ]

        growth_map = {id(data.hist_eps): data.hist_eps_growth}

        self._parse_year_tables(soup, label_map, growth_map)

    def scrape_ratios_page(self, data: StockData, url_code: str) -> None:
        """Scrape financial ratios page (margins, ROE, ROCE)."""
        url = f"{BASE_URL}/{url_code}/finances-ratios/"

        logger.info(f"📊 Loading financial ratios...")
        self.driver.get(url)
        soup = self._wait_and_get_soup(wait_seconds=3)
        self._maybe_dump_html(data.symbol, "ratios")

        label_map: List[Tuple[str, Dict[str, float], bool]] = [
            # Margins (exclude growth/CAGR rows like "Gross Profit, 1 Yr. Growth %")
            (r'gross\s*(?:profit\s*)?margin\s*%?(?!.*(?:growth|cagr))', data.hist_gross_margin, True),
            (r'net\s*(?:income\s*)?margin\s*%?(?!.*(?:growth|cagr))', data.hist_net_margin, True),
            (r'ebit[^d]?\s*margin\s*%?(?!.*(?:growth|cagr))', data.hist_ebit_margin, True),
            (r'ebitda\s*margin\s*%?(?!.*(?:growth|cagr))', data.hist_ebitda_margin, True),
            # Returns (exclude growth/CAGR rows)
            (r'return\s*on\s*equity\s*%?(?!.*(?:growth|cagr))', data.hist_roe, True),
            (r'(?:return\s*on\s*(?:total\s*)?capital|roce)(?!.*(?:growth|cagr))', data.hist_roce, True),
        ]

        self._parse_year_tables(soup, label_map)

    @staticmethod
    def _normalize_to_millions(series: Dict[str, float]) -> None:
        """
        The cash-flow / balance-sheet page on MarketScreener displays values
        with B/M suffixes (e.g. "6.01B", "398M") which parse_number expands
        to raw MAD.  The finances page, however, stores the same metrics as
        plain numbers in **millions MAD** (footnote ¹MAD in Million).

        To keep every hist_* series in a single unit (millions MAD), convert
        any value whose absolute magnitude ≥ 1 000 000 (i.e. clearly raw MAD
        rather than millions) by dividing by 1 000 000.
        """
        for year, val in series.items():
            if abs(val) >= 1_000_000:
                series[year] = round(val / 1_000_000, 2)

    def scrape_cashflow_page(self, data: StockData, url_code: str) -> None:
        """Scrape cash flow statement page (OCF)."""
        url = f"{BASE_URL}/{url_code}/finances-cash-flow-statement/"

        logger.info(f"📊 Loading cash flow statement...")
        self.driver.get(url)
        soup = self._wait_and_get_soup(wait_seconds=3)
        self._maybe_dump_html(data.symbol, "cashflow")

        # Collect into temporary dicts so we can normalize before merging
        # into data.* (which may already have millions-scale values from
        # the finances page).
        tmp_ocf: Dict[str, float] = {}
        tmp_fcf: Dict[str, float] = {}
        tmp_capex: Dict[str, float] = {}
        tmp_cash: Dict[str, float] = {}
        tmp_equity: Dict[str, float] = {}
        _skip: Dict[str, float] = {}

        label_map: List[Tuple[str, Dict[str, float], bool]] = [
            # Skip ratio rows containing '/' FIRST (e.g. "Debt / (EBITDA - Capex)")
            # so they don't pollute the real metric rows below.
            (r'/', _skip, False),
            # Skip growth / CAGR sub-rows
            (r'(?:growth|cagr)\s*%', _skip, False),
            (r'(?:cash\s*from\s*operations?|operating\s*cash\s*flow)(?!.*(?:growth|cagr|margin|liabilities))', tmp_ocf, True),
            (r'(?:free\s*cash\s*flow|(?:^|\b)fcf\b)(?!.*(?:growth|cagr|margin|yield))', tmp_fcf, True),
            (r'(?:capex|capital\s*expenditure)(?!.*(?:growth|cagr|margin))', tmp_capex, True),
            # Balance sheet items also appear on this page
            (r'(?:cash\s*and\s*equivalents|total\s*cash\s*and\s*short)', tmp_cash, True),
            (r'(?:total\s*(?:common\s*)?equity|shareholders?\s*equity)(?!.*(?:growth|cagr|debt|return))', tmp_equity, True),
        ]

        self._parse_year_tables(soup, label_map)

        # Normalize raw-MAD values (from B/M suffixes) → millions MAD
        for tmp in (tmp_ocf, tmp_fcf, tmp_capex, tmp_cash, tmp_equity):
            self._normalize_to_millions(tmp)

        # Merge: cash-flow page fills gaps but does NOT overwrite existing
        # values from the finances page (which are already in millions).
        for src, dst in [
            (tmp_ocf, data.hist_ocf),
            (tmp_fcf, data.hist_fcf),
            (tmp_capex, data.hist_capex),
            (tmp_cash, data.hist_cash),
            (tmp_equity, data.hist_equity),
        ]:
            for year, val in src.items():
                if year not in dst:
                    dst[year] = val

    def scrape_valuation_page(self, data: StockData, url_code: str) -> None:
        """Scrape valuation page for Price-to-Book."""
        url = f"{BASE_URL}/{url_code}/valuation/"

        logger.info(f"📊 Loading valuation page...")
        self.driver.get(url)
        soup = self._wait_and_get_soup(wait_seconds=3)
        self._maybe_dump_html(data.symbol, "valuation")

        # Try KV extraction first (summary/sidebar)
        if data.price_to_book is None:
            kv = extract_kv_pairs(soup)
            pb_value = find_in_kv(kv, [
                r'Price\s*to\s*book\s*value',
                r'^P\s*/\s*B(?:V|R)?\b',
                r'^PBR\b',
                r'^Price\s*/\s*Book',
            ])
            if pb_value:
                pb = parse_number(pb_value)
                if pb and 0.01 <= pb <= 100:
                    data.price_to_book = pb
                    logger.info(f"✓ P/B (valuation page KV): {pb}")

        # Fallback: parse year-column table for PBR / P/BV row
        if data.price_to_book is None:
            temp_pbv: Dict[str, float] = {}
            label_map: List[Tuple[str, Dict[str, float], bool]] = [
                (r'(?:price\s*to\s*book|p\s*/\s*bv|pbr\b)', temp_pbv, True),
            ]
            self._parse_year_tables(soup, label_map)
            if temp_pbv:
                current_year = str(datetime.now().year)
                candidates = {y: v for y, v in temp_pbv.items() if y <= current_year}
                if candidates:
                    latest = max(candidates.keys())
                    pb = candidates[latest]
                    if 0.01 <= pb <= 100:
                        data.price_to_book = pb
                        logger.info(f"✓ P/B (valuation table, {latest}): {pb}")

        # Fill DPS from this page if finances page missed it
        if not data.hist_dividend_per_share:
            temp_dps: Dict[str, float] = {}
            label_map_dps: List[Tuple[str, Dict[str, float], bool]] = [
                (r'dividend\s*per\s*share', temp_dps, True),
            ]
            self._parse_year_tables(soup, label_map_dps)
            if temp_dps:
                data.hist_dividend_per_share.update(temp_dps)

        # Also fill EV/EBITDA history if not already populated
        if not data.hist_ev_ebitda:
            label_map_ev: List[Tuple[str, Dict[str, float], bool]] = [
                (r'(?:ev\s*/\s*ebitda|enterprise\s*value\s*/\s*ebitda)', data.hist_ev_ebitda, True),
            ]
            self._parse_year_tables(soup, label_map_ev)

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
            r'Coverage',
        ])
        if analysts_value:
            n = parse_number(analysts_value)
            if n and 1 <= n <= 100:
                data.num_analysts = int(n)
                logger.info(f"✓ Analysts: {data.num_analysts}")

        # Regex fallback: MS sometimes renders the analyst count as plain text
        # outside a KV widget, e.g. "Number of Analysts 2" or "Coverage: 2 analysts".
        if data.num_analysts is None:
            for pattern in [
                r'Number\s+of\s+Analysts[\s:]*(\d{1,3})',
                r'Nombre\s+d.?analystes[\s:]*(\d{1,3})',
                r'\b(\d{1,3})\s+analysts?\b',
            ]:
                m = re.search(pattern, page_text, re.IGNORECASE)
                if m:
                    n = int(m.group(1))
                    if 1 <= n <= 100:
                        data.num_analysts = n
                        logger.info(f"✓ Analysts (fallback): {n}")
                        break

        # ----- Consensus rating -----
        # IMPORTANT: only SET the value; never OVERWRITE a good value that
        # the main quote page already extracted. MS's /consensus/ page has a
        # rating-scale axis ("Sell | Underperform | Hold | Buy | Outperform")
        # that can poison naive KV matching. parse_rating_keyword() rejects
        # any value that contains more than one rating keyword.
        if data.consensus is None:
            consensus_label_patterns = [
                r'(?:Mean|Consensus|Average)\s+(?:recommendation|consensus)',
                r'^Consensus\b',
                r'^Recommendation\b',
                r'^Recommandation\b',
            ]
            for cand in find_all_in_kv(kv, consensus_label_patterns):
                parsed = parse_rating_keyword(cand)
                if parsed:
                    data.consensus = parsed
                    logger.info(f"✓ Consensus: {parsed}")
                    break

        # Regex fallback on page text: require "Mean consensus" specifically
        # (not just "Consensus", which matches the axis-label header), and
        # require the rating word to be followed by a non-letter boundary so
        # we don't grab the first word of a scale bar like "Sell Underperform".
        if data.consensus is None:
            m = re.search(
                r'Mean\s+consensus\s*[:\-]?\s*'
                r'(BUY|OUTPERFORM|ACCUMULATE|HOLD|NEUTRAL|UNDERPERFORM|SELL)\b',
                page_text,
                re.IGNORECASE,
            )
            if m:
                parsed = parse_rating_keyword(m.group(1))
                if parsed:
                    data.consensus = parsed
                    logger.info(f"✓ Consensus (fallback): {parsed}")
    
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

    def hard_clear_session(self) -> None:
        """
        Wipe cookies + localStorage + sessionStorage + HTTP cache so
        MarketScreener treats us as a brand-new visitor. Used when we hit
        the site's daily article/view limit — clearing the session is what
        actually resets the quota counter.
        """
        try:
            self.driver.delete_all_cookies()
        except Exception as exc:
            logger.warning(f"   delete_all_cookies failed: {exc}")
        try:
            # Storage clears require being on a same-origin page.
            self.driver.get("https://www.marketscreener.com/")
            self.driver.execute_script(
                "try { window.localStorage.clear(); } catch(e) {}"
                "try { window.sessionStorage.clear(); } catch(e) {}"
            )
        except Exception as exc:
            logger.warning(f"   storage clear failed: {exc}")
        # CDP-level cache + cookie wipe (Chrome-only, best effort).
        for cmd in ("Network.clearBrowserCookies", "Network.clearBrowserCache"):
            try:
                self.driver.execute_cdp_cmd(cmd, {})
            except Exception:
                pass
        logger.info("   🧹 cleared cookies + storage + cache")

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

    def _handle_rate_limit(self, page_name: str) -> None:
        """Clear cookies/cache and wait when rate-limited."""
        logger.warning(f"⚠ Rate-limited on {page_name} — clearing session...")
        self.hard_clear_session()
        wait = random.uniform(10, 20)
        logger.info(f"   ⏳ Waiting {wait:.0f}s before retrying...")
        time.sleep(wait)

    def scrape(self, symbol: str, url_code: str) -> StockData:
        """Main scraping orchestrator."""
        logger.info(f"\n{'='*60}")
        logger.info(f"Scraping {symbol} with Selenium")
        logger.info(f"{'='*60}")

        data = StockData(symbol=symbol)

        pages = [
            ("main",      self.scrape_main_page),
            ("finances",  self.scrape_finances_page),
            ("ratios",    self.scrape_ratios_page),
            ("cashflow",  self.scrape_cashflow_page),
            ("valuation", self.scrape_valuation_page),
            ("consensus", self.scrape_consensus_page),
        ]

        for page_name, scrape_fn in pages:
            scrape_fn(data, url_code)

            if self.looks_rate_limited():
                self._handle_rate_limit(page_name)
                # Retry the same page once after clearing
                scrape_fn(data, url_code)
                if self.looks_rate_limited():
                    data.scrape_warnings.append(f"Rate-limited on {page_name} (gave up after retry)")
                    logger.error(f"   Still rate-limited on {page_name} after clear — skipping remaining pages")
                    break

            time.sleep(random.uniform(1.5, 3.0))

        data.validate()

        return data

    def scrape_daily(self, symbol: str, url_code: str, existing_json_path: Optional[Path] = None) -> StockData:
        """
        Daily scrape: only main page + consensus (2 pages instead of 6).
        Merges fresh market data into existing historical data from the JSON file.
        """
        logger.info(f"\n{'='*60}")
        logger.info(f"Scraping {symbol} — DAILY mode (main + consensus)")
        logger.info(f"{'='*60}")

        # Load existing data to preserve historical fundamentals
        existing: Dict[str, Any] = {}
        json_path = existing_json_path or (DATA_DIR / f"{symbol}_marketscreener_v3.json")
        if json_path.exists():
            try:
                with open(json_path, 'r', encoding='utf-8') as f:
                    existing = json.load(f)
                logger.info(f"   Loaded existing data from {json_path.name}")
            except (json.JSONDecodeError, OSError) as exc:
                logger.warning(f"   Could not load existing data: {exc}")

        data = StockData(symbol=symbol)

        # Restore all historical series from the existing file
        hist_fields = [
            'hist_revenue', 'hist_net_income', 'hist_eps', 'hist_ebitda',
            'hist_fcf', 'hist_ocf', 'hist_capex',
            'hist_debt', 'hist_cash', 'hist_equity',
            'hist_net_margin', 'hist_ebit_margin', 'hist_ebitda_margin',
            'hist_gross_margin', 'hist_roe', 'hist_roce',
            'hist_ev_ebitda', 'hist_dividend_per_share', 'hist_eps_growth',
        ]
        for field_name in hist_fields:
            if field_name in existing and existing[field_name]:
                getattr(data, field_name).update(existing[field_name])

        # Scrape only 2 pages
        pages = [
            ("main",      self.scrape_main_page),
            ("consensus", self.scrape_consensus_page),
        ]

        for page_name, scrape_fn in pages:
            scrape_fn(data, url_code)

            if self.looks_rate_limited():
                self._handle_rate_limit(page_name)
                scrape_fn(data, url_code)
                if self.looks_rate_limited():
                    data.scrape_warnings.append(f"Rate-limited on {page_name} (gave up after retry)")
                    logger.error(f"   Still rate-limited on {page_name} after clear — skipping")
                    break

            time.sleep(random.uniform(1.5, 3.0))

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


def _read_text_best_effort(path: Path) -> str:
    """Read a text file with encoding fallbacks (handles UTF-16 exports)."""
    for enc in ("utf-8-sig", "utf-16", "utf-16-le", "utf-16-be", "latin-1"):
        try:
            return path.read_text(encoding=enc)
        except UnicodeError:
            continue
    return path.read_text(encoding="utf-8", errors="ignore")


def _find_market_links_file() -> Optional[Path]:
    """Return the first existing marketscreener-link markdown file."""
    for p in MARKET_LINKS_PATHS:
        if p.exists():
            return p
    return None


def _guess_symbol_from_slug(url_code: str) -> Optional[str]:
    """
    Guess ticker from MarketScreener slug when available
    (e.g. ITISSALAT-AL-MAGHRIB-IAM--1408717 -> IAM).
    """
    m = re.search(r"-([A-Z0-9]{2,6})--\d+$", url_code)
    if m:
        return m.group(1)
    m = re.search(r"-([A-Z0-9]{2,6})-\d+$", url_code)
    if m:
        return m.group(1)
    return None


def _merge_instruments(primary: List[Dict[str, Any]], secondary: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """
    Merge two instrument lists by symbol.
    Primary keeps precedence; secondary fills missing name/url_code and adds new symbols.
    """
    merged: List[Dict[str, Any]] = []
    idx_by_symbol: Dict[str, int] = {}

    for inst in primary:
        symbol = str(inst.get("symbol", "")).upper().strip()
        if not symbol:
            continue
        cleaned = dict(inst)
        cleaned["symbol"] = symbol
        idx_by_symbol[symbol] = len(merged)
        merged.append(cleaned)

    for inst in secondary:
        symbol = str(inst.get("symbol", "")).upper().strip()
        if not symbol:
            continue
        if symbol in idx_by_symbol:
            cur = merged[idx_by_symbol[symbol]]
            if not cur.get("url_code") and inst.get("url_code"):
                cur["url_code"] = inst.get("url_code")
            if not cur.get("name") and inst.get("name"):
                cur["name"] = inst.get("name")
            continue
        cleaned = dict(inst)
        cleaned["symbol"] = symbol
        idx_by_symbol[symbol] = len(merged)
        merged.append(cleaned)

    return merged


def _load_ms_instruments_from_links_file(ms_instruments: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """
    Parse MarketScreener quote URLs from the links markdown file and convert them
    into instrument entries with url_code.
    """
    links_path = _find_market_links_file()
    if not links_path:
        return []

    try:
        content = _read_text_best_effort(links_path)
    except OSError as exc:
        logger.warning(f"Could not read links file {links_path}: {exc}")
        return []

    if not content.strip():
        logger.warning(f"Links file is empty: {links_path}")
        return []

    known_symbols = {
        str(i.get("symbol", "")).upper()
        for i in ms_instruments
        if i.get("symbol")
    }
    name_by_symbol = {
        str(i.get("symbol", "")).upper(): i.get("name")
        for i in ms_instruments
        if i.get("symbol")
    }
    try:
        for inst in _load_casa_instruments():
            sym = str(inst.get("symbol", "")).upper()
            if not sym:
                continue
            known_symbols.add(sym)
            if sym not in name_by_symbol and inst.get("name"):
                name_by_symbol[sym] = inst.get("name")
    except FileNotFoundError:
        pass

    out: List[Dict[str, Any]] = []
    seen_symbols: Set[str] = set()
    for line in content.splitlines():
        upper_line = line.upper()
        line_tokens = re.findall(r"\b[A-Z0-9]{2,6}\b", upper_line)
        line_known_symbols = [tok for tok in line_tokens if tok in known_symbols]

        for match in MS_QUOTE_URL_RE.finditer(line):
            url_code = match.group(1).strip().strip("/")
            if not url_code:
                continue

            symbol: Optional[str] = line_known_symbols[0] if line_known_symbols else None
            if not symbol:
                symbol = _guess_symbol_from_slug(url_code)
            if not symbol:
                # Keep full coverage: when ticker is not recoverable from the line
                # or slug, use the slug itself as a stable identifier.
                symbol = url_code

            symbol = symbol.upper()
            if symbol in seen_symbols:
                continue
            seen_symbols.add(symbol)
            out.append({
                "symbol": symbol,
                "name": name_by_symbol.get(symbol, symbol),
                "url_code": url_code,
            })

    if out:
        logger.info(f"🔗 Loaded {len(out)} url_code entries from {links_path.name}")
    else:
        logger.warning(f"No usable MarketScreener links found in {links_path.name}")
    return out


def _ensure_market_universe(ms_instruments: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """
    Ensure instruments_marketscreener universe includes all Casablanca symbols,
    while preserving any known url_code values and non-Casablanca extras.
    """
    try:
        casa = _load_casa_instruments()
    except FileNotFoundError:
        return ms_instruments

    ms_by_symbol = {
        str(i.get("symbol", "")).upper(): i
        for i in ms_instruments
        if i.get("symbol")
    }
    universe: List[Dict[str, Any]] = []
    casa_symbols: Set[str] = set()
    for inst in casa:
        sym = str(inst.get("symbol", "")).upper()
        if not sym:
            continue
        casa_symbols.add(sym)
        existing = ms_by_symbol.get(sym, {})
        universe.append({
            "symbol": sym,
            "name": existing.get("name") or inst.get("name", sym),
            "url_code": existing.get("url_code"),
        })

    # Keep any extra markets already present in instruments_marketscreener.json.
    for inst in ms_instruments:
        sym = str(inst.get("symbol", "")).upper()
        if not sym or sym in casa_symbols:
            continue
        universe.append({
            "symbol": sym,
            "name": inst.get("name", sym),
            "url_code": inst.get("url_code"),
        })

    return universe


def _was_scraped_recently(symbol: str, max_age_hours: float) -> bool:
    f = DATA_DIR / f"{symbol}_marketscreener_v3.json"
    if not f.exists():
        return False
    age_h = (time.time() - f.stat().st_mtime) / 3600
    return age_h < max_age_hours


def _safe_print(text: str) -> None:
    """Print text safely on Windows CP1252 terminals — replaces unencodable chars."""
    try:
        print(text)
    except UnicodeEncodeError:
        print(text.encode(errors='replace').decode('ascii', errors='replace'))


def _print_summary(stock_data: StockData, output_file: Path) -> None:
    _safe_print(f"\n[OK] Completed {stock_data.symbol}")
    _safe_print(f"   Price: {stock_data.price} MAD" if stock_data.price else "   Price: N/A")
    _safe_print(f"   Market Cap: {stock_data.market_cap:,.0f} MAD" if stock_data.market_cap else "   Market Cap: N/A")
    _safe_print(f"   P/E: {stock_data.pe_ratio}" if stock_data.pe_ratio else "   P/E: N/A")
    _safe_print(f"   P/B: {stock_data.price_to_book}" if stock_data.price_to_book else "   P/B: N/A")
    _safe_print(f"   Div Yield: {stock_data.dividend_yield}%" if stock_data.dividend_yield else "   Div: N/A")
    _safe_print(f"   Consensus: {stock_data.consensus} | Target: {stock_data.target_price} | Analysts: {stock_data.num_analysts}")
    _safe_print(f"   Revenue: {len(stock_data.hist_revenue)} years")
    _safe_print(f"   EBITDA: {len(stock_data.hist_ebitda)} years")
    _safe_print(f"   Net Income: {len(stock_data.hist_net_income)} years")
    _safe_print(f"   EPS: {len(stock_data.hist_eps)} years | growth: {len(stock_data.hist_eps_growth)} YoY points")
    _safe_print(f"   DPS: {len(stock_data.hist_dividend_per_share)} years")
    _safe_print(f"   Debt: {len(stock_data.hist_debt)} years | Cash: {len(stock_data.hist_cash)} years | Equity: {len(stock_data.hist_equity)} years")
    _safe_print(f"   OCF: {len(stock_data.hist_ocf)} years")
    _safe_print(f"   Margins (gross/net/ebit/ebitda): {len(stock_data.hist_gross_margin)}/{len(stock_data.hist_net_margin)}/{len(stock_data.hist_ebit_margin)}/{len(stock_data.hist_ebitda_margin)} years")
    _safe_print(f"   ROE: {len(stock_data.hist_roe)} years | ROCE: {len(stock_data.hist_roce)} years | EV/EBITDA: {len(stock_data.hist_ev_ebitda)} years")

    # Scalar fields + historical series (each present series counts as 1).
    scalar_checks = [
        bool(stock_data.price), bool(stock_data.market_cap),
        bool(stock_data.pe_ratio), bool(stock_data.price_to_book),
        bool(stock_data.dividend_yield),
        bool(stock_data.high_52w), bool(stock_data.low_52w),
        bool(stock_data.consensus), bool(stock_data.target_price),
    ]
    history_checks = [
        bool(stock_data.hist_revenue), bool(stock_data.hist_net_income),
        bool(stock_data.hist_eps), bool(stock_data.hist_ebitda),
        bool(stock_data.hist_fcf), bool(stock_data.hist_ocf),
        bool(stock_data.hist_capex),
        bool(stock_data.hist_debt), bool(stock_data.hist_cash), bool(stock_data.hist_equity),
        bool(stock_data.hist_gross_margin),
        bool(stock_data.hist_net_margin), bool(stock_data.hist_ebit_margin),
        bool(stock_data.hist_ebitda_margin),
        bool(stock_data.hist_roe), bool(stock_data.hist_roce),
        bool(stock_data.hist_ev_ebitda),
        bool(stock_data.hist_dividend_per_share),
        bool(stock_data.hist_eps_growth),
    ]
    total_fields = len(scalar_checks) + len(history_checks)
    filled = sum(scalar_checks) + sum(history_checks)
    quality = (filled / total_fields) * 100 if total_fields else 0
    _safe_print(f"   Data Quality: {quality:.0f}% ({filled}/{total_fields})")
    _safe_print(f"   Saved to: {output_file.name}")


def _resolve_targets(args, ms_instruments: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Build the work list, merging Casablanca symbols with MS slugs as needed."""
    ms_by_symbol = {i['symbol'].upper(): i for i in ms_instruments}

    if args.all or args.all_casa:
        return ms_instruments

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

    # Interactive picker.
    print("\n📊 MarketScreener Scraper V3 (Selenium)")
    print("=" * 60)
    print(f"  [0] ALL ({len(ms_instruments)} stocks)")
    for i, inst in enumerate(ms_instruments, 1):
        print(f"  [{i}] {inst['symbol']:5s} - {inst['name']}")
    try:
        choice = int(input("\nSelect number: "))
        if choice == 0:
            return ms_instruments
        return [ms_instruments[choice - 1]]
    except (ValueError, IndexError):
        print("❌ Invalid selection")
        return []


def _scrape_batch(batch_args):
    """
    Worker function for parallel scraping.
    Runs in its own process with its own Chrome instance.
    Auto-selects daily vs full mode per symbol based on scrape state.
    """
    (worker_id, instruments, headful, debug, delay_min, delay_max,
     restart_every, resume, max_age_hours, force_full) = batch_args

    # Stagger start so workers don't hit the server simultaneously
    time.sleep(worker_id * 5)

    tag = f"[W{worker_id}]"
    scraper = SeleniumScraper(headless=not headful, debug=debug, worker_id=worker_id)
    processed = 0
    failed_symbols = []
    state = _load_scrape_state()

    def _restart():
        nonlocal scraper
        try:
            scraper.close()
        except Exception:
            pass
        scraper = SeleniumScraper(headless=not headful, debug=debug, worker_id=worker_id)

    try:
        for idx, inst in enumerate(instruments, 1):
            symbol = inst['symbol']

            if resume and _was_scraped_recently(symbol, max_age_hours):
                logger.info(f"{tag} [{idx}/{len(instruments)}] {symbol}: skipped (recent)")
                continue

            url_code = inst.get('url_code')
            if not url_code:
                url_code = scraper.discover_url_code(symbol, inst.get('name', symbol))
                if not url_code:
                    logger.warning(f"{tag} {symbol}: no MS slug found, skipped")
                    failed_symbols.append(symbol)
                    continue

            # Decide: daily or full scrape
            do_full = force_full or _needs_full_scrape(symbol, state)
            mode_label = "FULL" if do_full else "DAILY"
            logger.info(f"{tag} [{idx}/{len(instruments)}] {symbol} ({mode_label})")

            stock_data = None
            attempts = 0
            while True:
                attempts += 1
                try:
                    if do_full:
                        stock_data = scraper.scrape(symbol, url_code)
                    else:
                        stock_data = scraper.scrape_daily(symbol, url_code)
                except WebDriverException as exc:
                    logger.error(f"{tag} browser error on {symbol}: {exc}")
                    _restart()
                    if attempts >= 2:
                        failed_symbols.append(symbol)
                        stock_data = None
                        break
                    continue

                rate_limited = (
                    scraper.looks_rate_limited()
                    or any('Rate-limited' in w for w in stock_data.scrape_warnings)
                )
                if not rate_limited:
                    break

                logger.warning(f"{tag} rate-limited on {symbol}, clearing + restart...")
                try:
                    scraper.hard_clear_session()
                except Exception:
                    pass
                _restart()
                if attempts >= 2:
                    failed_symbols.append(symbol)
                    stock_data = None
                    break
                time.sleep(random.uniform(15, 30))

            if stock_data is not None:
                output_file = DATA_DIR / f"{symbol}_marketscreener_v3.json"
                with open(output_file, 'w', encoding='utf-8') as f:
                    json.dump(asdict(stock_data), f, indent=2, default=str, ensure_ascii=False)
                _print_summary(stock_data, output_file)
                processed += 1

                if do_full:
                    _mark_full_scrape(symbol, state)
                    _save_scrape_state(state)

            if restart_every and processed > 0 and processed % restart_every == 0:
                _restart()

            if idx < len(instruments):
                time.sleep(random.uniform(delay_min, delay_max))

    except KeyboardInterrupt:
        logger.info(f"{tag} interrupted")
    finally:
        _save_scrape_state(state)
        try:
            scraper.close()
        except Exception:
            pass

    return worker_id, processed, failed_symbols


def main():
    parser = argparse.ArgumentParser(description='MarketScreener Scraper V3 (Selenium)')
    parser.add_argument('--symbol', help='Stock symbol')
    parser.add_argument('--all', action='store_true',
                        help='Scrape full market universe (Casablanca list + instruments_marketscreener + links markdown).')
    parser.add_argument('--all-casa', action='store_true',
                        help='Scrape Casablanca SE universe '
                             '(kept for backward compatibility; same scope as --all).')
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
    parser.add_argument('--workers', type=int, default=1,
                        help='Number of parallel Chrome sessions (default 1). '
                             'Use 2-3 for faster runs. Each worker scrapes a subset of stocks.')
    parser.add_argument('--discover', action='store_true',
                        help='Only discover MarketScreener URL slugs for all stocks '
                             '(no data scraping). Fast: ~3-5 min for 80 stocks.')
    parser.add_argument('--full', action='store_true',
                        help='Force a full scrape (all 6 pages) even if a recent full scrape exists. '
                             'Without this flag, the scraper auto-selects daily mode (main + consensus) '
                             'when the last full scrape is less than 1 year old.')
    args = parser.parse_args()

    ms_instruments = _load_ms_instruments()
    ms_instruments = _ensure_market_universe(ms_instruments)
    link_instruments = _load_ms_instruments_from_links_file(ms_instruments)
    if link_instruments:
        ms_instruments = _merge_instruments(ms_instruments, link_instruments)
    if ms_instruments:
        _save_ms_instruments(ms_instruments)
        logger.info(f"📚 Synced {CONFIG_PATH.name} with {len(ms_instruments)} symbols")

    # ── Discover-only mode: find URL slugs without scraping data ──────
    if args.discover:
        missing = [i for i in ms_instruments if not i.get('url_code')]
        already = len(ms_instruments) - len(missing)
        _safe_print(f"\n🔎 Discover mode: {already} already have url_code, {len(missing)} to discover")
        if not missing:
            _safe_print("   All stocks already have url_codes. Nothing to do.")
            return

        scraper = SeleniumScraper(headless=not args.headful, debug=args.debug)
        found, failed = 0, 0
        try:
            for idx, inst in enumerate(missing, 1):
                symbol = inst['symbol']
                name = inst.get('name', symbol)
                _safe_print(f"   [{idx}/{len(missing)}] {symbol} - {name}")

                url_code = scraper.discover_url_code(symbol, name)
                if url_code:
                    inst['url_code'] = url_code
                    found += 1
                    _safe_print(f"      ✓ {url_code}")
                else:
                    failed += 1
                    _safe_print(f"      ✗ not found")

                if scraper.looks_rate_limited():
                    _safe_print("   ⚠ Rate limited — clearing session...")
                    scraper.hard_clear_session()
                    time.sleep(random.uniform(10, 20))

                time.sleep(random.uniform(2, 5))
        except KeyboardInterrupt:
            _safe_print("\n   Interrupted.")
        finally:
            scraper.close()
            _save_ms_instruments(ms_instruments)

        _safe_print(f"\n🏁 Done. Found {found}, failed {failed}.")
        _safe_print(f"   Config saved to {CONFIG_PATH.name}")
        total_with_code = sum(1 for i in ms_instruments if i.get('url_code'))
        _safe_print(f"   Total with url_code: {total_with_code}/{len(ms_instruments)}")
        return

    to_process = _resolve_targets(args, ms_instruments)
    if not to_process:
        return

    n_workers = min(args.workers, len(to_process))

    # ── Parallel mode: split work across N Chrome sessions ──────────────
    if n_workers > 1:
        from concurrent.futures import ProcessPoolExecutor, as_completed
        import math

        chunk_size = math.ceil(len(to_process) / n_workers)
        chunks = [to_process[i:i + chunk_size] for i in range(0, len(to_process), chunk_size)]

        logger.info(f"\n🚀 Parallel mode: {len(chunks)} workers x ~{chunk_size} stocks each")
        logger.info(f"   Total: {len(to_process)} stocks")

        batch_args = [
            (wid, chunk, args.headful, args.debug, args.delay_min, args.delay_max,
             args.restart_every, args.resume, args.max_age_hours, args.full)
            for wid, chunk in enumerate(chunks)
        ]

        total_processed = 0
        all_failed = []

        with ProcessPoolExecutor(max_workers=len(chunks)) as pool:
            futures = {pool.submit(_scrape_batch, ba): ba[0] for ba in batch_args}
            try:
                for future in as_completed(futures):
                    wid = futures[future]
                    try:
                        _, processed, failed = future.result()
                        total_processed += processed
                        all_failed.extend(failed)
                        logger.info(f"[W{wid}] finished: {processed} scraped, {len(failed)} failed")
                    except Exception as exc:
                        logger.error(f"[W{wid}] crashed: {exc}")
            except KeyboardInterrupt:
                logger.info("Interrupted — shutting down workers...")
                pool.shutdown(wait=False, cancel_futures=True)

        logger.info(f"\n🏁 Done. Processed {total_processed}/{len(to_process)} instruments.")
        if all_failed:
            logger.warning(f"⚠ {len(all_failed)} failed: {', '.join(all_failed)}")
            logger.warning("   Re-run with --resume to retry only the missing/failed tickers.")
        return

    # ── Sequential mode (single worker) ─────────────────────────────────
    scraper: Optional[SeleniumScraper] = SeleniumScraper(headless=not args.headful, debug=args.debug)
    processed = 0
    rate_limit_hits = 0
    failed_symbols: List[str] = []
    state = _load_scrape_state()

    def restart_browser():
        nonlocal scraper
        if scraper is not None:
            scraper.close()
        logger.info("♻ Restarting Chrome with a fresh profile / user-agent...")
        scraper = SeleniumScraper(headless=not args.headful, debug=args.debug)

    try:
        for idx, inst in enumerate(to_process, 1):
            symbol = inst['symbol']

            if args.resume and _was_scraped_recently(symbol, args.max_age_hours):
                logger.info(f"⏭  [{idx}/{len(to_process)}] {symbol}: skipped (recent file < {args.max_age_hours}h)")
                continue

            # Decide: daily or full scrape
            do_full = args.full or _needs_full_scrape(symbol, state)
            mode_label = "FULL" if do_full else "DAILY"

            logger.info(f"\n▶ [{idx}/{len(to_process)}] {symbol} — {inst.get('name', '')} ({mode_label})")

            url_code = inst.get('url_code')
            if not url_code:
                url_code = scraper.discover_url_code(symbol, inst.get('name', symbol))
                if not url_code:
                    logger.warning(f"   skipped: no MS slug found for {symbol}")
                    failed_symbols.append(symbol)
                    continue
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

            stock_data: Optional[StockData] = None
            attempts = 0
            while True:
                attempts += 1
                try:
                    if do_full:
                        stock_data = scraper.scrape(symbol, url_code)
                    else:
                        stock_data = scraper.scrape_daily(symbol, url_code)
                except WebDriverException as exc:
                    logger.error(f"   browser error: {exc}; restarting...")
                    restart_browser()
                    if attempts >= 2:
                        failed_symbols.append(symbol)
                        stock_data = None
                        break
                    continue

                rate_limited = (
                    scraper.looks_rate_limited()
                    or any('Rate-limited' in w for w in stock_data.scrape_warnings)
                )
                if not rate_limited:
                    break

                rate_limit_hits += 1
                logger.warning(
                    f"⚠ Rate-limit hit #{rate_limit_hits} on {symbol} — "
                    f"clearing cookies and retrying (attempt {attempts})"
                )
                try:
                    scraper.hard_clear_session()
                except Exception as exc:
                    logger.warning(f"   hard_clear_session failed: {exc}")
                restart_browser()
                if attempts >= 2:
                    logger.error(
                        f"   {symbol}: still rate-limited after cookie clear, "
                        f"skipping (will be listed in failed_symbols)"
                    )
                    failed_symbols.append(symbol)
                    stock_data = None
                    break
                time.sleep(random.uniform(15, 30))

            if stock_data is None:
                continue

            output_file = DATA_DIR / f"{symbol}_marketscreener_v3.json"
            with open(output_file, 'w', encoding='utf-8') as f:
                json.dump(asdict(stock_data), f, indent=2, default=str, ensure_ascii=False)
            _print_summary(stock_data, output_file)
            processed += 1

            if do_full:
                _mark_full_scrape(symbol, state)
                _save_scrape_state(state)

            if args.restart_every and processed > 0 and processed % args.restart_every == 0:
                restart_browser()

            if idx < len(to_process):
                delay = random.uniform(args.delay_min, args.delay_max)
                logger.info(f"   ⏱  sleeping {delay:.1f}s before next instrument...")
                time.sleep(delay)

        logger.info(f"\n🏁 Done. Processed {processed}/{len(to_process)} instruments.")
        if failed_symbols:
            logger.warning(
                f"⚠ {len(failed_symbols)} symbol(s) failed: {', '.join(failed_symbols)}"
            )
            logger.warning(
                "   Re-run with --resume to retry only the missing/failed tickers."
            )

    finally:
        _save_scrape_state(state)
        if scraper is not None:
            scraper.close()


if __name__ == "__main__":
    main()
