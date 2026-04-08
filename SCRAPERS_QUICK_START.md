# 🎯 QUICK REFERENCE: 3 SCRAPERS THE AI NEEDS

## **SCRAPER 1: Financial Data** ⭐⭐⭐ CRITICAL

**File**: `scrapers/marketscreener_scraper_v2.py` (or v3)  
**Collects**: Revenue, EPS, P/E, Debt, EBITDA, Margins, etc.  
**Saves to**: `data/historical/IAM_marketscreener_v2.json`  
**Used by**: 5 valuation models + scoring engine  
**Status**: ✅ Working

**Run it**:
```bash
python scrapers/marketscreener_scraper_v2.py --symbol IAM
```

**Or better** (100% complete data):
```bash
python core/data_merger.py IAM
```

**Output**: `data/historical/IAM_merged.json`

---

## **SCRAPER 2: Daily Price Data** ⭐⭐⭐ CRITICAL

**File**: `scrapers/bourse_casa_scraper.py`  
**Collects**: Daily OHLCV (Open, High, Low, Close, Volume)  
**Saves to**: `data/historical/IAM_bourse_casa_full.csv`  
**Used by**: Whale strategy + SMA trend detection  
**Status**: ✅ Working

**Run it**:
```bash
python scrapers/bourse_casa_scraper.py --symbol IAM
```

**Output**: `data/historical/IAM_bourse_casa_full.csv`

---

## **SCRAPER 3: News Articles** ⭐⭐ IMPORTANT

**File**: `testing/run_scraper.py`  
**Collects**: News headlines, dates, sources  
**Saves to**: `testing/news_articles.csv`  
**Used by**: News sentiment analyzer  
**Status**: ✅ Working (but full_content is NULL)

**Run it**:
```bash
cd testing
python run_scraper.py
```

**Output**: `testing/news_articles.csv`

---

## **ALL 3 TOGETHER** (Quick Setup)

```bash
# Step 1: Get financial data
python core/data_merger.py IAM

# Step 2: Get daily prices
python scrapers/bourse_casa_scraper.py --symbol IAM

# Step 3: Get news
cd testing && python run_scraper.py && cd ..

# Step 4: Run AI (uses all above data)
python run_autopilot.py
```

**Time**: ~2-3 minutes total  
**Result**: AI predicts with 100% real data ✅

---

## **DATA FILES CREATED**

After running the 3 scrapers, you get:

```
data/historical/
├─ IAM_merged.json              ← Financial data (Scraper 1)
└─ IAM_bourse_casa_full.csv     ← Price data (Scraper 2)

testing/
└─ news_articles.csv            ← News data (Scraper 3)
```

**AI reads these files** → Makes prediction ✅

---

## **IF ONE SCRAPER FAILS**

| Scraper Fails | AI Impact | Fallback |
|---|---|---|
| Scraper 1 (Financial) | ❌ CRITICAL - AI can't calculate intrinsic value | Old cached JSON |
| Scraper 2 (Prices) | ⚠️ HIGH - Whale detection fails | Old Investing.com CSV |
| Scraper 3 (News) | ⚠️ MEDIUM - Sentiment defaults to NEUTRAL | Still works |

---

## **VERIFY SCRAPERS WORK**

```bash
# Test 1
python -c "import pandas as pd; df = pd.read_csv('data/historical/IAM_bourse_casa_full.csv'); print(f'✅ {len(df)} price rows')"

# Test 2
python -c "import json; data = json.load(open('data/historical/IAM_merged.json')); print(f'✅ {data[\"identity\"][\"ticker\"]} financial data')"

# Test 3
python -c "import pandas as pd; df = pd.read_csv('testing/news_articles.csv'); print(f'✅ {len(df)} news articles')"
```

---

## **STATUS CHECK**

Run this to see if all scrapers are ready:

```bash
python test_wired_pipeline.py
```

Shows:
- ✅ Current price loaded
- ✅ Intrinsic value calculated
- ✅ Composite score calculated
- ✅ Whale activity detected
- ✅ Sentiment analyzed

If all ✅ → All scrapers working perfectly! 🎉

---

That's it! 3 scrapers = AI ready to predict. 🚀
