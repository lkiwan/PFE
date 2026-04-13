# MarketScreener Scraper V3 - Explained Like You're a Kid

## The Big Picture: What Does This Script Do?

Imagine you want to collect information about **stocks on the Casablanca Stock Exchange** (price, revenue, profits, etc.) from a website called **MarketScreener.com**. But this website doesn't give you a nice download button. So we need to **pretend to be a human using a web browser**, visit each page, and copy the numbers.

That's exactly what this script does. It opens a **real Chrome browser** (controlled by Python), visits MarketScreener pages, waits for the numbers to appear, reads them, and saves them to JSON files.

---

## Why Not Just BeautifulSoup? Why Selenium?

This is the **#1 most important question**.

### The Problem: JavaScript

When you visit MarketScreener.com in your browser, here's what happens:

```
Step 1: Browser downloads the HTML page (just a skeleton)
Step 2: Browser runs JavaScript code
Step 3: JavaScript FETCHES the real data from MarketScreener's servers
Step 4: JavaScript INJECTS the numbers into the page (P/E ratio, Market Cap, etc.)
```

**BeautifulSoup alone** can only do Step 1. It downloads the skeleton HTML, but the skeleton has **empty boxes** where the numbers should be. BeautifulSoup cannot run JavaScript.

**Example:**

```
What BeautifulSoup sees:          What a real browser sees:
+---------------------+           +---------------------+
| Market Cap: [empty]  |           | Market Cap: 92.5B   |
| P/E Ratio: [empty]   |           | P/E Ratio: 18.3     |
| Revenue: [loading...] |           | Revenue: 36,746M    |
+---------------------+           +---------------------+
```

**Selenium** opens a REAL Chrome browser. It runs JavaScript. It waits for the numbers to appear. THEN we hand the full page (with all numbers filled in) to BeautifulSoup for fast parsing.

So the answer is: **We use BOTH together**.
- **Selenium** = opens the browser, runs JavaScript, waits for content
- **BeautifulSoup** = parses the HTML tables quickly once content is loaded

---

## Why Undetected ChromeDriver? Why Not Regular Selenium?

MarketScreener has **bot protection** (like a security guard at the door). When you use regular Selenium, the website can detect you're a robot because:

```
Regular Selenium leaves fingerprints:
  X navigator.webdriver = true      (normal browsers say "false")
  X Chrome shows "controlled by automation" banner
  X Missing browser plugins/fonts that real users have
  X CDP (Chrome DevTools Protocol) markers visible
```

**MarketScreener sees these fingerprints and blocks you** (returns a "Verify you are human" page or a 403 error).

**`undetected-chromedriver`** patches Chrome to remove ALL these fingerprints:

```
Undetected ChromeDriver:
  OK navigator.webdriver = false     (looks like a real person)
  OK No "controlled by automation" banner
  OK Patches the Chrome binary itself to hide automation markers
  OK Bypasses Cloudflare bot detection
```

Think of it like this: Regular Selenium is wearing a name tag that says "I'M A ROBOT". Undetected ChromeDriver takes off that name tag.

---

## Now Let's Walk Through the Code, Step by Step

### STEP 1: Imports and Configuration (Lines 1-78)

```python
import undetected_chromedriver as uc    # Stealth browser
from selenium import webdriver           # Browser automation
from bs4 import BeautifulSoup           # HTML parsing
```

It also sets up:
- **`CONFIG_PATH`** = where the list of stocks is stored (`instruments_marketscreener.json`)
- **`DATA_DIR`** = where output JSON files go (`data/historical/`)
- **`USER_AGENTS`** = 5 different fake "browser identities" to rotate between, so the website thinks different people are visiting (not the same bot over and over)

---

### STEP 2: The StockData Class (Lines 84-174)

This is the **container** (like a box) where we put all the data we collect. Think of it as an empty form:

```
StockData Form:
  +-------------------------------------+
  | symbol: IAM                          |
  | price: ___                           |
  | market_cap: ___                      |
  | pe_ratio: ___                        |
  | hist_revenue: {2019: ___, 2020: ___} |
  | hist_eps: {2019: ___, 2020: ___}     |
  | ... (20+ fields)                     |
  +-------------------------------------+
```

The `validate()` method at the end checks for crazy values. For example, if P/E ratio is 500, something went wrong, so it throws it away. It also calculates **EPS growth** year-over-year from the EPS history.

---

### STEP 3: `parse_number()` - The Number Reader (Lines 179-242)

This is one of the most important functions. MarketScreener shows numbers in many different formats:

```
"92.52B MAD"    -> 92,520,000,000    (B = Billion)
"36,746M"       -> 36,746,000,000    (M = Million)  
"4,47 %"        -> 4.47              (French format: comma = decimal)
"1.234.567"     -> 1,234,567         (European thousand separators)
"95.40"         -> 95.40             (simple decimal)
```

`parse_number()` handles ALL these cases. It:
1. Detects K/M/B/T suffixes and multiplies accordingly
2. Figures out if a comma means "decimal point" (French: `4,47`) or "thousand separator" (English: `1,234`)
3. Strips currency symbols (MAD, EUR, USD)
4. Rejects garbage (too many digits = probably two numbers glued together)

**Why is this hard?** Because `1.234` could mean `1234` (European thousands) OR `1.234` (decimal). The function uses rules like: if there are multiple dot-groups (`1.234.567`), it's thousand separators.

---

### STEP 4: DOM Extraction Helpers (Lines 260-376)

These functions read the page structure to find data. MarketScreener puts data in tables like:

```html
<table>
  <tr>
    <td>Market Cap</td>      <-- label
    <td>92.52B MAD</td>      <-- value
  </tr>
  <tr>
    <td>P/E Ratio</td>       <-- label
    <td>18.3</td>             <-- value
  </tr>
</table>
```

**`extract_kv_pairs()`** walks through ALL tables, definition lists, and span pairs on the page and collects every (label, value) pair it finds. It's like reading every row of every table and writing down: "Market Cap = 92.52B", "P/E = 18.3", etc.

**`find_in_kv()`** searches those pairs. You give it patterns like "Market Cap" or "P/E" and it returns the matching value.

**`_is_sane_kv()`** is a sanity check - it rejects labels that are too long (probably a paragraph, not a label) or values with too many digits (probably two numbers glued together).

---

### STEP 5: The SeleniumScraper Class (Lines 382-477)

This is where the browser gets set up.

**`__init__()` - Starting Chrome:**

```
1. Pick a random User-Agent (fake browser identity)
2. Create a temporary folder for Chrome's profile
3. Try undetected-chromedriver first (stealthy)
4. If UC not installed, fall back to regular Selenium (less stealthy)
5. Set page load timeout to 60 seconds
```

The Windows-specific fixes are important:
- **WinError 10053**: On Windows, UC tries to re-download the driver every time. If your firewall blocks it, it crashes. The code checks if a cached driver already exists and uses that.
- **WinError 6**: UC has a bug where closing Chrome on Windows throws an error. The code wraps the destructor to silently ignore it.

---

### STEP 6: `_wait_and_get_soup()` (Lines 480-490)

```python
def _wait_and_get_soup(self, wait_seconds=5):
    WebDriverWait(self.driver, 15).until(
        EC.presence_of_element_located((By.TAG_NAME, "body"))
    )
    time.sleep(wait_seconds)
    return BeautifulSoup(self.driver.page_source, 'lxml')
```

This is the **bridge between Selenium and BeautifulSoup**:
1. Wait up to 15 seconds for the page body to exist
2. Sleep extra seconds for JavaScript widgets to populate
3. Grab the FULL rendered HTML (with JavaScript-filled numbers)
4. Hand it to BeautifulSoup for fast parsing

---

### STEP 7: `_parse_year_tables()` (Lines 505-584)

This is the **workhorse** for historical data. MarketScreener shows financial data in tables like:

```
              | 2019    | 2020    | 2021    | 2022    | 2023
--------------+---------+---------+---------+---------+-----
Revenue       | 36,517  | 35,834  | 35,784  | 36,746  | 37,002
Net Income    | 5,826   | 5,576   | 5,622   | 5,987   | 6,038
EPS           | 6.63    | 6.34    | 6.40    | 6.81    | 6.87
  % Change    |         | -4.4%   | +0.9%   | +6.4%   | +0.9%
```

The function:
1. Finds the header row and identifies which columns are years (2019, 2020, etc.)
2. For each data row, matches the label against regex patterns (e.g., `revenue|sales|turnover`)
3. Reads the number from each year column
4. Stores it in the right dictionary (e.g., `data.hist_revenue["2023"] = 37002`)

The **`growth_map`** handles those "% Change" sub-rows that appear under EPS - they don't have their own label, they inherit from the row above.

---

### STEP 8: The 6 Page Scrapers

The scraper visits **6 different pages** for each stock:

```
Page 1: MAIN PAGE          -> Price, Market Cap, P/E, P/B, Dividend, 52w High/Low, Volume, Consensus
Page 2: FINANCES           -> Revenue, Net Income, EPS, EBITDA, Debt, Cash, Equity, Margins, ROE, ROCE (8 years)
Page 3: RATIOS             -> Gross/Net/EBIT/EBITDA Margins, ROE, ROCE (fills gaps from Page 2)
Page 4: CASH FLOW          -> Operating Cash Flow, Free Cash Flow, CapEx (fills gaps)
Page 5: VALUATION          -> Price-to-Book, EV/EBITDA, Dividend Per Share (fills gaps)
Page 6: CONSENSUS          -> Target Price, Number of Analysts, Buy/Hold/Sell Rating
```

Each page scraper:
1. Navigates to the URL
2. Waits for JavaScript
3. Parses with BeautifulSoup
4. Extracts the specific data fields

**Why 6 pages?** Because MarketScreener splits financial data across multiple pages. No single page has everything we need.

---

### STEP 9: Rate Limit Protection (Lines 1016-1064)

MarketScreener limits how many pages you can view. When you hit the limit:

```
Normal page:                  Rate-limited page:
+---------------------+       +-------------------------+
| IAM Stock Data      |       | WARNING Verify you are  |
| Price: 95.40 MAD    |       | human                   |
| ...                 |       | [Cloudflare challenge]  |
+---------------------+       +-------------------------+
```

**`looks_rate_limited()`** checks if the page shows these warning signs (like "just a moment", "verify you are human", "access denied").

**`hard_clear_session()`** is the fix - it:
1. Deletes all cookies
2. Clears localStorage and sessionStorage
3. Clears browser cache via Chrome DevTools Protocol
4. Now MarketScreener thinks you're a new visitor

---

### STEP 10: URL Discovery (Lines 1069-1115)

Each stock has a unique MarketScreener URL like:
```
/quote/stock/ITISSALAT-AL-MAGHRIB-IAM--1408717/
```

But we only know the stock symbol "IAM". So **`discover_url_code()`**:
1. Searches MarketScreener for the company name
2. Looks at the search results for links matching `/quote/stock/SLUG/`
3. Scores each result (does it contain "IAM"? Is it from Morocco?)
4. Returns the best match

---

### STEP 11: The Main Orchestrator - `scrape()` (Lines 1125-1158)

```python
def scrape(self, symbol, url_code):
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
        scrape_fn(data, url_code)           # Visit page and extract data
        if self.looks_rate_limited():       # Got blocked?
            self._handle_rate_limit()       # Clear cookies and retry once
        time.sleep(random.uniform(1.5, 3))  # Random delay between pages
    
    data.validate()
    return data
```

The random delay (`1.5-3 seconds`) between pages makes us look more human. A robot would instantly jump between pages; a human takes time to read.

---

### STEP 12: The `main()` Function and Batch Processing (Lines 1581-1781)

This is what runs when you type `python scrapers/marketscreener_scraper_v3.py`.

**Single stock mode:**
```bash
python scrapers/marketscreener_scraper_v3.py --symbol IAM
```
Opens one Chrome, scrapes one stock, saves one JSON file.

**All stocks mode (parallel):**
```bash
python scrapers/marketscreener_scraper_v3.py --all --workers 3
```
Opens 3 Chrome browsers, splits the stock list into 3 groups, each Chrome handles its group simultaneously.

**Resume mode:**
```bash
python scrapers/marketscreener_scraper_v3.py --all --resume
```
Skips stocks that were already scraped in the last 12 hours. Useful when the scraper crashed halfway through - you don't need to redo everything.

---

## Flow Diagram: From Run to Output

```
YOU RUN: python scrapers/marketscreener_scraper_v3.py --symbol IAM
|
+- 1. SETUP
|   +- Load instrument list from instruments_marketscreener.json
|   +- Merge with Casablanca stock list + links markdown file
|   +- Find IAM in the list -> get URL slug
|
+- 2. START CHROME (undetected-chromedriver)
|   +- Pick random User-Agent
|   +- Create temp profile folder
|   +- Launch headless Chrome with stealth patches
|   +- Set 60-second page timeout
|
+- 3. SCRAPE 6 PAGES (one by one)
|   |
|   +- PAGE 1: /quote/stock/ITISSALAT-AL-MAGHRIB-IAM--1408717/
|   |   +- Selenium loads page -> waits 5s for JavaScript
|   |   +- BeautifulSoup parses HTML -> extracts KV pairs
|   |   +- Finds: Price=95.40, Market Cap=92.5B, P/E=18.3...
|   |   +- Check: rate limited? -> No -> continue
|   |   +- Sleep 1.5-3 seconds (look human)
|   |
|   +- PAGE 2: .../finances/
|   |   +- Selenium loads -> waits 3s
|   |   +- _parse_year_tables() reads year columns
|   |   +- Finds: Revenue{2019:36517, 2020:35834...}, EPS{...}
|   |   +- Check: rate limited? -> No -> continue
|   |   +- Sleep 1.5-3 seconds
|   |
|   +- PAGE 3: .../finances-ratios/
|   |   +- Fills gaps: Gross Margin, Net Margin, ROE, ROCE
|   |   +- Sleep...
|   |
|   +- PAGE 4: .../finances-cash-flow-statement/
|   |   +- Fills gaps: OCF, FCF, CapEx
|   |   +- Sleep...
|   |
|   +- PAGE 5: .../valuation/
|   |   +- Fills gaps: P/B, EV/EBITDA, DPS
|   |   +- Sleep...
|   |
|   +- PAGE 6: .../consensus/
|       +- Finds: Target Price, Analysts count, BUY/HOLD/SELL
|       +- Done with pages
|
+- 4. VALIDATE DATA
|   +- P/E > 300? -> throw away (suspicious)
|   +- Target price 100x the current price? -> throw away
|   +- Calculate EPS growth % for missing years
|
+- 5. SAVE TO JSON
|   +- Convert StockData -> dictionary -> JSON
|   +- Write to: data/historical/IAM_marketscreener_v3.json
|
+- 6. PRINT SUMMARY
|   +- Price: 95.40 MAD
|   +- Revenue: 8 years, EPS: 8 years...
|   +- Data Quality: 50% (14/28 fields)
|
+- 7. CLOSE CHROME
    +- driver.quit()

TOTAL TIME: ~30-60 seconds for 1 stock
            ~30-60 MINUTES for all 75 stocks (with delays)
```

---

## Why Does It Take So Long?

Here's the time breakdown for scraping **1 stock**:

| Step | Time | Why |
|------|------|-----|
| Start Chrome | 3-5 sec | Browser needs to launch |
| Load Page 1 + wait JS | 5-8 sec | Network + JavaScript rendering |
| Load Page 2 + wait JS | 3-6 sec | Same |
| Load Page 3 + wait JS | 3-6 sec | Same |
| Load Page 4 + wait JS | 3-6 sec | Same |
| Load Page 5 + wait JS | 3-6 sec | Same |
| Load Page 6 + wait JS | 3-6 sec | Same |
| Random delays between pages | 9-18 sec | **Must look human** |
| **Total per stock** | **~30-60 sec** | |

For **75 stocks** with delays between instruments (6-14 seconds each):

```
75 stocks x ~45 sec each = ~56 minutes
+ 74 inter-stock delays x ~10 sec = ~12 minutes
+ Browser restarts every 15 stocks = ~5 minutes
= TOTAL: ~60-90 minutes for all stocks
```

**The delays are intentional.** Without them, MarketScreener blocks you after 10-15 pages.

With `--workers 3`, you can cut this to ~25-30 minutes (3 Chrome browsers working in parallel).

---

## Known Errors / Issues Still to Fix

1. **Data Quality is only ~50%** - The scraper gets about 14 out of 28 possible data fields. Some fields (like Gross Margin, Operating Cash Flow) are on pages where MarketScreener uses different HTML structure that the parser misses. That's why the **data_merger.py** exists - it combines V3 data with V2 data to get closer to 100%.

2. **Rate limiting** - MarketScreener limits views. After scraping ~15-20 stocks, you may get blocked. The script handles this (clears cookies, restarts Chrome), but sometimes it still fails. The `--resume` flag lets you restart where you left off.

3. **French vs English format** - MarketScreener sometimes shows the page in French (depending on your IP/cookies), so numbers look like `4,47` instead of `4.47`. The `parse_number()` function handles this, but edge cases can slip through.

4. **Some fields come back empty** - Fields like `hist_gross_margin` and `hist_ocf` are often empty because they're in JavaScript widgets that take longer to render, or they're in a different table format the parser doesn't expect.

5. **Windows-specific Chrome bugs** - WinError 6 and WinError 10053 are patched with workarounds, but Chrome/UC updates can break these fixes at any time.

6. **No retry for individual pages** - If one of the 6 pages fails (but not with a rate limit), the data from that page is just missing. The scraper doesn't retry individual pages, only full-stock retries on rate limits.
