"""
Unified News Scraper for MarketScreener
========================================
Fetches news articles from MarketScreener for Casablanca stocks.
Exports all data to CSV format.

Usage:
    python run_scraper.py                  # Interactive picker
    python run_scraper.py --symbol IAM     # Single stock
    python run_scraper.py --all            # All stocks with url_code

Output:
    news_articles.csv - CSV file with date, title, source, URL, and full article content
"""

import asyncio
import csv
import sys
import os
import argparse
import time
import random
from datetime import datetime

sys.path.insert(0, '.')

from scraper import NewsScraper, StockData, STOCKS, AsyncHTTPClient


def _safe_print(text: str) -> None:
    try:
        print(text)
    except UnicodeEncodeError:
        print(text.encode(errors='replace').decode('ascii', errors='replace'))


async def scrape_one(scraper, symbol, stock_config, fetch_full=False):
    """Scrape news for one stock. Returns list of row tuples."""
    stock_data = StockData()
    await scraper.scrape(stock_config, stock_data, fetch_full_articles=fetch_full)

    rows = []
    for article in stock_data.news.articles:
        rows.append((
            symbol,
            stock_config['full_name'],
            article.date or '',
            article.title or '',
            article.source or '',
            article.url or '',
            article.full_content or '',
            datetime.now().strftime('%Y-%m-%d'),
        ))
    return rows


async def main():
    parser = argparse.ArgumentParser(description='MarketScreener News Scraper')
    parser.add_argument('--symbol', help='Stock symbol (e.g. IAM)')
    parser.add_argument('--all', action='store_true', help='Scrape news for all stocks')
    parser.add_argument('--full', action='store_true',
                        help='Also fetch full article content (slower)')
    parser.add_argument('--start-from', help='Symbol to start/resume from (e.g. JET) when using --all')
    args = parser.parse_args()

    if not STOCKS:
        print("No stocks with MarketScreener url_code found.")
        print("Run the MarketScreener scraper first to populate url_codes.")
        sys.exit(1)

    # --- Resolve targets ---
    symbols_sorted = sorted(STOCKS.keys())

    if args.symbol:
        sym = args.symbol.upper()
        if sym not in STOCKS:
            print(f"Symbol {sym} not found in MarketScreener config.")
            print(f"Available: {', '.join(symbols_sorted)}")
            sys.exit(1)
        targets = [sym]

    elif args.all:
        targets = symbols_sorted
        if args.start_from:
            start_sym = args.start_from.upper()
            if start_sym in targets:
                targets = targets[targets.index(start_sym):]
            else:
                print(f"Symbol {start_sym} not found. Cannot start from it.")
                sys.exit(1)

    else:
        # Interactive picker
        _safe_print(f"\nMarketScreener News Scraper")
        _safe_print("=" * 55)
        _safe_print(f"  [0] ALL ({len(symbols_sorted)} stocks)")
        for i, sym in enumerate(symbols_sorted, 1):
            name = STOCKS[sym]['full_name']
            _safe_print(f"  [{i}] {sym:5s} - {name}")

        try:
            choice = input("\nSelect number: ").strip()
            if not choice:
                sys.exit(0)
            choice = int(choice)
        except (ValueError, KeyboardInterrupt):
            print("Cancelled.")
            sys.exit(0)

        if choice == 0:
            targets = symbols_sorted
        elif 1 <= choice <= len(symbols_sorted):
            targets = [symbols_sorted[choice - 1]]
        else:
            print("Invalid selection.")
            sys.exit(1)

    # --- Scrape ---
    _safe_print(f"\n{'='*60}")
    _safe_print(f"MarketScreener News Scraper - {len(targets)} stock(s)")
    _safe_print(f"{'='*60}")

    http_client = AsyncHTTPClient()
    scraper = NewsScraper(http_client)
    all_rows = []

    try:
        for idx, sym in enumerate(targets, 1):
            config = STOCKS[sym]
            _safe_print(f"\n[{idx}/{len(targets)}] {sym} - {config['full_name']}")

            # Rotate session every 10 items to prevent MarketScreener blocks
            if idx % 10 == 0:
                await http_client.close()
                http_client = AsyncHTTPClient()
                scraper = NewsScraper(http_client)
                _safe_print("  [Rotated HTTP Session to avoid blocks]")

            rows = await scrape_one(scraper, sym, config, fetch_full=args.full)
            all_rows.extend(rows)
            _safe_print(f"  Found {len(rows)} articles")

            if idx < len(targets):
                delay = random.uniform(3, 7) if len(rows) > 0 else random.uniform(6, 10)
                time.sleep(delay)

    except KeyboardInterrupt:
        _safe_print("\n\nInterrupted by user.")
    finally:
        await http_client.close()

    if not all_rows:
        _safe_print("\nNo articles found.")
        return

    # --- Deduplicate: load existing CSV, merge, deduplicate by URL ---
    csv_file = 'news_articles.csv'
    header = ['Ticker', 'Company', 'Date', 'Title', 'Source', 'URL', 'Full_Content', 'Scraped_At']
    existing_rows = []
    if os.path.exists(csv_file):
        try:
            with open(csv_file, 'r', encoding='utf-8') as f:
                reader = csv.reader(f)
                old_header = next(reader, None)
                for row in reader:
                    # Handle old format (7 columns) by adding empty Scraped_At
                    if len(row) == 7:
                        row.append('')
                    existing_rows.append(tuple(row))
        except Exception as e:
            _safe_print(f"  Warning: could not read existing CSV: {e}")

    # Deduplicate by URL (column index 5)
    seen_urls = {row[5] for row in existing_rows if len(row) > 5 and row[5]}
    new_rows = [row for row in all_rows if row[5] and row[5] not in seen_urls]
    combined = existing_rows + new_rows

    with open(csv_file, 'w', newline='', encoding='utf-8') as f:
        writer = csv.writer(f)
        writer.writerow(header)
        writer.writerows(combined)

    _safe_print(f"\n  Existing articles: {len(existing_rows)}")
    _safe_print(f"  New articles:      {len(new_rows)}")
    _safe_print(f"  Total saved:       {len(combined)}")

    # --- Summary ---
    _safe_print(f"\n{'='*60}")
    _safe_print("SUMMARY")
    _safe_print(f"{'='*60}")
    _safe_print(f"  Stocks scraped: {len(targets)}")
    _safe_print(f"  Total articles: {len(all_rows)}")
    _safe_print(f"  Output file:    {csv_file}")

    # Per-stock breakdown
    from collections import Counter
    counts = Counter(r[0] for r in all_rows)
    _safe_print(f"\n  Per stock:")
    for sym in targets:
        _safe_print(f"    {sym:5s}: {counts.get(sym, 0)} articles")

    if all_rows:
        _safe_print(f"\n  Latest articles:")
        for row in all_rows[:5]:
            ticker, _, date, title, *_ = row
            title_short = title[:55] if title else 'N/A'
            date_short = date[:10] if date else 'N/A'
            _safe_print(f"    [{ticker}] [{date_short}] {title_short}...")

    _safe_print(f"\n{'='*60}")
    _safe_print("Done!")
    _safe_print(f"{'='*60}")


if __name__ == '__main__':
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n\nScraper interrupted by user.")
    except Exception as e:
        print(f"Fatal error: {e}")
        import traceback
        traceback.print_exc()
