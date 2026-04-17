"""
ATW News Scraper — RSS-based
Collects Attijariwafa Bank news from Google News RSS, Moroccan financial sites,
Medias24 WP API, and MarketScreener. Filters, deduplicates, scores, and saves
to data/historical/ATW_news.csv.

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
os.environ["CURL_CA_BUNDLE"]     = certifi.where()
os.environ["SSL_CERT_FILE"]      = certifi.where()

import feedparser
import requests
from bs4 import BeautifulSoup

import sys
_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_ROOT))
from db.writer import upsert_news

DEFAULT_OUT = _ROOT / "data" / "historical" / "ATW_news.csv"
STATE_FILE  = _ROOT / "data" / "scrapers" / "atw_news_state.json"
TICKER      = "ATW"
MEDIAS24_WP_TAG_ATW = 8987

USER_AGENT      = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                   "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36")
REQUEST_TIMEOUT = 20
POLITE_DELAY    = 1.0

BLOCKED_HOST_SUBSTRINGS = (
    "attijariwafa", "attijari.com", "daralmoukawil.com",
    "facebook.com", "instagram.com", "twitter.com", "threads.net",
    "tiktok.com", "youtube.com", "youtu.be", "linkedin.com",
    "pinterest.", "reddit.com", "bebee.com",
    "waze.com", "openstreetmap", "foursquare", "yelp.",
    "remitly.com", "wise.com", "wewire.com", "transferwise.com",
    "worldremit.com", "xoom.com", "moneygram.com", "westernunion.com", "paysend.com",
    "rekrute.com", "emploi.ma", "anapec.org", "bayt.com", "indeed.com",
    "glassdoor.com", "welcometothejungle.com", "jobzyn.com", "monster.com",
    "bghit-nekhdem", "drh.ma",
    "apps.apple.com", "play.google.com", "lbankalik.ma",
    "remittanceprices.worldbank.org", "xe.com", "qonto.com", "globaldata.com",
    "euroquity.com", "viguier.com", "wikipedia.org", "fsma.be",
    "greenclimate.fund", "eib.org", "hps-worldwide.com",
    "royalairmaroc.com", "airarabia.com",
    "prnewswire.com", "businesswire.com",
)

BLOCKED_HOSTPATH_SUBSTRINGS = ("x.com/", "google.com/maps")

WHITELISTED_HOST_SUFFIXES = ("ir.attijariwafabank.com", "attijaricib.com")

BLOCKED_HOSTS: set[str] = set()
BLOCKED_SOURCE_SUBSTRINGS = BLOCKED_HOST_SUBSTRINGS + BLOCKED_HOSTPATH_SUBSTRINGS

ATW_TOKEN_RE = re.compile(r"\b(attijariwafa|attijari\s*wafa|\bATW\b)", re.IGNORECASE)
NOISE_SOURCE_SUBSTRINGS = ("bebee", "instagram", "facebook.com")
FOCUS_PME_RE  = re.compile(r"\bfocus\s*pme\b", re.IGNORECASE)
EGYPT_KEYWORD_RE = re.compile(
    r"\b(egypt|egypte|égypte|cairo|le\s+caire|alexandrie|alexandria|egx|attijariwafa\s+bank\s+egypt)\b",
    re.IGNORECASE,
)
MOROCCO_CONTEXT_RE = re.compile(
    r"\b(maroc|morocco|casablanca|bourse de casablanca|masi|ammc|bank al[-\s]?maghrib|bam)\b",
    re.IGNORECASE,
)
ATW_CORE_SIGNAL_RE = re.compile(
    r"\b(résultats?|resultats?|earnings|rnpg|pnb|bénéfices?|benefices?|profits?|net income|"
    r"chiffre d'affaires|revenus?|croissance|guidance|outlook|"
    r"dividendes?|dividend|"
    r"strat[ée]gie|plan strat[ée]gique|transformation|acquisition|fusion|cession|"
    r"rating|notation|recommandation|cours cible|objectif de cours|upgrade|downgrade|surpond[ée]rer|"
    r"valorisation|capitalisation|bourse)\b",
    re.IGNORECASE,
)
ATW_PASSING_RE = re.compile(
    r"\b(forum|salon|webinaire|événement|evenement|event|sponsor|sponsoring|campagne)\b",
    re.IGNORECASE,
)

GOOGLE_NEWS_QUERIES = [
    ('"Attijariwafa bank" -site:attijariwafa.com -site:attijariwafabank.com', "fr", "MA", "MA:fr"),
    ('"Attijariwafa" -site:attijariwafa.com -site:attijariwafabank.com',      "fr", "MA", "MA:fr"),
    ('"Attijariwafa bank" -site:attijariwafa.com -site:attijariwafabank.com', "en", "US", "US:en"),
]

GENERIC_FEEDS: list[tuple[str, str]] = []

logger = logging.getLogger("atw_news")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _fetch(url: str, timeout: int = REQUEST_TIMEOUT, retries: int = 1) -> Optional[str]:
    for attempt in range(retries + 1):
        try:
            resp = requests.get(url, headers={"User-Agent": USER_AGENT, "Accept": "*/*"}, timeout=timeout)
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
    """Normalize any date-ish input to ISO-8601. Returns '' on failure."""
    if not value:
        return ""
    if isinstance(value, time.struct_time):
        return datetime(*value[:6], tzinfo=timezone.utc).isoformat()
    if not isinstance(value, str) or not value.strip():
        return ""
    s = value.strip()
    for fmt in ("%Y-%m-%d",):
        try:
            return datetime.strptime(s, fmt).strftime("%Y-%m-%d")
        except ValueError:
            pass
    try:
        dt = datetime.fromisoformat(s)
        return dt.replace(tzinfo=dt.tzinfo or timezone.utc).astimezone(timezone.utc).isoformat()
    except ValueError:
        pass
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S"):
        try:
            return datetime.strptime(s, fmt).replace(tzinfo=timezone.utc).isoformat()
        except ValueError:
            pass
    try:
        from email.utils import parsedate_to_datetime
        dt = parsedate_to_datetime(s)
        return dt.replace(tzinfo=dt.tzinfo or timezone.utc).astimezone(timezone.utc).isoformat()
    except (TypeError, ValueError):
        pass
    return ""


_FRENCH_MONTHS = {
    "janvier": 1, "février": 2, "fevrier": 2, "mars": 3, "avril": 4,
    "mai": 5, "juin": 6, "juillet": 7, "août": 8, "aout": 8,
    "septembre": 9, "octobre": 10, "novembre": 11, "décembre": 12, "decembre": 12,
}


def _parse_french_date(s: str) -> str:
    """Parse 'Vendredi 10 Avril 2026' → 'YYYY-MM-DD'."""
    if not s:
        return ""
    m = re.search(
        r"(\d{1,2})\s+(janvier|février|fevrier|mars|avril|mai|juin|juillet|août|aout|septembre|octobre|novembre|décembre|decembre)\s+(\d{4})",
        s, re.IGNORECASE,
    )
    if not m:
        return ""
    day, month, year = int(m.group(1)), _FRENCH_MONTHS.get(m.group(2).lower()), int(m.group(3))
    try:
        return datetime(year, month, day).strftime("%Y-%m-%d") if month else ""
    except ValueError:
        return ""


def _extract_article_date(html: str) -> str:
    """Extract publication date from article HTML. Returns ISO string or ''."""
    if not html:
        return ""
    soup = BeautifulSoup(html, "html.parser")
    for attrs in (
        {"property": "article:published_time"}, {"property": "og:article:published_time"},
        {"name": "article:published_time"}, {"itemprop": "datePublished"},
        {"name": "date"}, {"name": "pubdate"}, {"name": "publish-date"},
    ):
        tag = soup.find("meta", attrs=attrs)
        if tag and tag.get("content"):
            parsed = _parse_date(tag["content"]) or _parse_french_date(tag["content"])
            if parsed:
                return parsed
    for t in soup.find_all("time"):
        parsed = _parse_date(t.get("datetime") or t.get_text(strip=True)) or \
                 _parse_french_date(t.get_text(strip=True))
        if parsed:
            return parsed
    for s in soup.find_all("script", type="application/ld+json"):
        for m in re.finditer(r'"datePublished"\s*:\s*"([^"]+)"', s.string or s.get_text() or ""):
            parsed = _parse_date(m.group(1)) or _parse_french_date(m.group(1))
            if parsed:
                return parsed
    return ""


def _mentions_atw(*fields: str) -> bool:
    return any(f and ATW_TOKEN_RE.search(f) for f in fields)


def _host_blocked(url: str) -> bool:
    try:
        parsed = urlparse(url)
        host = (parsed.hostname or "").lower()
        if not host:
            return False
        if any(host == w or host.endswith("." + w) for w in WHITELISTED_HOST_SUFFIXES):
            return False
        if host in BLOCKED_HOSTS or any(sub in host for sub in BLOCKED_HOST_SUBSTRINGS):
            return True
        path = (parsed.path or "").lower()
        first_seg = path[:path.index("/", 1) + 1] if "/" in path[1:] else path + "/"
        return any(sub in f"{host}{first_seg}" for sub in BLOCKED_HOSTPATH_SUBSTRINGS)
    except Exception:
        return False


def _resolve_final_url(url: str) -> str:
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
        resp = requests.get(url, headers={"User-Agent": USER_AGENT, "Accept": "*/*"},
                            timeout=REQUEST_TIMEOUT, allow_redirects=True)
        return resp.url or url
    except requests.RequestException:
        return url


def _fetch_article_body(url: str) -> tuple[str, str]:
    try:
        resp = requests.get(
            url,
            headers={"User-Agent": USER_AGENT, "Accept": "text/html,application/xhtml+xml",
                     "Accept-Language": "fr-FR,fr;q=0.9,en;q=0.8"},
            timeout=REQUEST_TIMEOUT, allow_redirects=True,
        )
        if resp.status_code != 200 or not resp.text:
            return "", ""
        import trafilatura
        text = trafilatura.extract(resp.text, url=resp.url, include_comments=False,
                                   include_tables=False, favor_recall=False)
        return (text or "").strip(), _extract_article_date(resp.text)
    except Exception as exc:
        logger.debug("Body extract failed for %s: %s", url, exc)
        return "", ""


def _fetch_article_date_only(url: str) -> str:
    try:
        resp = requests.get(
            url,
            headers={"User-Agent": USER_AGENT, "Accept": "text/html,application/xhtml+xml",
                     "Accept-Language": "fr-FR,fr;q=0.9,en;q=0.8"},
            timeout=REQUEST_TIMEOUT, allow_redirects=True,
        )
        return _extract_article_date(resp.text) if resp.status_code == 200 and resp.text else ""
    except Exception as exc:
        logger.debug("Date extract failed for %s: %s", url, exc)
        return ""


def _normalize_title(title: str) -> str:
    t = re.sub(r"\s+", " ", title or "").strip().lower()
    t = re.sub(
        r"\s(?:-|–|—|\|)\s(?:medias24|l['']?economiste|boursenews|infom[ée]diaire|facebook\.com|instagram\.com|bebee\.com)$",
        "", t, flags=re.IGNORECASE,
    )
    return re.sub(r"\s+", " ", re.sub(r"[^\w\sàâäéèêëïîôöùûüç%-]", " ", t, re.IGNORECASE)).strip()


def _canonical_url(url: str) -> str:
    raw = (url or "").strip()
    if not raw:
        return ""
    try:
        parsed = urlparse(raw)
    except ValueError:
        return raw.split("?")[0].rstrip("/").lower()
    host = (parsed.hostname or "").lower().removeprefix("www.")
    path = re.sub(r"/+", "/", parsed.path or "").rstrip("/") or "/"
    if path == "/":
        path = "/"
    query_params = parse_qs(parsed.query, keep_blank_values=False)
    for key in ("url", "u", "target", "dest", "destination"):
        for k in (key, key.upper()):
            if values := query_params.get(k):
                nested = unquote(values[0]).strip()
                if nested.startswith(("http://", "https://")):
                    return _canonical_url(nested)
    kept_items = sorted(
        (lk, v)
        for key, values in query_params.items()
        for lk in [key.lower()]
        if not lk.startswith("utm_") and lk not in {"oc","ved","usg","fbclid","gclid","igshid","mkt_tok","mc_cid","mc_eid"}
        for v in values
    )
    query = "&".join(f"{k}={v}" if v else k for k, v in kept_items)
    return (f"{host}{path}{'?' + query if query else ''}").lower()


def _is_egypt_specific(*fields: str) -> bool:
    text = " ".join(f for f in fields if f)
    return bool(text and EGYPT_KEYWORD_RE.search(text) and not MOROCCO_CONTEXT_RE.search(text))


def _is_noise_article(article: dict) -> bool:
    source = (article.get("source") or "").lower()
    url    = (article.get("url") or "").lower()
    title  = article.get("title") or ""
    snippet = article.get("snippet") or ""
    text   = f"{title} {snippet} {source} {url}"
    return (
        any(sub in source for sub in NOISE_SOURCE_SUBSTRINGS)
        or "bebee" in url or "instagram.com" in url
        or bool(FOCUS_PME_RE.search(text))
        or _is_egypt_specific(title, snippet, source, url)
    )


def _compute_signal_fields(article: dict) -> tuple[int, int]:
    title        = article.get("title") or ""
    snippet      = article.get("snippet") or ""
    full_content = article.get("full_content") or ""
    query_source = (article.get("query_source") or "").lower()
    text_all     = f"{title} {snippet} {full_content}"

    atw_title = _mentions_atw(title)
    atw_any   = _mentions_atw(title, snippet, full_content)
    core_title_hits = len(ATW_CORE_SIGNAL_RE.findall(title))
    core_all_hits   = len(ATW_CORE_SIGNAL_RE.findall(text_all))
    passing_hits    = len(ATW_PASSING_RE.findall(text_all))

    score = 10
    if atw_any:   score += 20
    if atw_title: score += 15
    score += min(core_title_hits, 3) * 18
    score += min(max(core_all_hits - core_title_hits, 0), 4) * 8
    if query_source.startswith("direct:"): score += 6
    score -= min(passing_hits, 3) * 8
    if _is_egypt_specific(title, snippet, full_content): score -= 40

    score   = max(0, min(100, score))
    is_core = int(atw_any and (core_title_hits > 0 or core_all_hits >= 2))
    return score, is_core


def _abs_url(base: str, href: str) -> str:
    if href.startswith("http"):  return href
    if href.startswith("//"):    return "https:" + href
    return base.rstrip("/") + "/" + href.lstrip("/")


# ---------------------------------------------------------------------------
# Fetchers
# ---------------------------------------------------------------------------

def fetch_google_news_rss(query: str, hl: str, gl: str, ceid: str) -> list[dict]:
    url = f"https://news.google.com/rss/search?q={quote_plus(query)}&hl={hl}&gl={gl}&ceid={ceid}"
    logger.info("Google News RSS: %s [%s]", query, ceid)
    content = _fetch(url)
    if not content:
        return []
    items = []
    for entry in feedparser.parse(content).entries:
        title = entry.get("title") or ""
        link  = entry.get("link") or ""
        if _host_blocked(link) or not _mentions_atw(title, entry.get("summary", "")):
            continue
        items.append({
            "date":         _parse_date(entry.get("published_parsed") or entry.get("published")),
            "title":        title.strip(),
            "source":       entry.get("source", {}).get("title") if isinstance(entry.get("source"), dict)
                            else (urlparse(link).hostname or "Google News"),
            "url":          link,
            "snippet":      BeautifulSoup(entry.get("summary", ""), "html.parser").get_text(" ", strip=True)[:400],
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
    items = []
    for entry in feedparser.parse(content).entries:
        title   = entry.get("title") or ""
        summary = BeautifulSoup(entry.get("summary", ""), "html.parser").get_text(" ", strip=True)
        link    = entry.get("link") or ""
        if not _mentions_atw(title, summary) or _host_blocked(link):
            continue
        items.append({
            "date": _parse_date(entry.get("published_parsed") or entry.get("published")),
            "title": title.strip(), "source": name, "url": link,
            "snippet": summary[:400], "full_content": "", "query_source": f"rss:{name}",
        })
    logger.info("  -> %d ATW-matching items", len(items))
    return items


# ---------------------------------------------------------------------------
# Generic link-page scraper (shared by boursenews, leconomiste)
# ---------------------------------------------------------------------------

def _scrape_link_page(
    url: str, source_name: str, query_source: str,
    base_url: str = "",
    url_must_contain: tuple = (),
    url_must_not_contain: tuple = (),
    min_title_len: int = 15,
    known_url_keys: Optional[set[str]] = None,
) -> list[dict]:
    html = _fetch(url)
    if not html:
        return []
    soup  = BeautifulSoup(html, "html.parser")
    items: list[dict] = []
    seen:  set[str]   = set()
    for a in soup.find_all("a", href=True):
        href = a["href"]
        if url_must_contain and not any(s in href for s in url_must_contain):
            continue
        if url_must_not_contain and any(s in href for s in url_must_not_contain):
            continue
        title = a.get_text(" ", strip=True)
        if not title or len(title) < min_title_len or not _mentions_atw(title, ""):
            continue
        link = _abs_url(base_url, href) if base_url else href
        if link in seen:
            continue
        seen.add(link)
        if known_url_keys is not None and not items:
            if _canonical_url(link) in known_url_keys:
                logger.info("  -> source unchanged (top item known), skipped")
                return []
        items.append({"date": "", "title": title, "source": source_name, "url": link,
                      "snippet": "", "full_content": "", "query_source": query_source})
    logger.info("  -> %d items", len(items))
    return items


# ---------------------------------------------------------------------------
# Direct topic/stock-page scrapers
# ---------------------------------------------------------------------------

def scrape_medias24_topic(known_url_keys: Optional[set[str]] = None) -> list[dict]:
    url = "https://medias24.com/sujet/attijariwafa-bank/"
    logger.info("Direct scrape: Medias24 topic (%s)", url)
    html = _fetch(url)
    if not html:
        return []
    soup  = BeautifulSoup(html, "html.parser")
    items: list[dict] = []
    seen:  set[str]   = set()
    for a in soup.find_all("a", href=True):
        href = a["href"]
        if "medias24.com/" not in href or not re.search(r"medias24\.com/\d{4}/\d{2}/\d{2}/", href):
            continue
        title = a.get_text(" ", strip=True)
        if not title or len(title) < 15 or href in seen:
            continue
        seen.add(href)
        slug_has_atw = "attijariwafa" in href.lower() or "/atw-" in href.lower()
        if not (slug_has_atw or _mentions_atw(title, "")):
            continue
        if known_url_keys is not None and not items:
            if _canonical_url(href) in known_url_keys:
                logger.info("  -> source unchanged (top item known), skipped")
                return []
        m = re.search(r"/(\d{4})/(\d{2})/(\d{2})/", href)
        date_iso = f"{m.group(1)}-{m.group(2)}-{m.group(3)}" if m else ""
        items.append({"date": date_iso, "title": title, "source": "Medias24", "url": href,
                      "snippet": "", "full_content": "", "query_source": "direct:medias24_topic"})
    logger.info("  -> %d items", len(items))
    return items


def scrape_boursenews_stock(known_url_keys: Optional[set[str]] = None) -> list[dict]:
    logger.info("Direct scrape: Boursenews stock")
    return _scrape_link_page(
        "https://boursenews.ma/action/attijariwafa-bank",
        "Boursenews", "direct:boursenews_stock",
        base_url="https://boursenews.ma",
        url_must_contain=("/article/marches/",),
        known_url_keys=known_url_keys,
    )


def scrape_leconomiste_search(known_url_keys: Optional[set[str]] = None) -> list[dict]:
    logger.info("Direct scrape: L'Economiste search")
    return _scrape_link_page(
        "https://www.leconomiste.com/?s=attijariwafa",
        "L'Economiste", "direct:leconomiste_search",
        url_must_contain=("leconomiste.com/",),
        url_must_not_contain=("/search/", "/?s=", "/tags/", "/categories/"),
        known_url_keys=known_url_keys,
    )


def scrape_aujourdhui_search(max_pages: int = 10, known_url_keys: Optional[set[str]] = None) -> list[dict]:
    base = "https://aujourdhui.ma/page/{page}?s=Attijariwafa%20bank"
    logger.info("Direct scrape: Aujourd'hui search (up to %d pages)", max_pages)
    items: list[dict] = []
    seen:  set[str]   = set()
    for page in range(1, max_pages + 1):
        html = _fetch(base.format(page=page), timeout=45, retries=2)
        if not html:
            break
        soup     = BeautifulSoup(html, "html.parser")
        page_new = 0
        for a in soup.find_all("a", href=True):
            href = a["href"]
            if "aujourdhui.ma" not in href:
                continue
            if any(seg in href for seg in ("?s=", "/tag/", "/category/", "/author/", "/page/")):
                continue
            title = a.get_text(" ", strip=True)
            if not title or len(title) < 20 or not _mentions_atw(title, "") or href in seen:
                continue
            seen.add(href)
            if known_url_keys is not None and page_new == 0:
                if _canonical_url(href) in known_url_keys:
                    if page == 1:
                        logger.info("  -> source unchanged (top item known), skipped")
                        return []
                    logger.info("  page %d: top item known, stopping pagination", page)
                    return items
            date_str = ""
            parent = a.find_parent(["article", "div", "li"])
            if parent:
                date_str = _parse_french_date(parent.get_text(" ", strip=True))
            items.append({"date": date_str, "title": title, "source": "Aujourd'hui", "url": href,
                          "snippet": "", "full_content": "", "query_source": "direct:aujourdhui_search"})
            page_new += 1
        logger.info("  page %d: %d new items", page, page_new)
        if page_new == 0:
            break
        time.sleep(POLITE_DELAY)
    logger.info("  -> %d items total", len(items))
    return items


def scrape_medias24_wp_posts(max_pages: int = 3, known_url_keys: Optional[set[str]] = None) -> list[dict]:
    logger.info("Direct scrape: Medias24 WP API (tag=%d)", MEDIAS24_WP_TAG_ATW)
    items: list[dict] = []
    for page in range(1, max_pages + 1):
        try:
            r = requests.get(
                "https://medias24.com/wp-json/wp/v2/posts",
                params={"tags": MEDIAS24_WP_TAG_ATW, "per_page": 100, "page": page,
                        "orderby": "date", "order": "desc",
                        "_fields": "id,date,link,title,excerpt"},
                headers={"User-Agent": USER_AGENT, "Accept": "application/json"},
                timeout=REQUEST_TIMEOUT,
            )
        except requests.RequestException as exc:
            logger.warning("Medias24 WP API page %d failed: %s", page, exc)
            break
        if r.status_code == 400:
            break  # past last page
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
            if first_link and _canonical_url(first_link) in known_url_keys:
                if page == 1:
                    logger.info("  -> source unchanged (top item known), skipped")
                    return []
                logger.info("  page %d: top item known, stopping pagination", page)
                break
        for p in batch:
            link        = p.get("link", "") or ""
            title_html  = (p.get("title") or {}).get("rendered", "") or ""
            excerpt_html = (p.get("excerpt") or {}).get("rendered", "") or ""
            title   = BeautifulSoup(title_html,   "html.parser").get_text(" ", strip=True)
            excerpt = BeautifulSoup(excerpt_html, "html.parser").get_text(" ", strip=True)
            if not link or not title:
                continue
            items.append({"date": _parse_date(p.get("date", "")), "title": title,
                          "source": "Medias24", "url": link, "snippet": excerpt,
                          "full_content": "", "query_source": "direct:medias24_wp"})
        time.sleep(POLITE_DELAY)
    logger.info("  -> %d items", len(items))
    return items


def scrape_marketscreener_atw_news(known_url_keys: Optional[set[str]] = None) -> list[dict]:
    url = "https://www.marketscreener.com/quote/stock/ATTIJARIWAFA-BANK-SA-41148801/news/"
    logger.info("Direct scrape: MarketScreener ATW news (%s)", url)
    html = _fetch(url)
    if not html:
        return []
    soup    = BeautifulSoup(html, "html.parser")
    items:  list[dict] = []
    seen:   set[str]   = set()
    pattern = re.compile(r'/news/.*-(?:\d{6,}|[a-f0-9]{15,})', re.IGNORECASE)
    for a in soup.find_all("a", href=True):
        href = a["href"]
        if not pattern.search(href):
            continue
        title = a.get_text(" ", strip=True)
        if not title or len(title) < 15:
            continue
        link = href if href.startswith("http") else f"https://www.marketscreener.com{href}"
        if link in seen:
            continue
        seen.add(link)
        if known_url_keys is not None and not items:
            if _canonical_url(link) in known_url_keys:
                logger.info("  -> source unchanged (top item known), skipped")
                return []
        date_str = ""
        parent = a.find_parent("tr") or a.find_parent("div")
        if parent:
            date_span = parent.find("span", attrs={"data-utc-date": True})
            if date_span:
                date_str = _parse_date(date_span["data-utc-date"])
            if not date_str:
                dm = re.search(r'(\d{2}/\d{2}/\d{4}|\d{4}-\d{2}-\d{2})', parent.get_text(" ", strip=True))
                if dm:
                    date_str = _parse_date(dm.group(1))
        items.append({"date": date_str, "title": title, "source": "MarketScreener", "url": link,
                      "snippet": "", "full_content": "", "query_source": "direct:marketscreener_atw_news"})
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
        url_raw  = a.get("url") or ""
        url_key  = _canonical_url(url_raw)
        title_key = _normalize_title(a.get("title", ""))
        if not url_key or not title_key:
            continue
        date_key       = (_parse_date(a.get("date")) or "")[:10]
        date_title_key = f"{date_key}|{title_key}" if date_key else ""
        is_gnews       = "news.google.com/rss/articles/" in url_raw.lower()
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


def add_signal_metadata(articles: Iterable[dict]) -> list[dict]:
    scraping_time = datetime.now(timezone.utc).isoformat()
    out: list[dict] = []
    for article in articles:
        row = dict(article)
        row.setdefault("ticker", TICKER)
        score, is_core = _compute_signal_fields(row)
        row["signal_score"] = score
        row["is_atw_core"]  = is_core
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
            kept.append(a)
            continue
        try:
            d = datetime.fromisoformat(date_str)
            if d.replace(tzinfo=d.tzinfo or timezone.utc) >= cutoff:
                kept.append(a)
        except ValueError:
            kept.append(a)
    return kept


CSV_FIELDS = [
    "date", "ticker", "title", "source", "url", "full_content",
    "query_source", "signal_score", "is_atw_core", "scraping_date",
]


def _flatten(value) -> str:
    return re.sub(r"\s*\n+\s*", " ", ("" if value is None else str(value))).strip()


def save_csv(articles: list[dict], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=CSV_FIELDS)
        w.writeheader()
        for a in articles:
            w.writerow({k: _flatten(a.get(k, "")) for k in CSV_FIELDS})
    _upsert_articles_to_db(articles)


def _upsert_articles_to_db(articles: list[dict]) -> None:
    rows = []
    for a in articles:
        url   = (a.get("url") or "").strip()
        title = (a.get("title") or "").strip()
        if not url or not title:
            continue
        signal = a.get("signal_score")
        try:
            signal = int(signal) if signal not in (None, "") else 0
        except (TypeError, ValueError):
            signal = 0
        core = a.get("is_atw_core")
        try:
            core = bool(int(core)) if core not in (None, "") else False
        except (TypeError, ValueError):
            core = bool(core)
        rows.append({
            "publish_date": a.get("date") or None,
            "title":        title,
            "source":       a.get("source") or None,
            "url":          url,
            "full_content": a.get("full_content") or None,
            "query_source": a.get("query_source") or None,
            "signal_score": signal,
            "is_atw_core":  core,
        })
    if rows:
        upsert_news(TICKER, rows)


def enrich_with_bodies(
    articles: list[dict],
    limit: Optional[int] = None,
    existing: Optional[dict[str, dict]] = None,
    failed_urls: Optional[set[str]] = None,
    gnews_cache: Optional[dict[str, str]] = None,
    state: Optional[dict] = None,
    save_every: int = 20,
) -> list[dict]:
    total       = len(articles)
    existing    = existing or {}
    failed_urls = failed_urls or set()
    gnews_cache = gnews_cache if gnews_cache is not None else {}
    logger.info("Enriching %d articles (resolve Google News + fetch body)%s",
                total, f", body limit={limit}" if limit is not None else "")
    kept: list[dict] = []
    fetched = reused = skipped_failed = 0

    for idx, a in enumerate(articles, 1):
        url = a.get("url", "")
        if not url:
            kept.append(a)
            continue

        # Resolve Google News redirect
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

        if "news.google.com" in final_url:
            logger.debug("Dropped unresolved Google News URL: %s", final_url)
            continue
        if _host_blocked(final_url):
            logger.debug("Dropped after redirect (blocked host): %s", final_url)
            continue
        a["url"] = final_url

        key   = _canonical_url(final_url)
        prior = existing.get(key)
        if prior and prior.get("full_content"):
            a["full_content"] = prior["full_content"]
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
            skipped_failed += 1
        elif limit is None or fetched < limit:
            body, page_date = _fetch_article_body(final_url)
            if body:
                a["full_content"] = body
                if not a.get("date") and page_date:
                    a["date"] = page_date
                existing[key] = dict(a)
                fetched += 1
            else:
                failed_urls.add(key)
            time.sleep(POLITE_DELAY)

        kept.append(a)
        if idx % 10 == 0 or idx == total:
            logger.info("  progress: %d/%d processed, %d fetched, %d reused, %d skipped-failed",
                        idx, total, fetched, reused, skipped_failed)
        if state is not None and idx % save_every == 0:
            state["failed_body_urls"] = sorted(failed_urls)
            state["gnews_resolved"]   = gnews_cache
            try:
                _save_state(state)
            except OSError as exc:
                logger.warning("State checkpoint failed: %s", exc)

    logger.info("Enriched %d/%d articles (fetched %d new, reused %d cached, skipped %d known-failed)",
                fetched + reused, len(kept), fetched, reused, skipped_failed)
    return kept


# ---------------------------------------------------------------------------
# State persistence
# ---------------------------------------------------------------------------

def _load_state() -> dict:
    defaults = {"seen_urls": {}, "per_source_last_seen": {}, "failed_body_urls": [],
                "gnews_resolved": {}, "last_full_run_ts": None}
    if not STATE_FILE.exists():
        return defaults
    try:
        with open(STATE_FILE, "r", encoding="utf-8") as f:
            s = json.load(f)
        for k, v in defaults.items():
            s.setdefault(k, v)
        return s
    except (json.JSONDecodeError, OSError):
        logger.warning("News state corrupt — starting fresh.")
        return defaults


def _save_state(state: dict) -> None:
    STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    tmp = STATE_FILE.with_suffix(".json.tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(state, f, indent=2, ensure_ascii=False)
    os.replace(tmp, STATE_FILE)


def _load_existing_csv(path: Path) -> dict[str, dict]:
    if not path.exists():
        return {}
    out: dict[str, dict] = {}
    with open(path, "r", encoding="utf-8", newline="") as f:
        for row in csv.DictReader(f):
            k = _canonical_url(row.get("url", ""))
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
    processed = add_signal_metadata(deduplicate([a for a in rows if not _is_noise_article(a)]))
    processed.sort(key=lambda r: r.get("date") or "", reverse=True)
    save_csv(processed, path)
    logger.info("Backfilled %d rows in %s (from %d raw rows)", len(processed), path, len(rows))
    return processed


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
    state      = {"seen_urls": {}, "per_source_last_seen": {}, "failed_body_urls": [],
                  "gnews_resolved": {}, "last_full_run_ts": None} if full_refresh else _load_state()
    failed_urls: set[str]    = set(state.get("failed_body_urls", []))
    gnews_cache: dict[str, str] = dict(state.get("gnews_resolved", {}))
    existing = {} if full_refresh else _load_existing_csv(out_path)

    mode = ("direct + Google News, body fetch enabled [DEEP]" if include_gnews and fetch_bodies
            else "direct + Google News, no body fetch"        if include_gnews
            else "direct sources only, body fetch enabled"    if fetch_bodies
            else "direct sources only, no body fetch (fast path)")
    logger.info("Mode: %s", mode)
    logger.info("Incremental run: %d URLs in state, %d rows in existing CSV%s",
                len(state.get("seen_urls", {})), len(existing),
                " [FULL REFRESH]" if full_refresh else "")

    known_keys: set[str] = set(existing.keys())
    all_items: list[dict] = []

    for fn, kw in [
        (scrape_medias24_topic,         {"known_url_keys": known_keys}),
        (scrape_medias24_wp_posts,      {"known_url_keys": known_keys}),
        (scrape_boursenews_stock,       {"known_url_keys": known_keys}),
        (scrape_marketscreener_atw_news,{"known_url_keys": known_keys}),
        (scrape_leconomiste_search,     {"known_url_keys": known_keys}),
        (scrape_aujourdhui_search,      {"known_url_keys": known_keys}),
    ]:
        all_items.extend(fn(**kw))
        time.sleep(POLITE_DELAY)

    if include_gnews:
        for query, hl, gl, ceid in GOOGLE_NEWS_QUERIES:
            all_items.extend(fetch_google_news_rss(query, hl, gl, ceid))
            time.sleep(POLITE_DELAY)

    for name, url in GENERIC_FEEDS:
        all_items.extend(fetch_rss_feed(name, url))
        time.sleep(POLITE_DELAY)

    for a in all_items:
        a.setdefault("ticker", TICKER)

    cleaned  = [a for a in all_items if not _is_noise_article(a)]
    deduped  = deduplicate(cleaned)
    filtered = filter_since(deduped, since)
    filtered.sort(key=lambda a: a.get("date") or "", reverse=True)

    if fetch_bodies:
        filtered = enrich_with_bodies(filtered, limit=body_limit, existing=existing,
                                      failed_urls=failed_urls, gnews_cache=gnews_cache, state=state)

    merged: dict[str, dict] = dict(existing)
    for a in filtered:
        k = _canonical_url(a.get("url", ""))
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
    final_rows = add_signal_metadata(deduplicate([a for a in merged.values() if not _is_noise_article(a)]))
    final_rows.sort(key=lambda r: r.get("date") or "", reverse=True)
    save_csv(final_rows, out_path)
    logger.info("Saved %d articles to %s (%d new this run, %d merged before cleanup)",
                len(final_rows), out_path, len(filtered), raw_merged_count)

    seen       = state.get("seen_urls", {})
    per_source = state.get("per_source_last_seen", {})
    for a in filtered:
        k = _canonical_url(a.get("url", ""))
        if not k:
            continue
        date = a.get("date") or ""
        seen.setdefault(k, date)
        qs = a.get("query_source") or ""
        if qs and date and date > per_source.get(qs, ""):
            per_source[qs] = date
    state.update({"seen_urls": seen, "per_source_last_seen": per_source,
                  "failed_body_urls": sorted(failed_urls), "gnews_resolved": gnews_cache,
                  "last_full_run_ts": datetime.now(timezone.utc).isoformat()})
    _save_state(state)
    return filtered


def main():
    logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
    parser = argparse.ArgumentParser(
        description="ATW News Scraper (Attijariwafa Bank). Default: direct sources, no body fetch."
    )
    parser.add_argument("--out",             type=Path, default=DEFAULT_OUT)
    parser.add_argument("--since",           type=str,  default=None)
    parser.add_argument("--with-gnews",      action="store_true")
    parser.add_argument("--with-bodies",     dest="with_bodies", action="store_true", default=True)
    parser.add_argument("--no-bodies",       dest="with_bodies", action="store_false")
    parser.add_argument("--deep",            action="store_true")
    parser.add_argument("--body-limit",      type=int,  default=None)
    parser.add_argument("--full-refresh",    action="store_true")
    parser.add_argument("--backfill-existing", action="store_true")
    args = parser.parse_args()

    if args.backfill_existing:
        rows = backfill_existing_csv(args.out)
        print(f"\nBackfilled {len(rows)} ATW articles in {args.out}")
        return

    results = run(
        args.out,
        since=args.since,
        fetch_bodies=args.with_bodies or args.deep,
        body_limit=args.body_limit,
        full_refresh=args.full_refresh,
        include_gnews=args.with_gnews or args.deep,
    )
    with_body = sum(1 for r in results if r.get("full_content"))
    print(f"\n{len(results)} ATW articles saved to {args.out} ({with_body} with full body)")


if __name__ == "__main__":
    main()