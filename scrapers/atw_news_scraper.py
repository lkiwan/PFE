"""
ATW News Scraper — free, RSS-based
==================================
Collects Attijariwafa Bank news from:
  1. Google News RSS (search operators supported: exact-phrase, -site:)
  2. Moroccan financial RSS feeds (Le Matin, L'Economiste, FNH, ...)
  3. Medias24 economie landing page (HTML scrape — no RSS)
  4. MarketScreener dedicated ATW news page

Filters every article by checking title/summary for "attijariwafa" or "ATW".
Drops known noise rows (BeBee/Instagram/Focus PME/Egypt-only mentions).
Deduplicates by canonical URL and (date, normalized-title), including Google
News redirect variants.
Adds signal_score and is_atw_core columns.
Saves CSV to data/historical/ATW_news.csv.

Usage:
    python scrapers/atw_news_scraper.py
    python scrapers/atw_news_scraper.py --since 2026-01-01
    python scrapers/atw_news_scraper.py --out data/historical/ATW_news.csv
"""

from __future__ import annotations

import argparse
import csv
import json
import logging
import os
import re
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable, Optional
from urllib.parse import parse_qs, quote_plus, unquote, urlparse

import certifi

os.environ["REQUESTS_CA_BUNDLE"] = certifi.where()
os.environ["CURL_CA_BUNDLE"] = certifi.where()
os.environ["SSL_CERT_FILE"] = certifi.where()

import feedparser
import requests
from bs4 import BeautifulSoup

_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_OUT = _ROOT / "data" / "historical" / "ATW_news.csv"
STATE_FILE = _ROOT / "data" / "scrapers" / "atw_news_state.json"
TICKER = "ATW"

# Medias24 WP REST tag id for ATW articles (discovered via /wp-json/wp/v2/tags?search=attijariwafa).
# Tag id 8987, slug "attijariwafa-bank", 128+ posts. Much cleaner than scraping
# the topic HTML page — returns clean JSON with structured date/title/excerpt/link.
MEDIAS24_WP_TAG_ATW = 8987

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)
REQUEST_TIMEOUT = 20
POLITE_DELAY = 1.0

# Substrings matched against the hostname ONLY — these drop any subdomain or
# country TLD variant. Used for the bank's own domains, social media, job
# boards, aggregators — places where a "mention" in the URL path is a false
# positive, not a reason to drop.
BLOCKED_HOST_SUBSTRINGS = (
    # Bank's own domains — substring form catches .com, .net, .com.eg, and
    # any subdomain (corporate.*, press.*, ...).
    "attijariwafa",
    "attijari.com",
    "daralmoukawil.com",
    # Social media
    "facebook.com",
    "instagram.com",
    "twitter.com",
    "threads.net",
    "tiktok.com",
    "youtube.com",
    "youtu.be",
    "linkedin.com",
    "pinterest.",
    "reddit.com",
    "bebee.com",
    # Maps / location listings (not news)
    "waze.com",
    "openstreetmap",
    "foursquare",
    "yelp.",
    # Remittance / FX aggregators that mention ATW as a corridor partner
    "remitly.com",
    "wise.com",
    "wewire.com",
    "transferwise.com",
    "worldremit.com",
    "xoom.com",
    "moneygram.com",
    "westernunion.com",
    "paysend.com",
    # Job boards / HR news — career listings aren't market news
    "rekrute.com",
    "emploi.ma",
    "anapec.org",
    "bayt.com",
    "indeed.com",
    "glassdoor.com",
    "welcometothejungle.com",
    "jobzyn.com",
    "monster.com",
    "bghit-nekhdem",
    "drh.ma",
    # App stores — product listings, not news
    "apps.apple.com",
    "play.google.com",
    # ATW retail product sites (self-operated, not news)
    "lbankalik.ma",
    # World Bank remittance comparator — transfer-fee listings, not news
    "remittanceprices.worldbank.org",
    # SWIFT-code / company directories — evergreen lookup pages
    "xe.com",
    "qonto.com",
    "globaldata.com",
    "euroquity.com",
    "viguier.com",
    # Reference / regulatory filings — not price-moving news
    "wikipedia.org",
    "fsma.be",
    # Partner / vendor press pages — self-published, no editorial filter
    "greenclimate.fund",
    "eib.org",
    "hps-worldwide.com",
    "royalairmaroc.com",
    "airarabia.com",
    # PR-wire aggregators that re-host press releases without editorial value
    "prnewswire.com",
    "businesswire.com",
)

# Substrings matched against "<host><first-path-segment>/" — for rules that
# only make sense when a specific path is hit (e.g. x.com/ user pages, but
# not a hypothetical x.com news section; Google Maps but not Google News).
BLOCKED_HOSTPATH_SUBSTRINGS = (
    "x.com/",
    "google.com/maps",
)

# Whitelist — exact host suffixes that override BLOCKED_HOST_SUBSTRINGS. Lets
# us keep the blanket "attijariwafa" block for corporate/retail pages while
# still accepting the official IR site and group-adjacent insights hubs.
WHITELISTED_HOST_SUFFIXES = (
    "ir.attijariwafabank.com",
    "attijaricib.com",
)

# Backward-compat aliases.
BLOCKED_HOSTS: set[str] = set()
BLOCKED_SOURCE_SUBSTRINGS = BLOCKED_HOST_SUBSTRINGS + BLOCKED_HOSTPATH_SUBSTRINGS

# Match tokens we consider a positive mention of the bank.
ATW_TOKEN_RE = re.compile(
    r"\b(attijariwafa|attijari\s*wafa|\bATW\b)",
    flags=re.IGNORECASE,
)

NOISE_SOURCE_SUBSTRINGS = (
    "bebee",
    "instagram",
    "facebook.com",
)

FOCUS_PME_RE = re.compile(r"\bfocus\s*pme\b", flags=re.IGNORECASE)
EGYPT_KEYWORD_RE = re.compile(
    r"\b(egypt|egypte|égypte|cairo|le\s+caire|alexandrie|alexandria|egx|attijariwafa\s+bank\s+egypt)\b",
    flags=re.IGNORECASE,
)
MOROCCO_CONTEXT_RE = re.compile(
    r"\b(maroc|morocco|casablanca|bourse de casablanca|masi|ammc|bank al[-\s]?maghrib|bam)\b",
    flags=re.IGNORECASE,
)
ATW_CORE_SIGNAL_RE = re.compile(
    r"\b("
    r"résultats?|resultats?|earnings|rnpg|pnb|bénéfices?|benefices?|profits?|net income|"
    r"chiffre d'affaires|revenus?|croissance|guidance|outlook|"
    r"dividendes?|dividend|"
    r"strat[ée]gie|plan strat[ée]gique|transformation|acquisition|fusion|cession|"
    r"rating|notation|recommandation|cours cible|objectif de cours|upgrade|downgrade|surpond[ée]rer|"
    r"valorisation|capitalisation|bourse"
    r")\b",
    flags=re.IGNORECASE,
)
ATW_PASSING_RE = re.compile(
    r"\b(forum|salon|webinaire|événement|evenement|event|sponsor|sponsoring|campagne)\b",
    flags=re.IGNORECASE,
)

logger = logging.getLogger("atw_news")


# ---------------------------------------------------------------------------
# Source registry
# ---------------------------------------------------------------------------

GOOGLE_NEWS_QUERIES = [
    # (query_string, hl, gl, ceid)
    (
        '"Attijariwafa bank" -site:attijariwafa.com -site:attijariwafabank.com',
        "fr", "MA", "MA:fr",
    ),
    (
        '"Attijariwafa" -site:attijariwafa.com -site:attijariwafabank.com',
        "fr", "MA", "MA:fr",
    ),
    (
        '"Attijariwafa bank" -site:attijariwafa.com -site:attijariwafabank.com',
        "en", "US", "US:en",
    ),
]

# Generic feeds — we fetch everything and filter for ATW mentions.
# Direct topic-page scrapers (scrape_medias24_topic, scrape_boursenews_stock,
# scrape_ir_attijariwafa, scrape_attijari_cib_insights, scrape_leconomiste_search)
# are the primary source. Generic sitewide RSS feeds previously listed here
# (Le Matin, L'Economiste root) returned zero ATW items per run and were dropped.
GENERIC_FEEDS: list[tuple[str, str]] = []


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _fetch(url: str, timeout: int = REQUEST_TIMEOUT, retries: int = 1) -> Optional[str]:
    for attempt in range(retries + 1):
        try:
            resp = requests.get(
                url,
                headers={"User-Agent": USER_AGENT, "Accept": "*/*"},
                timeout=timeout,
            )
            if resp.status_code == 200 and resp.text:
                return resp.text
            logger.warning("HTTP %s for %s", resp.status_code, url)
            return None
        except requests.RequestException as exc:
            if attempt < retries:
                logger.info("Retry %d for %s (%s)", attempt + 1, url, exc)
                continue
            logger.warning("Fetch failed for %s: %s", url, exc)
    return None


def _parse_date(value) -> str:
    """Normalize any date-ish input to strict ISO-8601.

    Returns bare `YYYY-MM-DD` when only a date is known, `YYYY-MM-DDTHH:MM:SS+00:00`
    when a time is available, or empty string on failure. Empty strings keep
    the CSV clean (no "None" literals, no mixed-type sort keys).
    """
    if not value:
        return ""
    if isinstance(value, time.struct_time):
        return datetime(*value[:6], tzinfo=timezone.utc).isoformat()
    if isinstance(value, str):
        s = value.strip()
        if not s:
            return ""
        # Date-only — keep as YYYY-MM-DD
        try:
            return datetime.strptime(s, "%Y-%m-%d").strftime("%Y-%m-%d")
        except ValueError:
            pass
        # Full ISO with timezone
        try:
            dt = datetime.fromisoformat(s)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return dt.astimezone(timezone.utc).isoformat()
        except ValueError:
            pass
        # Common alternate formats
        for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S"):
            try:
                dt = datetime.strptime(s, fmt).replace(tzinfo=timezone.utc)
                return dt.isoformat()
            except ValueError:
                continue
        # RFC-2822 (feedparser fallback when published_parsed missing)
        try:
            from email.utils import parsedate_to_datetime
            dt = parsedate_to_datetime(s)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return dt.astimezone(timezone.utc).isoformat()
        except (TypeError, ValueError):
            pass
    return ""


def _mentions_atw(*fields: str) -> bool:
    for f in fields:
        if f and ATW_TOKEN_RE.search(f):
            return True
    return False


def _host_blocked(url: str) -> bool:
    """Drop URLs whose *host* matches BLOCKED_HOST_SUBSTRINGS, or whose
    <host>+<first-path-segment> matches BLOCKED_HOSTPATH_SUBSTRINGS. Host-only
    matching avoids false positives where the article slug mentions
    "attijariwafa" on a legitimate news site.
    """
    try:
        parsed = urlparse(url)
        host = (parsed.hostname or "").lower()
        if not host:
            return False
        if any(host == w or host.endswith("." + w) or host == w
               for w in WHITELISTED_HOST_SUFFIXES):
            return False
        if host in BLOCKED_HOSTS:
            return True
        if any(sub in host for sub in BLOCKED_HOST_SUBSTRINGS):
            return True
        path = (parsed.path or "").lower()
        if "/" in path[1:]:
            first_seg = path[:path.index("/", 1) + 1]
        else:
            first_seg = path + "/"
        hostpath = f"{host}{first_seg}"
        return any(sub in hostpath for sub in BLOCKED_HOSTPATH_SUBSTRINGS)
    except Exception:
        return False


def _resolve_final_url(url: str) -> str:
    """Resolve a Google-News `rss/articles/CBMi...` URL to the real publisher
    URL via googlenewsdecoder. For non-Google-News URLs, follow standard HTTP
    redirects. Returns the original URL on failure.
    """
    if "news.google.com/rss/articles/" in url:
        try:
            from googlenewsdecoder import gnewsdecoder
            result = gnewsdecoder(url, interval=1)
            if isinstance(result, dict) and result.get("status") and result.get("decoded_url"):
                return result["decoded_url"]
        except Exception as exc:
            logger.debug("gnewsdecoder failed for %s: %s", url[:80], exc)
        return url

    try:
        resp = requests.get(
            url,
            headers={"User-Agent": USER_AGENT, "Accept": "*/*"},
            timeout=REQUEST_TIMEOUT,
            allow_redirects=True,
        )
        return resp.url or url
    except requests.RequestException:
        return url


_FRENCH_MONTHS = {
    "janvier": 1, "février": 2, "fevrier": 2, "mars": 3, "avril": 4,
    "mai": 5, "juin": 6, "juillet": 7, "août": 8, "aout": 8,
    "septembre": 9, "octobre": 10, "novembre": 11, "décembre": 12, "decembre": 12,
}


def _parse_french_date(s: str) -> str:
    """Parse French long-form dates like 'Vendredi 10 Avril 2026' → ISO YYYY-MM-DD."""
    if not s:
        return ""
    m = re.search(
        r"(\d{1,2})\s+(janvier|février|fevrier|mars|avril|mai|juin|juillet|août|aout|septembre|octobre|novembre|décembre|decembre)\s+(\d{4})",
        s,
        re.IGNORECASE,
    )
    if not m:
        return ""
    day, month_name, year = int(m.group(1)), m.group(2).lower(), int(m.group(3))
    month = _FRENCH_MONTHS.get(month_name)
    if not month:
        return ""
    try:
        return datetime(year, month, day).strftime("%Y-%m-%d")
    except ValueError:
        return ""


def _extract_article_date(html: str) -> str:
    """Extract publication date from an article page's HTML.

    Checks (in order): <meta article:published_time>, <meta name=date*>,
    <time datetime>, JSON-LD datePublished. Handles both ISO-8601 and
    French long-form dates. Returns ISO string or "".
    """
    if not html:
        return ""
    soup = BeautifulSoup(html, "html.parser")

    for attrs in (
        {"property": "article:published_time"},
        {"property": "og:article:published_time"},
        {"name": "article:published_time"},
        {"itemprop": "datePublished"},
        {"name": "date"},
        {"name": "pubdate"},
        {"name": "publish-date"},
    ):
        tag = soup.find("meta", attrs=attrs)
        if tag and tag.get("content"):
            parsed = _parse_date(tag["content"]) or _parse_french_date(tag["content"])
            if parsed:
                return parsed

    for t in soup.find_all("time"):
        candidate = t.get("datetime") or t.get_text(strip=True)
        parsed = _parse_date(candidate) or _parse_french_date(candidate)
        if parsed:
            return parsed

    for s in soup.find_all("script", type="application/ld+json"):
        txt = s.string or s.get_text() or ""
        for m in re.finditer(r'"datePublished"\s*:\s*"([^"]+)"', txt):
            parsed = _parse_date(m.group(1)) or _parse_french_date(m.group(1))
            if parsed:
                return parsed

    return ""


def _fetch_article_body(url: str) -> tuple[str, str]:
    """Fetch a publisher page and extract (body_text, iso_date).

    Uses our own `requests` session for download (so the certifi CA fix
    applies), then hands the raw HTML to trafilatura for body extraction
    and a local parser for date extraction. Returns ("","") on failure.
    """
    try:
        resp = requests.get(
            url,
            headers={
                "User-Agent": USER_AGENT,
                "Accept": "text/html,application/xhtml+xml",
                "Accept-Language": "fr-FR,fr;q=0.9,en;q=0.8",
            },
            timeout=REQUEST_TIMEOUT,
            allow_redirects=True,
        )
        if resp.status_code != 200 or not resp.text:
            return "", ""
        import trafilatura
        text = trafilatura.extract(
            resp.text,
            url=resp.url,
            include_comments=False,
            include_tables=False,
            favor_recall=False,
        )
        date_str = _extract_article_date(resp.text)
        return (text or "").strip(), date_str
    except Exception as exc:
        logger.debug("Body extract failed for %s: %s", url, exc)
        return "", ""


def _fetch_article_date_only(url: str) -> str:
    """Lightweight fetch for date back-fill when body is already cached."""
    try:
        resp = requests.get(
            url,
            headers={
                "User-Agent": USER_AGENT,
                "Accept": "text/html,application/xhtml+xml",
                "Accept-Language": "fr-FR,fr;q=0.9,en;q=0.8",
            },
            timeout=REQUEST_TIMEOUT,
            allow_redirects=True,
        )
        if resp.status_code != 200 or not resp.text:
            return ""
        return _extract_article_date(resp.text)
    except Exception as exc:
        logger.debug("Date extract failed for %s: %s", url, exc)
        return ""


def _normalize_title(title: str) -> str:
    t = re.sub(r"\s+", " ", title or "").strip().lower()
    # Strip trailing publisher suffixes commonly added by RSS aggregators.
    t = re.sub(
        r"\s(?:-|–|—|\|)\s(?:medias24|l['’]?economiste|boursenews|infom[ée]diaire|facebook\.com|instagram\.com|bebee\.com)$",
        "",
        t,
        flags=re.IGNORECASE,
    )
    t = re.sub(r"[^\w\sàâäéèêëïîôöùûüç%-]", " ", t, flags=re.IGNORECASE)
    return re.sub(r"\s+", " ", t).strip()


def _canonical_url(url: str) -> str:
    raw = (url or "").strip()
    if not raw:
        return ""
    try:
        parsed = urlparse(raw)
    except ValueError:
        return raw.split("?")[0].rstrip("/").lower()

    host = (parsed.hostname or "").lower()
    if host.startswith("www."):
        host = host[4:]

    path = re.sub(r"/+", "/", parsed.path or "")
    if path != "/":
        path = path.rstrip("/")

    query_params = parse_qs(parsed.query, keep_blank_values=False)

    # If this URL is itself a redirect wrapper, canonicalize the target URL.
    for key in ("url", "u", "target", "dest", "destination"):
        values = query_params.get(key) or query_params.get(key.upper())
        if values:
            nested = unquote(values[0]).strip()
            if nested.startswith(("http://", "https://")):
                return _canonical_url(nested)

    kept_items: list[tuple[str, str]] = []
    for key, values in query_params.items():
        lk = key.lower()
        if lk.startswith("utm_") or lk in {
            "oc", "ved", "usg", "fbclid", "gclid", "igshid", "mkt_tok", "mc_cid", "mc_eid",
        }:
            continue
        for value in values:
            kept_items.append((lk, value))
    kept_items.sort()
    query = "&".join(f"{k}={v}" if v else k for k, v in kept_items)

    canonical = f"{host}{path}"
    if query:
        canonical = f"{canonical}?{query}"
    return canonical.lower()


def _is_egypt_specific(*fields: str) -> bool:
    text = " ".join(f for f in fields if f)
    if not text:
        return False
    if not EGYPT_KEYWORD_RE.search(text):
        return False
    return not MOROCCO_CONTEXT_RE.search(text)


def _is_noise_article(article: dict) -> bool:
    source = (article.get("source") or "").lower()
    url = (article.get("url") or "").lower()
    title = article.get("title") or ""
    snippet = article.get("snippet") or ""
    text = f"{title} {snippet} {source} {url}"

    if any(sub in source for sub in NOISE_SOURCE_SUBSTRINGS):
        return True
    if "bebee" in url or "instagram.com" in url:
        return True
    if FOCUS_PME_RE.search(text):
        return True
    if _is_egypt_specific(title, snippet, source, url):
        return True
    return False


def _compute_signal_fields(article: dict) -> tuple[int, int]:
    title = article.get("title") or ""
    snippet = article.get("snippet") or ""
    full_content = article.get("full_content") or ""
    query_source = (article.get("query_source") or "").lower()

    text_all = f"{title} {snippet} {full_content}"
    atw_title = _mentions_atw(title)
    atw_any = _mentions_atw(title, snippet, full_content)

    core_title_hits = len(ATW_CORE_SIGNAL_RE.findall(title))
    core_all_hits = len(ATW_CORE_SIGNAL_RE.findall(text_all))
    passing_hits = len(ATW_PASSING_RE.findall(text_all))

    score = 10
    if atw_any:
        score += 20
    if atw_title:
        score += 15
    score += min(core_title_hits, 3) * 18
    score += min(max(core_all_hits - core_title_hits, 0), 4) * 8
    if query_source.startswith("direct:"):
        score += 6
    score -= min(passing_hits, 3) * 8
    if _is_egypt_specific(title, snippet, full_content):
        score -= 40

    score = max(0, min(100, score))
    is_core = int(atw_any and (core_title_hits > 0 or core_all_hits >= 2))
    return score, is_core


# ---------------------------------------------------------------------------
# Fetchers
# ---------------------------------------------------------------------------

def fetch_google_news_rss(query: str, hl: str, gl: str, ceid: str) -> list[dict]:
    url = (
        "https://news.google.com/rss/search"
        f"?q={quote_plus(query)}&hl={hl}&gl={gl}&ceid={ceid}"
    )
    logger.info("Google News RSS: %s [%s]", query, ceid)
    content = _fetch(url)
    if not content:
        return []
    parsed = feedparser.parse(content)
    items = []
    for entry in parsed.entries:
        title = entry.get("title") or ""
        link = entry.get("link") or ""
        if _host_blocked(link):
            continue
        if not _mentions_atw(title, entry.get("summary", "")):
            continue
        items.append({
            "date": _parse_date(entry.get("published_parsed") or entry.get("published")),
            "title": title.strip(),
            "source": entry.get("source", {}).get("title")
                      if isinstance(entry.get("source"), dict)
                      else (urlparse(link).hostname or "Google News"),
            "url": link,
            "snippet": BeautifulSoup(entry.get("summary", ""), "html.parser")
                       .get_text(" ", strip=True)[:400],
            "full_content": "",
            "query_source": f"google_news:{ceid}",
        })
    logger.info("  -> %d ATW-matching items", len(items))
    return items


def fetch_rss_feed(name: str, url: str) -> list[dict]:
    logger.info("Feed: %s (%s)", name, url)
    content = _fetch(url)
    if not content:
        return []
    parsed = feedparser.parse(content)
    items = []
    for entry in parsed.entries:
        title = entry.get("title") or ""
        summary = BeautifulSoup(entry.get("summary", ""), "html.parser").get_text(
            " ", strip=True
        )
        if not _mentions_atw(title, summary):
            continue
        link = entry.get("link") or ""
        if _host_blocked(link):
            continue
        items.append({
            "date": _parse_date(entry.get("published_parsed") or entry.get("published")),
            "title": title.strip(),
            "source": name,
            "url": link,
            "snippet": summary[:400],
            "full_content": "",
            "query_source": f"rss:{name}",
        })
    logger.info("  -> %d ATW-matching items", len(items))
    return items


def scrape_medias24() -> list[dict]:
    """Medias24 has no public RSS — scrape the économie landing page."""
    url = "https://medias24.com/categorie/economie/"
    logger.info("HTML scrape: Medias24 économie")
    html = _fetch(url)
    if not html:
        return []
    soup = BeautifulSoup(html, "html.parser")
    items = []
    for art in soup.select("article"):
        a = art.find("a", href=True)
        if not a:
            continue
        title = a.get_text(" ", strip=True) or (a.get("title") or "")
        href = a["href"]
        if not href.startswith("http"):
            href = "https://medias24.com" + href
        summary_tag = art.find(["p", "div"], class_=re.compile("excerpt|summary|desc", re.I))
        snippet = summary_tag.get_text(" ", strip=True) if summary_tag else ""
        if not _mentions_atw(title, snippet):
            continue
        if _host_blocked(href):
            continue
        time_tag = art.find("time")
        items.append({
            "date": _parse_date(time_tag.get("datetime") if time_tag else None),
            "title": title,
            "source": "Medias24",
            "url": href,
            "snippet": snippet[:400],
            "full_content": "",
            "query_source": "html:medias24",
        })
    logger.info("  -> %d ATW-matching items", len(items))
    return items


# ---------------------------------------------------------------------------
# Direct topic/stock-page scrapers (high-signal, ATW-specific hubs)
# ---------------------------------------------------------------------------

def _abs_url(base: str, href: str) -> str:
    if href.startswith("http"):
        return href
    if href.startswith("//"):
        return "https:" + href
    return base.rstrip("/") + "/" + href.lstrip("/")


def scrape_ir_attijariwafa() -> list[dict]:
    """Official Attijariwafa IR news-release hub — zero false positives."""
    url = "https://ir.attijariwafabank.com/news-releases"
    logger.info("Direct scrape: IR Attijariwafa (%s)", url)
    html = _fetch(url)
    if not html:
        return []
    soup = BeautifulSoup(html, "html.parser")
    items = []
    for a in soup.find_all("a", href=True):
        href = a["href"]
        if "/news-releases/news-release-details/" not in href:
            continue
        title = a.get_text(" ", strip=True)
        if not title or len(title) < 15:
            continue
        link = _abs_url("https://ir.attijariwafabank.com", href)
        items.append({
            "date": "",
            "title": title,
            "source": "Attijariwafa IR",
            "url": link,
            "snippet": "",
            "full_content": "",
            "query_source": "direct:ir",
        })
    logger.info("  -> %d items", len(items))
    return items


def scrape_medias24_topic(known_url_keys: Optional[set[str]] = None) -> list[dict]:
    """Medias24 ATW topic hub — the main column is ATW, but the page also
    renders sitewide sidebar/recommended links. We filter on title mention of
    ATW to drop the non-topic stragglers (URL slug contains "attijariwafa"
    for real topic articles, but we rely on title too for robustness).
    """
    url = "https://medias24.com/sujet/attijariwafa-bank/"
    logger.info("Direct scrape: Medias24 topic (%s)", url)
    html = _fetch(url)
    if not html:
        return []
    soup = BeautifulSoup(html, "html.parser")
    items = []
    seen: set[str] = set()
    # Article URLs follow medias24.com/YYYY/MM/DD/<slug>
    for a in soup.find_all("a", href=True):
        href = a["href"]
        if "medias24.com/" not in href:
            continue
        if not re.search(r"medias24\.com/\d{4}/\d{2}/\d{2}/", href):
            continue
        title = a.get_text(" ", strip=True)
        if not title or len(title) < 15:
            continue
        if href in seen:
            continue
        seen.add(href)
        # Drop sitewide sidebar links that don't actually mention ATW.
        slug_has_atw = "attijariwafa" in href.lower() or "/atw-" in href.lower()
        if not (slug_has_atw or _mentions_atw(title, "")):
            continue
        if known_url_keys is not None and not items:
            if _url_key(href) in known_url_keys:
                logger.info("  -> source unchanged (top item known), skipped")
                return []
        m = re.search(r"/(\d{4})/(\d{2})/(\d{2})/", href)
        date_iso = f"{m.group(1)}-{m.group(2)}-{m.group(3)}" if m else ""
        items.append({
            "date": date_iso,
            "title": title,
            "source": "Medias24",
            "url": href,
            "snippet": "",
            "full_content": "",
            "query_source": "direct:medias24_topic",
        })
    logger.info("  -> %d items", len(items))
    return items


def scrape_boursenews_stock(known_url_keys: Optional[set[str]] = None) -> list[dict]:
    """Boursenews dedicated ATW action page — earnings, broker notes, ratings."""
    url = "https://boursenews.ma/action/attijariwafa-bank"
    logger.info("Direct scrape: Boursenews stock (%s)", url)
    html = _fetch(url)
    if not html:
        return []
    soup = BeautifulSoup(html, "html.parser")
    items = []
    seen: set[str] = set()
    for a in soup.find_all("a", href=True):
        href = a["href"]
        if "/article/marches/" not in href:
            continue
        title = a.get_text(" ", strip=True)
        if not title or len(title) < 15:
            continue
        # Filter to titles that actually mention ATW — the page also links
        # generic market-data articles (Feuille de marché, Sentiment, ...).
        if not _mentions_atw(title, ""):
            continue
        link = _abs_url("https://boursenews.ma", href)
        if link in seen:
            continue
        seen.add(link)
        if known_url_keys is not None and not items:
            if _url_key(link) in known_url_keys:
                logger.info("  -> source unchanged (top item known), skipped")
                return []
        items.append({
            "date": "",
            "title": title,
            "source": "Boursenews",
            "url": link,
            "snippet": "",
            "full_content": "",
            "query_source": "direct:boursenews_stock",
        })
    logger.info("  -> %d items", len(items))
    return items


def scrape_leconomiste_search(known_url_keys: Optional[set[str]] = None) -> list[dict]:
    """L'Economiste WordPress search — direct article URLs for Attijariwafa."""
    url = "https://www.leconomiste.com/?s=attijariwafa"
    logger.info("Direct scrape: L'Economiste search (%s)", url)
    html = _fetch(url)
    if not html:
        return []
    soup = BeautifulSoup(html, "html.parser")
    items = []
    seen: set[str] = set()
    for a in soup.find_all("a", href=True):
        href = a["href"]
        if "leconomiste.com/" not in href:
            continue
        if any(seg in href for seg in ("/search/", "/?s=", "/tags/", "/categories/")):
            continue
        title = a.get_text(" ", strip=True)
        if not title or len(title) < 15:
            continue
        if not _mentions_atw(title, ""):
            continue
        if href in seen:
            continue
        seen.add(href)
        if known_url_keys is not None and not items:
            if _url_key(href) in known_url_keys:
                logger.info("  -> source unchanged (top item known), skipped")
                return []
        items.append({
            "date": "",
            "title": title,
            "source": "L'Economiste",
            "url": href,
            "snippet": "",
            "full_content": "",
            "query_source": "direct:leconomiste_search",
        })
    logger.info("  -> %d items", len(items))
    return items


def scrape_aujourdhui_search(max_pages: int = 10, known_url_keys: Optional[set[str]] = None) -> list[dict]:
    """Aujourd'hui le Maroc WordPress search — Attijariwafa bank articles.

    Paginates through /page/N?s=Attijariwafa%20bank until a page returns
    zero new items (or max_pages hit). Each result has the title in a link
    and the French date nearby ("26 février 2026").
    """
    base = "https://aujourdhui.ma/page/{page}?s=Attijariwafa%20bank"
    logger.info("Direct scrape: Aujourd'hui search (up to %d pages)", max_pages)
    items = []
    seen: set[str] = set()
    for page in range(1, max_pages + 1):
        url = base.format(page=page)
        html = _fetch(url, timeout=45, retries=2)
        if not html:
            break
        soup = BeautifulSoup(html, "html.parser")
        page_new = 0
        for a in soup.find_all("a", href=True):
            href = a["href"]
            if "aujourdhui.ma" not in href:
                continue
            if any(seg in href for seg in ("?s=", "/tag/", "/category/", "/author/", "/page/")):
                continue
            title = a.get_text(" ", strip=True)
            if not title or len(title) < 20:
                continue
            if not _mentions_atw(title, ""):
                continue
            if href in seen:
                continue
            seen.add(href)
            if known_url_keys is not None and page_new == 0:
                if _url_key(href) in known_url_keys:
                    if page == 1:
                        logger.info("  -> source unchanged (top item known), skipped")
                        return []
                    else:
                        logger.info("  page %d: top item known, stopping pagination", page)
                        return items
            date_str = ""
            parent = a.find_parent(["article", "div", "li"])
            if parent:
                date_str = _parse_french_date(parent.get_text(" ", strip=True))
            items.append({
                "date": date_str,
                "title": title,
                "source": "Aujourd'hui",
                "url": href,
                "snippet": "",
                "full_content": "",
                "query_source": "direct:aujourdhui_search",
            })
            page_new += 1
        logger.info("  page %d: %d new items", page, page_new)
        if page_new == 0:
            break
        time.sleep(POLITE_DELAY)
    logger.info("  -> %d items total", len(items))
    return items


def scrape_attijari_cib_insights() -> list[dict]:
    """Attijari CIB insights/actualites — group-adjacent analyst research.

    Not ATW-specific, so apply the ATW-mention filter to titles.
    """
    url = "https://attijaricib.com/fr/insights/actualites"
    logger.info("Direct scrape: Attijari CIB insights (%s)", url)
    html = _fetch(url)
    if not html:
        return []
    soup = BeautifulSoup(html, "html.parser")
    items = []
    seen: set[str] = set()
    for a in soup.find_all("a", href=True):
        href = a["href"]
        if "/fr/insights/actualites/" not in href:
            continue
        # Skip the hub landing page itself
        if href.rstrip("/").endswith("/actualites"):
            continue
        title = a.get_text(" ", strip=True)
        if not title or len(title) < 15:
            continue
        if not _mentions_atw(title, ""):
            continue
        link = _abs_url("https://attijaricib.com", href)
        if link in seen:
            continue
        seen.add(link)
        items.append({
            "date": "",
            "title": title,
            "source": "Attijari CIB",
            "url": link,
            "snippet": "",
            "full_content": "",
            "query_source": "direct:attijari_cib",
        })
    logger.info("  -> %d items", len(items))
    return items


# ---------------------------------------------------------------------------
# Deduplication + CSV
# ---------------------------------------------------------------------------

def deduplicate(articles: Iterable[dict]) -> list[dict]:
    ranked = sorted(
        list(articles),
        key=lambda a: (
            "news.google.com/rss/articles/" not in (a.get("url", "").lower()),
            bool(a.get("full_content")),
            bool(a.get("date")),
        ),
        reverse=True,
    )
    seen_urls: set[str] = set()
    seen_date_titles: set[str] = set()
    seen_titles: set[str] = set()
    out: list[dict] = []
    for a in ranked:
        url_raw = a.get("url") or ""
        url_key = _canonical_url(url_raw)
        title_key = _normalize_title(a.get("title", ""))
        if not url_key or not title_key:
            continue

        date_key = (_parse_date(a.get("date")) or "")[:10]
        date_title_key = f"{date_key}|{title_key}" if date_key else ""
        is_gnews = "news.google.com/rss/articles/" in url_raw.lower()

        if url_key in seen_urls:
            continue
        if date_title_key and date_title_key in seen_date_titles:
            continue
        if not date_title_key and title_key in seen_titles:
            continue
        if is_gnews and title_key in seen_titles:
            continue

        seen_urls.add(url_key)
        seen_titles.add(title_key)
        if date_title_key:
            seen_date_titles.add(date_title_key)
        out.append(a)
    return out


def filter_noise_articles(articles: Iterable[dict]) -> list[dict]:
    return [a for a in articles if not _is_noise_article(a)]


def add_signal_metadata(articles: Iterable[dict]) -> list[dict]:
    out: list[dict] = []
    scraping_time = datetime.now(timezone.utc).isoformat()
    for article in articles:
        row = dict(article)
        row.setdefault("ticker", TICKER)
        score, is_core = _compute_signal_fields(row)
        row["signal_score"] = score
        row["is_atw_core"] = is_core
        # Preserve existing scraping_date (old articles), set current time only for new
        row.setdefault("scraping_date", scraping_time)
        out.append(row)
    return out


def filter_since(articles: list[dict], since_iso: Optional[str]) -> list[dict]:
    if not since_iso:
        return articles
    cutoff = datetime.fromisoformat(since_iso).replace(tzinfo=timezone.utc)
    kept = []
    for a in articles:
        date_str = a.get("date")
        if not date_str:
            kept.append(a)  # keep undated rather than drop
            continue
        try:
            d = datetime.fromisoformat(date_str)
            if d.tzinfo is None:
                d = d.replace(tzinfo=timezone.utc)
            if d >= cutoff:
                kept.append(a)
        except ValueError:
            kept.append(a)
    return kept


CSV_FIELDS = [
    "date", "ticker", "title", "source", "url", "full_content",
    "query_source", "signal_score", "is_atw_core", "scraping_date",
]


def _flatten(value) -> str:
    """Collapse newlines so each article stays on one CSV line."""
    s = "" if value is None else str(value)
    return re.sub(r"\s*\n+\s*", " ", s).strip()


def save_csv(articles: list[dict], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=CSV_FIELDS)
        w.writeheader()
        for a in articles:
            w.writerow({k: _flatten(a.get(k, "")) for k in CSV_FIELDS})


def enrich_with_bodies(
    articles: list[dict],
    limit: Optional[int] = None,
    existing: Optional[dict[str, dict]] = None,
    failed_urls: Optional[set[str]] = None,
    gnews_cache: Optional[dict[str, str]] = None,
    state: Optional[dict] = None,
    save_every: int = 20,
) -> list[dict]:
    """For each article, resolve Google-News redirect → publisher URL, then
    fetch + extract the article body with trafilatura. Articles whose resolved
    host matches the blocklist are dropped here (caught after redirect).

    A `limit` caps how many articles get body fetching — useful for fast
    test runs. Unfetched articles keep an empty full_content.

    If `existing` is given (keyed by url_key), articles whose URL is already
    present with a non-empty full_content reuse the cached body and skip the
    network fetch entirely — the big incremental-run win.
    """
    total = len(articles)
    existing = existing or {}
    failed_urls = failed_urls or set()
    gnews_cache = gnews_cache if gnews_cache is not None else {}
    logger.info(
        "Enriching %d articles (resolve Google News + fetch body)%s",
        total,
        f", body limit={limit}" if limit is not None else "",
    )
    kept: list[dict] = []
    fetched = 0
    reused = 0
    skipped_failed = 0
    for idx, a in enumerate(articles, 1):
        url = a.get("url", "")
        if not url:
            kept.append(a)
            continue

        # Resolve redirect — Google News wraps the real URL. Cache resolved
        # URLs across runs (gnewsdecoder costs 2-3s per call), so the next run
        # short-circuits without any network.
        if "news.google.com" in url:
            cached = gnews_cache.get(url)
            if cached:
                final_url = cached
            else:
                final_url = _resolve_final_url(url)
                if final_url and "news.google.com" not in final_url:
                    gnews_cache[url] = final_url
        else:
            final_url = url
        # Drop if still a Google News URL (decoder failed) — source is unreliable.
        if "news.google.com" in final_url:
            logger.debug("Dropped unresolved Google News URL: %s", final_url)
            continue
        if _host_blocked(final_url):
            logger.debug("Dropped after redirect (blocked host): %s", final_url)
            continue
        a["url"] = final_url

        key = _url_key(final_url)
        prior = existing.get(key)
        if prior and prior.get("full_content"):
            a["full_content"] = prior["full_content"]
            # Back-fill date if row has none but cache does, else fetch it once.
            if not a.get("date"):
                cached_date = (prior.get("date") or "").strip()
                if cached_date:
                    a["date"] = cached_date
                elif limit is None or fetched < limit:
                    a["date"] = _fetch_article_date_only(final_url)
                    if a["date"]:
                        existing[key]["date"] = a["date"]
                    time.sleep(POLITE_DELAY)
            reused += 1
        elif key in failed_urls:
            # Previous run couldn't extract a body — paywall, bot wall, or
            # publisher layout trafilatura can't parse. Skip forever (until
            # --full-refresh) to avoid paying the network + 1s polite delay
            # on every run for URLs we know fail.
            skipped_failed += 1
        elif limit is None or fetched < limit:
            body, page_date = _fetch_article_body(final_url)
            if body:
                a["full_content"] = body
                if not a.get("date") and page_date:
                    a["date"] = page_date
                existing[key] = dict(a)  # checkpoint into cache in-memory
                fetched += 1
            else:
                failed_urls.add(key)
            time.sleep(POLITE_DELAY)

        kept.append(a)
        if idx % 10 == 0 or idx == total:
            logger.info(
                "  progress: %d/%d processed, %d fetched, %d reused, %d skipped-failed",
                idx, total, fetched, reused, skipped_failed,
            )

        # Periodic state checkpoint — so a killed run still persists
        # gnews resolutions + failed-URL markers instead of losing everything.
        if state is not None and idx % save_every == 0:
            state["failed_body_urls"] = sorted(failed_urls)
            state["gnews_resolved"] = gnews_cache
            try:
                _save_state(state)
            except OSError as exc:
                logger.warning("State checkpoint failed: %s", exc)

    logger.info(
        "Enriched %d/%d articles (fetched %d new, reused %d cached, skipped %d known-failed)",
        fetched + reused, len(kept), fetched, reused, skipped_failed,
    )
    return kept


# ---------------------------------------------------------------------------
# Incremental state — scrape new, not old
# ---------------------------------------------------------------------------

def _empty_state() -> dict:
    return {
        "seen_urls": {},
        "per_source_last_seen": {},
        "failed_body_urls": [],
        "gnews_resolved": {},
        "last_full_run_ts": None,
    }


def _load_state() -> dict:
    if not STATE_FILE.exists():
        return _empty_state()
    try:
        with open(STATE_FILE, "r", encoding="utf-8") as f:
            s = json.load(f)
        s.setdefault("seen_urls", {})
        s.setdefault("per_source_last_seen", {})
        s.setdefault("failed_body_urls", [])
        s.setdefault("gnews_resolved", {})
        s.setdefault("last_full_run_ts", None)
        return s
    except (json.JSONDecodeError, OSError):
        logger.warning("News state corrupt — starting fresh.")
        return _empty_state()


def _save_state(state: dict) -> None:
    STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    tmp = STATE_FILE.with_suffix(".json.tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(state, f, indent=2, ensure_ascii=False)
    os.replace(tmp, STATE_FILE)


def _url_key(url: str) -> str:
    return _canonical_url(url)


def _load_existing_csv(path: Path) -> dict[str, dict]:
    """Load existing articles keyed by url_key — lets us preserve bodies we
    already fetched and append-only new rows.
    """
    if not path.exists():
        return {}
    out: dict[str, dict] = {}
    with open(path, "r", encoding="utf-8", newline="") as f:
        for row in csv.DictReader(f):
            k = _url_key(row.get("url", ""))
            if k:
                out[k] = row
    return out


def _load_csv_rows(path: Path) -> list[dict]:
    if not path.exists():
        return []
    with open(path, "r", encoding="utf-8", newline="") as f:
        return list(csv.DictReader(f))


def backfill_existing_csv(path: Path) -> list[dict]:
    rows = _load_csv_rows(path)
    if not rows:
        logger.warning("No existing CSV found at %s", path)
        return []
    processed = add_signal_metadata(deduplicate(filter_noise_articles(rows)))
    processed.sort(key=lambda r: r.get("date") or "", reverse=True)
    save_csv(processed, path)
    logger.info(
        "Backfilled %d rows in %s (from %d raw rows)",
        len(processed), path, len(rows),
    )
    return processed


def scrape_medias24_wp_posts(max_pages: int = 3, known_url_keys: Optional[set[str]] = None) -> list[dict]:
    """Medias24 WordPress REST API — filtered by tag id 8987 (attijariwafa-bank).

    Much cleaner than the topic HTML scrape: structured JSON, reliable
    dates, excerpts included. Paginates with `?page=N&per_page=100` — cap at
    `max_pages` so a single run doesn't walk the whole archive.
    """
    logger.info("Direct scrape: Medias24 WP API (tag=%d)", MEDIAS24_WP_TAG_ATW)
    items: list[dict] = []
    for page in range(1, max_pages + 1):
        try:
            r = requests.get(
                "https://medias24.com/wp-json/wp/v2/posts",
                params={
                    "tags": MEDIAS24_WP_TAG_ATW,
                    "per_page": 100,
                    "page": page,
                    "orderby": "date",
                    "order": "desc",
                    "_fields": "id,date,link,title,excerpt",
                },
                headers={"User-Agent": USER_AGENT, "Accept": "application/json"},
                timeout=REQUEST_TIMEOUT,
            )
        except requests.RequestException as exc:
            logger.warning("Medias24 WP API page %d failed: %s", page, exc)
            break
        if r.status_code == 400:
            # WP returns 400 past the last page — normal end-of-pagination.
            break
        if r.status_code != 200:
            logger.warning("Medias24 WP API page %d HTTP %s", page, r.status_code)
            break
        try:
            batch = r.json()
        except ValueError:
            break
        if not isinstance(batch, list) or not batch:
            break
        if known_url_keys is not None:
            first_link = (batch[0].get("link", "") or "") if batch else ""
            if first_link and _url_key(first_link) in known_url_keys:
                if page == 1:
                    logger.info("  -> source unchanged (top item known), skipped")
                    return []
                else:
                    logger.info("  page %d: top item known, stopping pagination", page)
                    break
        for p in batch:
            link = p.get("link", "") or ""
            title_html = (p.get("title") or {}).get("rendered", "") or ""
            excerpt_html = (p.get("excerpt") or {}).get("rendered", "") or ""
            # Strip the <span class="premium-post">...</span> wrapper when present.
            title = BeautifulSoup(title_html, "html.parser").get_text(" ", strip=True)
            excerpt = BeautifulSoup(excerpt_html, "html.parser").get_text(" ", strip=True)
            if not link or not title:
                continue
            items.append({
                "date": _parse_date(p.get("date", "")),
                "title": title,
                "source": "Medias24",
                "url": link,
                "snippet": excerpt,
                "full_content": "",
                "query_source": "direct:medias24_wp",
            })
        time.sleep(POLITE_DELAY)
    logger.info("  -> %d items", len(items))
    return items


def scrape_marketscreener_atw_news(known_url_keys: Optional[set[str]] = None) -> list[dict]:
    """MarketScreener dedicated ATW news page — earnings, analyst notes, ratings.
    
    Scrapes https://www.marketscreener.com/quote/stock/ATTIJARIWAFA-BANK-SA-41148801/news/
    for news articles specific to Attijariwafa Bank.
    """
    url = "https://www.marketscreener.com/quote/stock/ATTIJARIWAFA-BANK-SA-41148801/news/"
    logger.info("Direct scrape: MarketScreener ATW news (%s)", url)
    html = _fetch(url)
    if not html:
        return []
    soup = BeautifulSoup(html, "html.parser")
    items = []
    seen: set[str] = set()
    
    # MarketScreener news pages use <a> links with href containing /news/
    # Look for all article links on the page
    news_link_pattern = re.compile(r'/news/.*-(?:\d{6,}|[a-f0-9]{15,})', re.IGNORECASE)
    
    for a in soup.find_all("a", href=True):
        href = a["href"]
        # Match MarketScreener news article patterns
        if not news_link_pattern.search(href):
            continue
        
        title = a.get_text(" ", strip=True)
        if not title or len(title) < 15:
            continue
        
        # Construct absolute URL
        link = href if href.startswith("http") else f"https://www.marketscreener.com{href}"
        
        if link in seen:
            continue
        seen.add(link)
        if known_url_keys is not None and not items:
            if _url_key(link) in known_url_keys:
                logger.info("  -> source unchanged (top item known), skipped")
                return []

        # MarketScreener embeds the ISO date in <span class="js-date-relative" data-utc-date="...">
        date_str = ""
        parent = a.find_parent("tr") or a.find_parent("div")
        if parent:
            date_span = parent.find("span", attrs={"data-utc-date": True})
            if date_span:
                date_str = _parse_date(date_span["data-utc-date"])
            if not date_str:
                text = parent.get_text(" ", strip=True)
                date_match = re.search(r'(\d{2}/\d{2}/\d{4}|\d{4}-\d{2}-\d{2})', text)
                if date_match:
                    date_str = _parse_date(date_match.group(1))
        
        items.append({
            "date": date_str,
            "title": title,
            "source": "MarketScreener",
            "url": link,
            "snippet": "",
            "full_content": "",
            "query_source": "direct:marketscreener_atw_news",
        })
    
    logger.info("  -> %d items", len(items))
    return items


# ---------------------------------------------------------------------------
# Orchestration
# ---------------------------------------------------------------------------

def run(
    out_path: Path,
    since: Optional[str] = None,
    fetch_bodies: bool = False,
    body_limit: Optional[int] = None,
    full_refresh: bool = False,
    include_gnews: bool = False,
) -> list[dict]:
    state = _empty_state() if full_refresh else _load_state()
    failed_urls: set[str] = set(state.get("failed_body_urls", []))
    gnews_cache: dict[str, str] = dict(state.get("gnews_resolved", {}))
    existing = {} if full_refresh else _load_existing_csv(out_path)

    deep = include_gnews and fetch_bodies
    if deep:
        mode = "direct + Google News, body fetch enabled [DEEP]"
    elif include_gnews:
        mode = "direct + Google News, no body fetch"
    elif fetch_bodies:
        mode = "direct sources only, body fetch enabled"
    else:
        mode = "direct sources only, no body fetch (fast path)"
    logger.info("Mode: %s", mode)
    logger.info(
        "Incremental run: %d URLs in state, %d rows in existing CSV%s",
        len(state.get("seen_urls", {})), len(existing),
        " [FULL REFRESH]" if full_refresh else "",
    )

    all_items: list[dict] = []
    known_keys: set[str] = set(existing.keys())

    # High-signal direct sources first — these are ATW-specific hubs.
    # IR Attijariwafa and Attijari CIB removed: article pages don't expose dates.
    all_items.extend(scrape_medias24_topic(known_url_keys=known_keys))
    time.sleep(POLITE_DELAY)
    all_items.extend(scrape_medias24_wp_posts(known_url_keys=known_keys))
    time.sleep(POLITE_DELAY)
    all_items.extend(scrape_boursenews_stock(known_url_keys=known_keys))
    time.sleep(POLITE_DELAY)
    all_items.extend(scrape_marketscreener_atw_news(known_url_keys=known_keys))
    time.sleep(POLITE_DELAY)
    all_items.extend(scrape_leconomiste_search(known_url_keys=known_keys))
    time.sleep(POLITE_DELAY)
    all_items.extend(scrape_aujourdhui_search(known_url_keys=known_keys))
    time.sleep(POLITE_DELAY)

    # Broad discovery fallback — catches international coverage. Off by
    # default because gnewsdecoder is slow (~3s/URL) and the direct sources
    # already cover ~150 ATW-specific articles. Enable with --with-gnews.
    if include_gnews:
        for query, hl, gl, ceid in GOOGLE_NEWS_QUERIES:
            all_items.extend(fetch_google_news_rss(query, hl, gl, ceid))
            time.sleep(POLITE_DELAY)

    for name, url in GENERIC_FEEDS:
        all_items.extend(fetch_rss_feed(name, url))
        time.sleep(POLITE_DELAY)

    # Tag every article with the ticker — single source of truth for joins
    # with market data. Today ATW-only; extend when multi-ticker lands.
    for a in all_items:
        a.setdefault("ticker", TICKER)

    cleaned = filter_noise_articles(all_items)
    deduped = deduplicate(cleaned)
    filtered = filter_since(deduped, since)
    filtered.sort(key=lambda a: a.get("date") or "", reverse=True)

    if fetch_bodies:
        filtered = enrich_with_bodies(
            filtered, limit=body_limit, existing=existing,
            failed_urls=failed_urls, gnews_cache=gnews_cache,
            state=state,
        )

    # Merge new results with existing rows — append-only, keyed on url_key.
    # Preserve full_content from existing when this run didn't get one (e.g.
    # --no-bodies, or body fetch returned empty), so we never destroy cache.
    merged: dict[str, dict] = dict(existing)
    for a in filtered:
        k = _url_key(a.get("url", ""))
        if not k:
            continue
        prior = merged.get(k)
        if prior:
            if prior.get("full_content") and not a.get("full_content"):
                a["full_content"] = prior["full_content"]
            if prior.get("date") and not a.get("date"):
                a["date"] = prior["date"]
        merged[k] = a
    raw_merged_count = len(merged)
    final_rows = add_signal_metadata(deduplicate(filter_noise_articles(merged.values())))
    final_rows.sort(key=lambda r: r.get("date") or "", reverse=True)

    save_csv(final_rows, out_path)
    logger.info(
        "Saved %d articles to %s (%d new this run, %d merged before cleanup)",
        len(final_rows), out_path, len(filtered), raw_merged_count,
    )

    # Persist state: per-URL first-seen date, per-source most recent date.
    seen = state.get("seen_urls", {})
    per_source = state.get("per_source_last_seen", {})
    for a in filtered:
        k = _url_key(a.get("url", ""))
        if not k:
            continue
        date = a.get("date") or ""
        seen.setdefault(k, date)
        qs = a.get("query_source") or ""
        if qs and date and date > per_source.get(qs, ""):
            per_source[qs] = date
    state["seen_urls"] = seen
    state["per_source_last_seen"] = per_source
    state["failed_body_urls"] = sorted(failed_urls)
    state["gnews_resolved"] = gnews_cache
    state["last_full_run_ts"] = datetime.now(timezone.utc).isoformat()
    _save_state(state)

    return filtered


def main():
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s - %(levelname)s - %(message)s",
    )
    parser = argparse.ArgumentParser(
        description=(
            "ATW News Scraper (Attijariwafa Bank). "
            "Default: direct sources only, no body fetch — fast path (<30s). "
            "Use --deep for full discovery + body enrichment."
        ),
    )
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT, help="Output CSV path")
    parser.add_argument("--since", type=str, default=None, help="Only keep articles on/after YYYY-MM-DD")
    parser.add_argument("--with-gnews", action="store_true",
                        help="Enable Google News RSS discovery (slow: gnewsdecoder ~3s per URL)")
    parser.add_argument("--with-bodies", dest="with_bodies", action="store_true", default=True,
                        help="[DEFAULT] Enable trafilatura body enrichment (cache-aware: only new URLs are fetched)")
    parser.add_argument("--no-bodies", dest="with_bodies", action="store_false",
                        help="Skip body enrichment entirely (listings only, ~25s)")
    parser.add_argument("--deep", action="store_true",
                        help="Shorthand for --with-gnews --with-bodies")
    parser.add_argument("--body-limit", type=int, default=None,
                        help="Cap new body fetches per run")
    parser.add_argument("--full-refresh", action="store_true",
                        help="Ignore state + existing CSV and re-scrape everything from scratch")
    parser.add_argument("--backfill-existing", action="store_true",
                        help="Reprocess existing CSV only (noise filter + dedup + signal columns)")
    args = parser.parse_args()

    if args.backfill_existing:
        rows = backfill_existing_csv(args.out)
        print(f"\nBackfilled {len(rows)} ATW articles in {args.out}")
        return

    include_gnews = args.with_gnews or args.deep
    fetch_bodies = args.with_bodies or args.deep

    results = run(
        args.out,
        since=args.since,
        fetch_bodies=fetch_bodies,
        body_limit=args.body_limit,
        full_refresh=args.full_refresh,
        include_gnews=include_gnews,
    )
    with_body = sum(1 for r in results if r.get("full_content"))
    print(f"\n{len(results)} ATW articles saved to {args.out} ({with_body} with full body)")


if __name__ == "__main__":
    main()
