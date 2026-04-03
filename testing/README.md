# MarketScreener News Scraper

Simple, consolidated news scraper for IAM (Maroc Telecom) from MarketScreener.

## Quick Start

```bash
python run_scraper.py
```

This will:
1. Fetch IAM news articles from MarketScreener
2. Extract full article content from each article page
3. Export everything to `news_articles.csv`

## Output

**File:** `news_articles.csv`

Columns:
- **Ticker**: IAM
- **Company**: Itissalat Al-Maghrib (IAM) S.A.
- **Date**: Publication date
- **Title**: Article headline
- **Source**: News source (Reuters, S&P Capital IQ, etc.)
- **URL**: Link to article page
- **Full_Content**: Complete article body text

## Requirements

- Python 3.8+
- aiohttp
- beautifulsoup4

Install dependencies:
```bash
pip install -r requirements.txt
```

## Files

- **run_scraper.py** - Main unified scraper (entry point)
- **scraper.py** - Core scraper infrastructure
- **config.py** - Configuration files
- **requirements.txt** - Python dependencies
- **news_articles.csv** - Output file with scraped articles

## Usage

### Basic Run
```bash
python run_scraper.py
```

### Output Examples

First 3 rows of news_articles.csv:
```
Ticker,Company,Date,Title,Source,URL,Full_Content
IAM,Itissalat Al-Maghrib (IAM) S.A.,2026-03-11,Itissalat Al Maghrib IAM S A : MAGHRIB - The AMMC appro...,Unknown,/news/slug,"Full article text here..."
IAM,Itissalat Al-Maghrib (IAM) S.A.,2026-02-18,Maroc Telecom reports $760mn profit for 2025...,Reuters,/news/slug,"Maroc Telecom, part of IAM group..."
```

## Performance

- First run (with full content extraction): ~10-30 seconds
- Includes up to 20 IAM news articles
- Each article page is individually fetched for full content

## Features

✓ Full article content extraction using JSON-LD schema  
✓ Automatic date parsing and formatting  
✓ Source attribution  
✓ CSV export with all data  
✓ Error handling and logging  
✓ Clean, single-entry-point design  

## Troubleshooting

**No articles found?**
- Check internet connection
- MarketScreener website structure may have changed

**Slow extraction?**
- Normal behavior - fetches each article individually
- This is why it takes 10-30 seconds

**Empty full_content column?**
- Some articles may not have JSON-LD structured data
- Falls back to alternative content selectors

## Support

For issues, check the CSV output and error logs in console output.

---

**Version:** 1.0  
**Stock:** IAM (Maroc Telecom)  
**Source:** MarketScreener.com  
