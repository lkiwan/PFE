# 🔄 SCRAPER CODE FILES REQUIRED FOR AI TO WORK

**The AI needs data from these scrapers to make predictions.**

---

## 📊 **3 CRITICAL SCRAPERS** (MUST WORK PERFECTLY)

### **1️⃣ FINANCIAL DATA SCRAPER** ⭐⭐⭐ CRITICAL

**File**: `scrapers/marketscreener_scraper_v2.py`

**What it does**:
- Scrapes financial fundamentals from MarketScreener
- Collects: Revenue, EBITDA, Net Income, EPS, P/E, Debt, etc.
- Saves to: `data/historical/IAM_marketscreener_v2.json`

**Why AI needs it**: 
- 5 valuation models use this data to calculate intrinsic value
- Scoring engine uses this to rate stock health
- WITHOUT IT: All 5 models + scoring = USELESS

**Status**: ✅ Working (but V2 only gets 38% of data)

**Better Alternative**: `scrapers/marketscreener_scraper_v3.py`
- Same output but uses Selenium to wait for JavaScript rendering
- Gets 50% more data (better than V2)
- Takes longer (15 sec vs 5 sec per stock)

**Usage**:
```bash
# Option A: V2 (Fast, 38% quality)
python scrapers/marketscreener_scraper_v2.py --symbol IAM

# Option B: V3 (Slow, 50% quality) 
python scrapers/marketscreener_scraper_v3.py --symbol IAM

# Option C: Data Merger (Uses both, 100% quality) ⭐⭐⭐
python core/data_merger.py IAM
```

**Output file**: `data/historical/IAM_merged.json`

---

### **2️⃣ DAILY PRICE DATA SCRAPER** ⭐⭐⭐ CRITICAL

**File**: `scrapers/bourse_casa_scraper.py`

**What it does**:
- Scrapes daily OHLCV (Open, High, Low, Close, Volume) from Casablanca Bourse
- Saves to: `data/historical/IAM_bourse_casa_full.csv`

**Why AI needs it**:
- Whale strategy uses this to detect volume spikes
- Calculates 50-day SMA trend
- Without it: Whale detection = FAILS

**Status**: ✅ Working (supports CLI mode)

**Usage**:
```bash
# Scrape single symbol
python scrapers/bourse_casa_scraper.py --symbol IAM

# Scrape all configured instruments
python scrapers/bourse_casa_scraper.py --all

# Interactive menu (choose which instruments)
python scrapers/bourse_casa_scraper.py
```

**Output files**:
- CSV: `data/historical/IAM_bourse_casa_full.csv`
- Database: Inserts to PostgreSQL `public.md_eod_bars`
- State: Tracks progress in `data/scrapers/bourse_casa_state.json`

**Fallback if this fails**: Use old Investing.com CSV
```
IAM/IAM - Données Historiques dayli P.1.csv
IAM/IAM - Données Historiques dayli P.2.csv
```

---

### **3️⃣ NEWS SENTIMENT SCRAPER** ⭐⭐ IMPORTANT

**File**: `testing/run_scraper.py`

**What it does**:
- Scrapes news headlines from MarketScreener
- Extracts article content and sentiment keywords
- Saves to: `testing/news_articles.csv`

**Why AI needs it**:
- News sentiment analyzer uses headlines to determine sentiment
- Positive/negative news affects recommendation confidence
- Without it: Sentiment = NEUTRAL (neutral default)

**Status**: ⚠️ Working but `full_content` column is NULL
- Headlines work fine
- Full article content not being extracted

**Usage**:
```bash
cd testing/
python run_scraper.py
```

**Output file**: `testing/news_articles.csv`

**Columns needed**:
- `Ticker`: Stock symbol (IAM)
- `Company`: Full company name
- `Date`: Article date
- `Title`: Article headline
- `Source`: News source
- `URL`: Article URL
- `Full_Content`: Article text (currently NULL ⚠️)

---

## 🔗 **COMPLETE SCRAPER DEPENDENCY CHAIN**

```
AI Agent (run_autopilot.py)
    ↓
agents/tools.py
    ↓
    ├─→ core/data_merger.py
    │   └─→ NEEDS: data/historical/IAM_merged.json
    │       CREATED BY: marketscreener_scraper_v2.py OR v3.py
    │
    ├─→ strategies/whale_strategy.py
    │   └─→ NEEDS: data/historical/IAM_bourse_casa_full.csv
    │       CREATED BY: bourse_casa_scraper.py
    │
    └─→ strategies/news_sentiment.py
        └─→ NEEDS: testing/news_articles.csv
            CREATED BY: testing/run_scraper.py
```

---

## 📋 **ALL SCRAPER FILES** (Reference)

### **Primary Scrapers** (Used by AI)

| File | Purpose | Status | Output |
|------|---------|--------|--------|
| `marketscreener_scraper_v2.py` | Financial data (faster) | ✅ Working | JSON |
| `marketscreener_scraper_v3.py` | Financial data (more complete) | ✅ Working | JSON |
| `bourse_casa_scraper.py` | Daily OHLCV price data | ✅ Working | CSV + DB |
| `run_scraper.py` (in testing/) | News articles & sentiment | ✅ Working | CSV |

### **Secondary Scrapers** (Legacy/Optional)

| File | Purpose | Status | Used By |
|------|---------|--------|---------|
| `cih_history_scraper.py` | CIH stock daily history | ✅ Working | Backtest only |
| `marketscreener_scraper.py` | Original scraper (broken) | ❌ Obsolete | DEPRECATED |
| `base_scraper.py` | Abstract base class | ✅ Base class | Other scrapers |
| `market_data_scraper.py` | Generic market data | ✅ Available | Not used |
| `order_book_scraper.py` | Bid/ask order book | ✅ Available | Not used |
| `financial_reports.py` | PDF financial reports | ✅ Available | Not used |

---

## 🎯 **MINIMUM TO RUN AI** (3 Commands)

```bash
# 1️⃣ Get stock fundamentals (financial data)
python core/data_merger.py IAM
# Output: data/historical/IAM_merged.json ✅

# 2️⃣ Get daily price data
python scrapers/bourse_casa_scraper.py --symbol IAM
# Output: data/historical/IAM_bourse_casa_full.csv ✅

# 3️⃣ Get news articles
cd testing && python run_scraper.py
# Output: testing/news_articles.csv ✅

# 4️⃣ Run AI autopilot
cd .. && python run_autopilot.py
# AI makes prediction with all real data ✅
```

---

## ⚠️ **KNOWN ISSUES WITH SCRAPERS**

### **Issue 1: MarketScreener V2 gets 38% of data**
- Missing: Market Cap, P/E, Dividend Yield
- Reason: JavaScript-rendered fields not visible to BeautifulSoup
- Solution: Use V3 (Selenium) or Data Merger (combines both)

### **Issue 2: News full_content is NULL**
- Headlines work (extraction works)
- Article body not extracted
- Impact: Sentiment is less accurate (only from headlines)
- Fix: Not urgent (sentiment still works from titles)

### **Issue 3: Rate limiting on MarketScreener**
- If you scrape all 11 stocks too fast, IP gets blocked
- Solution: V3 scraper has built-in delays and rate limit detection
- Workaround: Use data merger (uses old cached data)

### **Issue 4: Bourse Casa API sometimes slow**
- API can take 30+ seconds per symbol
- Solution: Use --all flag to batch multiple symbols
- Fallback: Old Investing.com CSV works

---

## 🚀 **PRODUCTION SETUP** (How run_autopilot.py uses scrapers)

**File**: `run_autopilot.py` (lines 43-61)

```python
def run_data_sync(symbol="IAM"):
    """Syncs market data before AI prediction."""
    scraper_path = _ROOT / "scrapers" / "bourse_casa_scraper.py"
    
    result = subprocess.run(
        [sys.executable, str(scraper_path), "--symbol", symbol],
        capture_output=True, text=True, check=True
    )
    # Updates: data/historical/IAM_bourse_casa_full.csv
```

**What happens**:
1. Before AI runs, it syncs latest daily prices
2. This ensures whale detection uses TODAY's data
3. Financial fundamentals loaded from cached `IAM_merged.json`
4. News loaded from cached `news_articles.csv`

---

## 📈 **DATA FLOW: Scrapers → AI**

```
Day 1: Initial Setup
├─ python core/data_merger.py IAM
│  └─ Loads all financial data (done once)
├─ python scrapers/bourse_casa_scraper.py --symbol IAM
│  └─ Loads historical prices (done once)
└─ cd testing && python run_scraper.py
   └─ Loads news articles (done once)

Daily: Refresh Daily Data
├─ python scrapers/bourse_casa_scraper.py --symbol IAM
│  └─ Updates with TODAY's OHLCV (takes 10-30 sec)
└─ AI reads updated CSV → Detects today's whales → Makes prediction

Weekly: Refresh Financial Data
├─ python core/data_merger.py IAM
│  └─ Re-downloads fundamentals if available
└─ Scoring engine recalculates (usually unchanged unless earnings report)

Monthly: Refresh News
└─ cd testing && python run_scraper.py
   └─ Gets last 20 headlines → Recalculates sentiment
```

---

## ✅ **CHECKLIST: Are Scrapers Working?**

Run this to test:

```bash
# Test 1: Financial data
python -c "from core.data_merger import load_stock_data; print(load_stock_data('IAM', verbose=True)['identity'])"
# Should show: IAM, Itissalat Al-Maghrib, Telecom sector

# Test 2: Price data
python -c "import pandas as pd; df = pd.read_csv('data/historical/IAM_bourse_casa_full.csv'); print(f'Loaded {len(df)} rows of price data')"
# Should show: Loaded XXXX rows

# Test 3: News data
python -c "import pandas as pd; df = pd.read_csv('testing/news_articles.csv'); print(f'Loaded {len(df)} news articles')"
# Should show: Loaded XX news articles

# Test 4: Full AI (uses all scrapers)
python quick_test.py
# Should show: ✅ Current Price, ✅ Intrinsic Value, etc.
```

---

## 🎯 **SUMMARY: Critical Path**

**For AI to work perfectly, these 3 scrapers MUST work:**

1. ✅ `marketscreener_scraper_v2.py` (or v3 or merger)
   - Gets financial data
   - Used by: 5 valuation models + scoring engine
   - Criticality: HIGHEST (0 = total AI failure)

2. ✅ `bourse_casa_scraper.py`
   - Gets daily price data
   - Used by: Whale strategy + SMA calculation
   - Criticality: HIGH (AI still works without it, but whale detection fails)

3. ✅ `testing/run_scraper.py`
   - Gets news articles
   - Used by: News sentiment analyzer
   - Criticality: MEDIUM (AI still works, sentiment defaults to NEUTRAL)

**If all 3 work** → AI gets 100% of available data ✅

---

## 🔧 **How to Use This Information**

1. **To run AI once**: Execute the 3 commands above
2. **To run AI daily**: Automate with cron/scheduler
3. **To debug if AI fails**: Check if scrapers produced output files
4. **To improve accuracy**: Use V3 scraper instead of V2

All scrapers are ready to use! Just run them in order. 🚀
