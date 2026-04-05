"""
CIH Daily Historical Data Scraper — Medias24 API
=================================================
Fetches daily OHLCV price history for CIH from Medias24's internal API.
Uses cloudscraper to bypass Cloudflare, hits the JSON endpoint directly.

API endpoint: /content/api?method=getStockOHLC&ISIN={isin}&format=json
Returns: [[timestamp_ms, open, high, low, close, volume], ...]

Usage:
    python scrapers/cih_history_scraper.py
"""

import os
import csv
import json
import certifi
from datetime import datetime, timezone
from typing import List, Dict, Optional
from pathlib import Path

import cloudscraper

# Fix SSL cert path (PostgreSQL install overrides system certs)
os.environ["REQUESTS_CA_BUNDLE"] = certifi.where()
os.environ["SSL_CERT_FILE"] = certifi.where()

_ROOT = Path(__file__).resolve().parent.parent

# --- Configuration ---
CIH_ISIN = "MA0000011454"
BASE_API = "https://medias24.com/content/api"

# Known ISINs for other Casablanca stocks (extend as needed)
STOCK_ISINS = {
    "CIH": "MA0000011454",
    "IAM": "MA0000011488",
    "BCP": "MA0000010506",
    "ATW": "MA0000012445",
    "BOA": "MA0000010027",
    "LBV": "MA0000010928",
    "MNG": "MA0000010811",
    "TQM": "MA0000012320",
    "CSR": "MA0000012080",
    "HPS": "MA0000011801",
}


def create_scraper() -> cloudscraper.CloudScraper:
    """Create a cloudscraper session that bypasses Cloudflare."""
    return cloudscraper.create_scraper(
        browser={"browser": "chrome", "platform": "windows", "mobile": False}
    )


def fetch_ohlcv(scraper: cloudscraper.CloudScraper, isin: str) -> List[List]:
    """Fetch OHLCV data from Medias24 API for a given ISIN."""
    url = f"{BASE_API}?method=getStockOHLC&ISIN={isin}&format=json"
    print(f"  Fetching {url}")

    resp = scraper.get(url, timeout=30)
    print(f"  HTTP {resp.status_code} — {len(resp.text):,} chars")

    if resp.status_code != 200:
        raise Exception(f"HTTP {resp.status_code}: {resp.text[:200]}")

    data = resp.json()

    # Handle wrapped response format: {"result": [...], "message": "200 OK"}
    if isinstance(data, dict) and "result" in data:
        data = data["result"]

    if not isinstance(data, list) or len(data) == 0:
        raise Exception(f"Unexpected response format: {str(data)[:200]}")

    return data


def fetch_stock_info(scraper: cloudscraper.CloudScraper, isin: str) -> Optional[Dict]:
    """Fetch real-time stock info (price, market cap, variation, etc.)."""
    url = f"{BASE_API}?method=getStockInfo&ISIN={isin}&format=json"
    print(f"  Fetching stock info: {url}")

    resp = scraper.get(url, timeout=30)
    if resp.status_code != 200:
        print(f"  Warning: getStockInfo returned {resp.status_code}")
        return None

    data = resp.json()

    # Handle wrapped response format: {"result": {...}, "message": "200 OK"}
    if isinstance(data, dict) and "result" in data:
        return data["result"]

    return data


def parse_ohlcv(raw_data: List[List]) -> List[Dict]:
    """
    Parse raw OHLCV arrays into dictionaries.
    Input:  [timestamp_ms, open, high, low, close, volume]
    Output: [{"date": "YYYY-MM-DD", "open": float, ...}, ...]
    """
    records = []
    for row in raw_data:
        if not isinstance(row, (list, tuple)) or len(row) < 6:
            continue

        ts_ms, o, h, l, c, v = row[:6]

        # Convert timestamp (ms) to date string
        try:
            dt = datetime.fromtimestamp(ts_ms / 1000, tz=timezone.utc)
            date_str = dt.strftime("%Y-%m-%d")
        except (ValueError, TypeError, OSError):
            continue

        # Convert values to float, skip row if close is missing
        try:
            record = {
                "date": date_str,
                "open": float(o) if o is not None else None,
                "high": float(h) if h is not None else None,
                "low": float(l) if l is not None else None,
                "close": float(c) if c is not None else None,
                "volume": int(v) if v is not None else 0,
            }
        except (ValueError, TypeError):
            continue

        if record["close"] is None:
            continue

        records.append(record)

    # Sort by date ascending
    records.sort(key=lambda r: r["date"])
    return records


def save_csv(records: List[Dict], output_path: Path):
    """Save parsed OHLCV records to CSV."""
    if not records:
        print("  No data to save.")
        return

    fieldnames = ["date", "open", "high", "low", "close", "volume"]

    output_path.parent.mkdir(parents=True, exist_ok=True)

    with open(output_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(records)

    print(f"  Saved {len(records)} rows -> {output_path}")


def save_json(records: List[Dict], output_path: Path):
    """Save parsed OHLCV records to JSON."""
    output_path.parent.mkdir(parents=True, exist_ok=True)

    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(records, f, indent=2, ensure_ascii=False)

    print(f"  Saved {len(records)} rows -> {output_path}")


def scrape_stock(symbol: str = "CIH", isin: str = None) -> List[Dict]:
    """
    Main scraping function. Fetches and parses OHLCV data for a stock.
    Returns the list of parsed records.
    """
    if isin is None:
        isin = STOCK_ISINS.get(symbol.upper())
        if not isin:
            raise ValueError(f"Unknown symbol '{symbol}'. Known: {list(STOCK_ISINS.keys())}")

    scraper = create_scraper()

    # Fetch OHLCV history
    raw = fetch_ohlcv(scraper, isin)
    records = parse_ohlcv(raw)

    return records


def main():
    print("=" * 60)
    print("  CIH Daily Historical Data Scraper (Medias24 API)")
    print("=" * 60)

    symbol = "CIH"
    isin = STOCK_ISINS[symbol]

    scraper = create_scraper()

    # Step 1: Fetch OHLCV history
    print(f"\n[1] Fetching OHLCV history for {symbol} (ISIN: {isin})...")
    try:
        raw = fetch_ohlcv(scraper, isin)
        print(f"  Received {len(raw)} raw data points")
    except Exception as e:
        print(f"  Error: {e}")
        return

    # Step 2: Parse data
    print("\n[2] Parsing OHLCV data...")
    records = parse_ohlcv(raw)
    print(f"  Parsed {len(records)} valid trading days")

    if not records:
        print("  No valid data parsed. Exiting.")
        return

    # Step 3: Show sample
    print(f"\n[3] Date range: {records[0]['date']} to {records[-1]['date']}")
    print(f"  Sample (first 3 rows):")
    for r in records[:3]:
        print(f"    {r['date']} | O:{r['open']} H:{r['high']} L:{r['low']} C:{r['close']} V:{r['volume']}")
    print(f"  Sample (last 3 rows):")
    for r in records[-3:]:
        print(f"    {r['date']} | O:{r['open']} H:{r['high']} L:{r['low']} C:{r['close']} V:{r['volume']}")

    # Step 4: Fetch real-time info
    print(f"\n[4] Fetching real-time stock info...")
    info = fetch_stock_info(scraper, isin)
    if info:
        # Note: API keys are 'cours', 'min', 'max', 'volume', 'variation'
        print(f"  Current price: {info.get('cours', 'N/A')} MAD")
        print(f"  Day range: {info.get('min', 'N/A')} - {info.get('max', 'N/A')}")
        print(f"  Volume: {info.get('volume', 'N/A')}")
        print(f"  Variation: {info.get('variation', 'N/A')}%")

    # Step 5: Save to files
    output_dir = _ROOT / "data" / "historical"

    print(f"\n[5] Saving to files...")
    save_csv(records, output_dir / f"{symbol}_daily_history.csv")
    save_json(records, output_dir / f"{symbol}_daily_history.json")

    print(f"\n  Done! {len(records)} days of {symbol} history scraped.")
    print(f"  Date range: {records[0]['date']} to {records[-1]['date']}")


if __name__ == "__main__":
    main()
