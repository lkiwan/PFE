# Scraper V3 - Selenium for JavaScript Rendering

## What's Different from V2

**V2** (BeautifulSoup only):
- ❌ Can't see JavaScript-rendered content
- ❌ Market Cap, P/E, Dividend = null
- ✅ Fast (5 seconds total)
- ✅ Gets historical data from tables

**V3** (Selenium + BeautifulSoup):
- ✅ Renders JavaScript like a real browser
- ✅ Gets Market Cap, P/E, Dividend Yield
- ⏱️ Slower (~15-20 seconds per stock)
- ✅ Gets ALL data

---

## Installation

```bash
pip install selenium webdriver-manager
```

---

## Usage

### Single Stock:
```bash
python scrapers/marketscreener_scraper_v3.py --symbol IAM
```

### All Markets:
```bash
python scrapers/marketscreener_scraper_v3.py --all
```

`--all` now builds the full universe from:
1. `data/scrapers/instruments_bourse_casa.json`
2. `data/scrapers/instruments_marketscreener.json`
3. `markets on marketscreener link.md` (or `markets on marketscreener links.md`) when present

### See Browser (debug mode):
```bash
python scrapers/marketscreener_scraper_v3.py --symbol IAM --headful
```

---

## What You'll See

```
🌐 Starting Chrome browser...
📄 Loading https://www.marketscreener.com/quote/stock/...
⏳ Waiting for JavaScript to render (5s)...
✓ Price: 92.1 MAD
✓ Market Cap: 83,514,057,300 MAD
✓ P/E Ratio: 15.5
✓ Dividend Yield: 4.47%
📊 Loading financials...
📈 Loading consensus...
🔒 Closing browser...

✅ Completed IAM
   Price: 92.1 MAD
   Market Cap: 83,514,057,300 MAD
   P/E: 15.5
   Div Yield: 4.47%
   Revenue: 8 years
   EPS: 8 years
   Data Quality: 85% (11/13 fields) ✅
```

---

## Expected Data Quality

| Field | V2 (BeautifulSoup) | V3 (Selenium) |
|-------|-------------------|---------------|
| Price | ✅ 92.1 | ✅ 92.1 |
| Market Cap | ❌ null | ✅ 83.5B |
| P/E Ratio | ❌ null | ✅ 15.5 |
| Div Yield | ❌ null | ✅ 4.47% |
| Revenue (8y) | ✅ | ✅ |
| EPS (8y) | ✅ | ✅ |
| **Quality** | **38%** | **85%+** |

---

## Performance

- **V2**: 5 seconds per stock
- **V3**: 15-20 seconds per stock
- **Trade-off**: Slower but complete data

For 11 stocks:
- V2: ~1 minute total
- V3: ~3-4 minutes total

**Worth it for complete, clean data!** 🎯

---

## Troubleshooting

### Error: Chrome driver not found
```bash
pip install --upgrade webdriver-manager
```

### Error: Chrome not installed
Install Chrome or use Edge:
```python
# In the code, change to Edge:
from selenium.webdriver.edge.service import Service
from webdriver_manager.microsoft import EdgeChromiumDriverManager
service = Service(EdgeChromiumDriverManager().install())
driver = webdriver.Edge(service=service, options=options)
```

### Still getting nulls?
- Check if you have internet connection
- Try `--headful` to see what the browser sees
- MarketScreener might be blocking automated requests (add more delays)

---

## Test It Now!

```bash
python scrapers/marketscreener_scraper_v3.py --symbol IAM
```

Expected: **85%+ data quality** with Market Cap, P/E, and Dividend Yield filled! ✅
