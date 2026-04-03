"""
Unified News Scraper for MarketScreener
========================================
Fetches IAM (Maroc Telecom) news articles from MarketScreener with full article content.
Exports all data to CSV format.

Usage:
    python run_scraper.py

Output:
    news_articles.csv - CSV file with date, title, source, URL, and full article content
"""

import asyncio
import csv
import sys
from datetime import datetime
sys.path.insert(0, '.')

from scraper import NewsScraper, StockData, STOCKS, AsyncHTTPClient


async def main():
    """Main scraper function."""
    print("=" * 80)
    print("MarketScreener News Scraper - IAM (Maroc Telecom)")
    print("=" * 80)
    
    http_client = AsyncHTTPClient()
    scraper = NewsScraper(http_client)
    
    try:
        # Fetch IAM articles with full content
        print("\n[1] Fetching IAM articles with full content extraction...")
        print("    (This may take 10-30 seconds due to individual article fetches)\n")
        
        stock_config = STOCKS['IAM']
        stock_data = StockData()
        
        await scraper.scrape(
            stock_config, 
            stock_data, 
            fetch_full_articles=True
        )
        
        print(f"\n✓ Found {len(stock_data.news.articles)} articles")
        
        # Export to CSV
        print("\n[2] Exporting to CSV...")
        csv_file = 'news_articles.csv'
        
        with open(csv_file, 'w', newline='', encoding='utf-8') as f:
            writer = csv.writer(f)
            writer.writerow([
                'Ticker',
                'Company', 
                'Date',
                'Title',
                'Source',
                'URL',
                'Full_Content'
            ])
            
            for article in stock_data.news.articles:
                writer.writerow([
                    'IAM',
                    stock_config['full_name'],
                    article.date or '',
                    article.title or '',
                    article.source or '',
                    article.url or '',
                    article.full_content or ''
                ])
        
        print(f"✓ Exported to {csv_file}")
        
        # Print summary
        print("\n" + "=" * 80)
        print("SUMMARY")
        print("=" * 80)
        print(f"\nStock: IAM - {stock_config['full_name']}")
        print(f"Total Articles: {len(stock_data.news.articles)}")
        print(f"Output File: {csv_file}")
        
        if stock_data.news.articles:
            print("\nLatest Articles:")
            for i, article in enumerate(stock_data.news.articles[:5], 1):
                date_str = article.date[:10] if article.date else 'N/A'
                title = article.title[:60] if article.title else 'N/A'
                has_content = '✓' if article.full_content else '✗'
                print(f"  {i}. [{date_str}] {title}... [{has_content}]")
        
        print("\n" + "=" * 80)
        print("✓ Done!")
        print("=" * 80)
        
    except KeyError as e:
        print(f"✗ Error: Stock ticker not found: {e}")
        print(f"   Available stocks: {list(STOCKS.keys())}")
    except Exception as e:
        print(f"✗ Error: {e}")
        import traceback
        traceback.print_exc()
    finally:
        await http_client.close()


if __name__ == '__main__':
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n\nScraper interrupted by user.")
    except Exception as e:
        print(f"Fatal error: {e}")
        import traceback
        traceback.print_exc()
