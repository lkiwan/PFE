"""
News Scraper for MarketScreener
================================
Fetches news article headlines from MarketScreener for Casablanca stocks.
Uses requests + BeautifulSoup (no Selenium needed — news pages are static HTML).

Usage:
    from scraper import NewsScraper, STOCKS, AsyncHTTPClient, StockData

Classes are kept compatible with run_scraper.py's interface.
"""

import os
import re
import time
import random
import logging
from dataclasses import dataclass, field
from typing import List, Dict, Any, Optional
from pathlib import Path

# Fix: PostgreSQL overrides SSL_CERT_FILE / REQUESTS_CA_BUNDLE with its own
# path, which breaks Python requests for general HTTPS. Remove ALL overrides
# so requests uses its built-in certifi bundle instead.
for _env_var in ("SSL_CERT_FILE", "REQUESTS_CA_BUNDLE", "CURL_CA_BUNDLE"):
    if _env_var in os.environ:
        del os.environ[_env_var]

try:
    import certifi
    _CA_BUNDLE = certifi.where()
except ImportError:
    _CA_BUNDLE = True  # let requests figure it out

try:
    import requests
    from bs4 import BeautifulSoup
except ImportError:
    print("Missing dependencies. Install with:")
    print("  pip install requests beautifulsoup4 lxml certifi")
    raise

logger = logging.getLogger(__name__)

_ROOT = Path(__file__).resolve().parent.parent
MS_CONFIG = _ROOT / "data" / "scrapers" / "instruments_marketscreener.json"

BASE_URL = "https://www.marketscreener.com/quote/stock"

USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/123.0.0.0 Safari/537.36",
]


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------

@dataclass
class Article:
    title: Optional[str] = None
    date: Optional[str] = None
    source: Optional[str] = None
    url: Optional[str] = None
    full_content: Optional[str] = None


@dataclass
class NewsData:
    articles: List[Article] = field(default_factory=list)
    total_count: int = 0


@dataclass
class StockData:
    news: NewsData = field(default_factory=NewsData)


# ---------------------------------------------------------------------------
# Build STOCKS dict from instruments_marketscreener.json
# ---------------------------------------------------------------------------

def _load_stocks() -> Dict[str, Dict[str, str]]:
    """Load all stocks that have a MarketScreener url_code."""
    import json
    stocks: Dict[str, Dict[str, str]] = {}
    if not MS_CONFIG.exists():
        return stocks
    with open(MS_CONFIG, "r", encoding="utf-8") as f:
        instruments = json.load(f).get("instruments", [])
    for inst in instruments:
        sym = inst.get("symbol", "").upper()
        url_code = inst.get("url_code")
        if sym and url_code:
            stocks[sym] = {
                "url_code": url_code,
                "full_name": inst.get("name", sym),
                "ticker": sym,
            }
    return stocks


STOCKS = _load_stocks()


# ---------------------------------------------------------------------------
# HTTP client (sync, keeps the same interface name for run_scraper.py)
# ---------------------------------------------------------------------------

class AsyncHTTPClient:
    """Simple sync HTTP client disguised as 'Async' to keep run_scraper.py compatible."""

    def __init__(self):
        self.session = requests.Session()
        self.session.headers.update({
            "User-Agent": random.choice(USER_AGENTS),
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.5",
        })

    def get(self, url: str, timeout: int = 30) -> Optional[str]:
        try:
            resp = self.session.get(url, timeout=timeout, verify=_CA_BUNDLE)
            if resp.status_code == 200:
                return resp.text
            logger.warning(f"HTTP {resp.status_code} for {url}")
        except Exception as e:
            logger.warning(f"Request failed for {url}: {e}")
        return None

    async def close(self):
        """No-op for compatibility."""
        pass


# ---------------------------------------------------------------------------
# News scraper
# ---------------------------------------------------------------------------

class NewsScraper:
    """Scrape news headlines from MarketScreener stock pages."""

    def __init__(self, http_client: AsyncHTTPClient):
        self.client = http_client

    async def scrape(
        self,
        stock_config: Dict[str, str],
        stock_data: StockData,
        fetch_full_articles: bool = False,
    ) -> None:
        """
        Scrape news articles for a stock.

        MarketScreener news URL pattern:
            /quote/stock/<URL_CODE>/news/
        """
        url_code = stock_config["url_code"]
        news_url = f"{BASE_URL}/{url_code}/news/"

        logger.info(f"Fetching news from {news_url}")
        html = self.client.get(news_url)
        if not html:
            logger.warning(f"No HTML returned for {stock_config.get('ticker', '?')}")
            return

        soup = BeautifulSoup(html, "lxml")
        articles: List[Article] = []

        # MarketScreener news pages list articles as table rows or <a> links
        # inside containers with news-related classes.
        # Strategy: find all links whose href contains /news/ and a numeric ID.
        news_link_re = re.compile(
            rf'/quote/stock/{re.escape(url_code)}/news/[^"]*\d{{4,}}',
            re.IGNORECASE,
        )

        seen_urls = set()
        for a_tag in soup.find_all("a", href=True):
            href = a_tag["href"]
            if not news_link_re.search(href):
                continue

            full_url = href if href.startswith("http") else f"https://www.marketscreener.com{href}"
            if full_url in seen_urls:
                continue
            seen_urls.add(full_url)

            title = a_tag.get_text(strip=True)
            if not title or len(title) < 10:
                continue

            # Try to find date near this link
            date_str = self._find_date_near(a_tag)

            # Try to find source near this link
            source = self._find_source_near(a_tag)

            article = Article(
                title=title,
                date=date_str,
                source=source,
                url=full_url,
            )

            # Optionally fetch full article text
            if fetch_full_articles:
                article.full_content = self._fetch_article_content(full_url)
                time.sleep(random.uniform(0.5, 1.5))

            articles.append(article)

        stock_data.news.articles = articles
        stock_data.news.total_count = len(articles)
        logger.info(f"Found {len(articles)} articles for {stock_config.get('ticker', '?')}")

    def _find_date_near(self, tag) -> Optional[str]:
        """Try to extract a date from surrounding elements."""
        # Check parent row / container for date-like text
        parent = tag.find_parent("tr") or tag.find_parent("div")
        if parent:
            text = parent.get_text(" ", strip=True)
            # Match patterns like "04/10/2026", "2026-04-10", "Apr 10, 2026"
            m = re.search(r'(\d{2}/\d{2}/\d{4})', text)
            if m:
                try:
                    dt = time.strptime(m.group(1), "%m/%d/%Y")
                    return time.strftime("%Y-%m-%d", dt)
                except ValueError:
                    try:
                        dt = time.strptime(m.group(1), "%d/%m/%Y")
                        return time.strftime("%Y-%m-%d", dt)
                    except ValueError:
                        return m.group(1)

            m = re.search(r'(\d{4}-\d{2}-\d{2})', text)
            if m:
                return m.group(1)

            # "Apr 10, 2026" or "10 Apr 2026"
            m = re.search(
                r'(\w{3,9}\s+\d{1,2},?\s+\d{4}|\d{1,2}\s+\w{3,9}\s+\d{4})',
                text
            )
            if m:
                return m.group(1)

        return None

    def _find_source_near(self, tag) -> Optional[str]:
        """Try to extract the news source from surrounding elements."""
        parent = tag.find_parent("tr") or tag.find_parent("div")
        if parent:
            # MarketScreener often shows source in a small/span/italic element
            for el in parent.find_all(["span", "small", "em", "i"]):
                text = el.get_text(strip=True)
                if text and len(text) < 40 and text != tag.get_text(strip=True):
                    # Skip if it looks like a date
                    if re.match(r'^[\d/\-]+$', text):
                        continue
                    return text
        return "MarketScreener"

    def _fetch_article_content(self, url: str) -> Optional[str]:
        """Fetch full article text from an article page."""
        html = self.client.get(url)
        if not html:
            return None

        soup = BeautifulSoup(html, "lxml")

        # MarketScreener article content is typically in <div class="txt-...">
        # or <article> or a large <div> with paragraphs
        for selector in [
            {"class": re.compile(r"txt-|article-|news-content|story")},
            "article",
        ]:
            container = soup.find("div", selector) if isinstance(selector, dict) else soup.find(selector)
            if container:
                paragraphs = container.find_all("p")
                if paragraphs:
                    text = " ".join(p.get_text(strip=True) for p in paragraphs)
                    if len(text) > 50:
                        return text[:5000]

        return None
