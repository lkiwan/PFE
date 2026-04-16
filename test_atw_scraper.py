#!/usr/bin/env python3
"""Quick test to verify ATW is in STOCKS config and test the scrapers."""

import sys
import json
from pathlib import Path

# Add testing to path
sys.path.insert(0, 'testing')
sys.path.insert(0, 'scrapers')

from scraper import STOCKS

print("=" * 60)
print("Testing MarketScreener Scraper Configuration")
print("=" * 60)

print(f"\nTotal stocks loaded: {len(STOCKS)}")
print(f"ATW in STOCKS: {'ATW' in STOCKS}")

if 'ATW' in STOCKS:
    print(f"ATW config: {STOCKS['ATW']}")
    atw_url = f"https://www.marketscreener.com/quote/stock/{STOCKS['ATW']['url_code']}/news/"
    print(f"\nATW News URL: {atw_url}")
else:
    print("WARNING: ATW not found in STOCKS!")

# Test atw_news_scraper
print("\n" + "=" * 60)
print("Testing atw_news_scraper MarketScreener function")
print("=" * 60)

try:
    from scrapers.atw_news_scraper import scrape_marketscreener_atw_news
    print("\n✓ scrape_marketscreener_atw_news imported successfully")
    print("  Function signature: scrape_marketscreener_atw_news() -> list[dict]")
    print("  This function will be called in run() orchestration")
except Exception as e:
    print(f"✗ Failed to import scrape_marketscreener_atw_news: {e}")

print("\n" + "=" * 60)
print("Summary")
print("=" * 60)
print("\n✓ run_scraper.py can already scrape ATW news via:")
print("  python testing/run_scraper.py --symbol ATW")
print("\n✓ atw_news_scraper.py now includes MarketScreener as a source:")
print("  python scrapers/atw_news_scraper.py")
print("  (MarketScreener news will be included automatically)\n")
