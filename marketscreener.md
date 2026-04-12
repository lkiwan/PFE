# How `marketscreener_scraper_v3.py` Works — Step by Step

## What is this code?

Imagine MarketScreener.com is like a **newspaper** that publishes financial data about companies. This code is like a **robot that reads the newspaper for you**, copies the important numbers, and saves them in a file on your computer.

Since the newspaper is a website, the robot needs a **web browser** (Chrome) to open the pages — just like you would.

---

## The Schema

```
YOU run the command
        |
        v
+--------------------------------------------------+
|  STEP 1: SETUP                                   |
|  "Which company do you want?"                    |
|  -> You pick IAM (Maroc Telecom)                 |
|  -> Robot opens Chrome browser (invisible)       |
+----------------------+---------------------------+
                       v
+--------------------------------------------------+
|  STEP 2: VISIT 6 PAGES (one by one)              |
|                                                  |
|  Page 1: MAIN PAGE                               |
|    -> Gets: Price, Market Cap, P/E, Yield        |
|                                                  |
|  Page 2: FINANCES PAGE                           |
|    -> Gets: Revenue, Net Income, EPS,            |
|       EBITDA, FCF, Debt (8 years)                |
|                                                  |
|  Page 3: RATIOS PAGE                             |
|    -> Gets: ROE, ROCE, Margins                   |
|       (8 years)                                  |
|                                                  |
|  Page 4: CASH FLOW PAGE                          |
|    -> Gets: Operating Cash Flow,                 |
|       Cash, Equity                               |
|                                                  |
|  Page 5: VALUATION PAGE                          |
|    -> Gets: Price/Book (PBR),                    |
|       Dividend Per Share                         |
|                                                  |
|  Page 6: CONSENSUS PAGE                          |
|    -> Gets: BUY/HOLD/SELL,                       |
|       Target Price, Analyst count                |
|                                                  |
|  Between each page:                              |
|  +---------------------------------------------+ |
|  |  Wait 1.5-3 seconds (be polite)             | |
|  |  Check: "Am I blocked?"                     | |
|  |    NO  -> continue to next page             | |
|  |    YES -> clear cookies -> wait 10-20s      | |
|  |            -> retry same page               | |
|  +---------------------------------------------+ |
+----------------------+---------------------------+
                       v
+--------------------------------------------------+
|  STEP 3: VALIDATE                                |
|  "Does the data make sense?"                     |
|  -> P/E > 300? Remove it (suspicious)            |
|  -> Target price 100x the price? Remove it       |
|  -> Calculate EPS growth from EPS history         |
+----------------------+---------------------------+
                       v
+--------------------------------------------------+
|  STEP 4: SAVE                                    |
|  Save everything to:                             |
|  data/historical/IAM_marketscreener_v3.json      |
|  -> Print summary: quality 93% (26/28 fields)    |
+----------------------+---------------------------+
                       v
+--------------------------------------------------+
|  STEP 5: CLOSE                                   |
|  Close Chrome browser                            |
+--------------------------------------------------+
```

---

## Step-by-Step Explanation

### STEP 1 — Setup: "Who do I look up?"

When you run the command, the code first loads a list of 80 Moroccan companies (from `instruments_marketscreener.json`). You pick one — for example, IAM. The code then opens an **invisible Chrome browser** (you don't see it, but it's running in the background). This is called "headless" mode.

### STEP 2 — Visit 6 pages: "Read the newspaper"

The robot visits 6 different pages on MarketScreener, one after another. Each page has different information:

- **Page 1 (Main)**: Like the front page of the newspaper. Shows today's price (96 MAD), how big the company is (84 billion MAD), and basic ratios.

- **Page 2 (Finances)**: Like the annual report section. Shows 8 years of revenue, profit, earnings per share, debt, etc. The code reads the tables row by row, matching labels like "Net sales" or "EBITDA" to know which number is which.

- **Page 3 (Ratios)**: Shows profitability metrics — how efficiently the company uses money (ROE = Return on Equity, margins = what % of revenue becomes profit).

- **Page 4 (Cash Flow)**: Shows how much real cash the company generates (Operating Cash Flow), how much cash it has, and how much the company is worth (Equity).

- **Page 5 (Valuation)**: Shows if the stock is expensive or cheap compared to its book value (PBR = Price to Book Ratio), and dividend per share.

- **Page 6 (Consensus)**: Shows what professional analysts think — should you BUY, HOLD, or SELL? And what price they think the stock should reach.

**Between each page**, the robot:

- **Waits 1.5-3 seconds** — like a polite person who doesn't rush. If you click too fast, the website thinks you're a robot and blocks you.
- **Checks if blocked** — the website might show "Access Denied" or "Verify you are human". If blocked:
  - Clears all cookies (like erasing the website's memory of you)
  - Waits 10-20 seconds
  - Tries the same page again

### STEP 3 — Validate: "Does this make sense?"

Before saving, the code checks for suspicious values:

- If P/E ratio is over 300 -> probably wrong, remove it
- If target price is 100x the current price -> probably wrong, remove it
- Calculates EPS growth automatically from the EPS history

### STEP 4 — Save: "Write it down"

All the collected data is saved to a JSON file (`IAM_marketscreener_v3.json`). JSON is just a text file that organizes data with labels, like:

```json
{
  "price": 96.0,
  "pe_ratio": 15.7,
  "hist_revenue": { "2021": 35790, "2022": 35731, "...": "..." }
}
```

The code also prints a quality score — 93% means 26 out of 28 possible fields were found.

### STEP 5 — Close: "Done, close the browser"

---

## How it reads a table (the `_parse_year_tables` helper)

This is the core trick. MarketScreener tables look like this:

```
                    | 2021   | 2022   | 2023   | 2024
--------------------+--------+--------+--------+-------
Net sales           | 35,790 | 35,731 | 36,786 | 36,699
EBITDA              | 18,589 | 18,492 | 19,369 | 19,197
Net income          |  6,008 |  2,750 |  5,283 |  1,801
```

The code:

1. Finds the **header row** -> extracts the years (2021, 2022, 2023...)
2. For each **data row**, reads the first cell (the label: "Net sales")
3. Matches the label against a list of patterns: "Does this label contain 'revenue' or 'sales'?"
4. If it matches -> reads the numbers from each year column and saves them

It's like telling the robot: _"If you see a row that says 'Net sales', copy all the numbers and label them as revenue."_

---

## How it handles being blocked

```
Robot visits page
        |
        v
   Is page showing       YES     Clear cookies
   "Access Denied"?  ----------> + localStorage
        |                         + cache
        | NO                      |
        v                         v
   Read the data            Wait 10-20 sec
   Continue                       |
                                  v
                            Retry same page
                                  |
                                  v
                            Still blocked?
                           /            \
                         NO              YES
                          |               |
                          v               v
                     Continue        Give up,
                     normally        save what
                                    we have
```

---

## How to run it

```bash
# Scrape one company
python scrapers/marketscreener_scraper_v3.py --symbol IAM

# Scrape all 80 companies
python scrapers/marketscreener_scraper_v3.py --all

# Show the browser while scraping (for debugging)
python scrapers/marketscreener_scraper_v3.py --symbol IAM --headful

# Save HTML pages for inspection
python scrapers/marketscreener_scraper_v3.py --symbol IAM --debug
```

---

## What data it collects (28 fields total)

| Category                    | Fields                                                | Source Page          |
| --------------------------- | ----------------------------------------------------- | -------------------- |
| **Price & Market**          | price, market_cap, volume, 52w high/low               | Main                 |
| **Valuation Ratios**        | P/E, P/B (PBR), dividend yield                        | Main + Valuation     |
| **Analyst Opinion**         | consensus (BUY/HOLD/SELL), target price, num analysts | Consensus            |
| **Income (8 years)**        | revenue, EBITDA, net income, EPS, EPS growth          | Finances             |
| **Cash Flow (8 years)**     | FCF, OCF, CAPEX                                       | Finances + Cash Flow |
| **Balance Sheet (8 years)** | debt, cash, equity                                    | Finances + Cash Flow |
| **Profitability (8 years)** | net margin, EBIT margin, EBITDA margin, gross margin  | Ratios               |
| **Returns (8 years)**       | ROE, ROCE                                             | Ratios               |
| **Dividends (8 years)**     | dividend per share, EV/EBITDA                         | Finances + Valuation |
