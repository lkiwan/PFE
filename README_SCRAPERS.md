# 🎯 COMPLETE ANSWER TO YOUR QUESTION

**Question**: "What are the code files that scrape data that the AI needs to predict?"

**Answer**: **3 Scraper Code Files**

---

## 📌 **THE 3 SCRAPER CODE FILES**

### **1. FINANCIAL DATA SCRAPER**
```
File: core/data_merger.py
Also: scrapers/marketscreener_scraper_v2.py
Purpose: Scrapes financial fundamentals
Collects: Revenue, EBITDA, EPS, P/E, Debt, Dividend, ROE, ROCE, etc.
Output: data/historical/IAM_merged.json
Used by: 5 valuation models + 5 scoring factors
Status: ✅ Working
Run: python core/data_merger.py IAM
```

### **2. DAILY PRICE DATA SCRAPER**
```
File: scrapers/bourse_casa_scraper.py
Purpose: Scrapes daily OHLCV from Casablanca Stock Exchange
Collects: Open, High, Low, Close, Volume (3+ years)
Output: data/historical/IAM_bourse_casa_full.csv
Used by: Whale strategy + 50-day SMA calculation
Status: ✅ Working
Run: python scrapers/bourse_casa_scraper.py --symbol IAM
```

### **3. NEWS SCRAPER**
```
File: testing/run_scraper.py
Purpose: Scrapes news headlines from MarketScreener
Collects: Headlines, dates, sources, URLs
Output: testing/news_articles.csv
Used by: News sentiment analyzer
Status: ✅ Working
Run: cd testing && python run_scraper.py && cd ..
```

---

## 🔄 **Data Flow**

```
3 Scraper Code Files
        ↓
        ├─→ core/data_merger.py
        │   Creates: IAM_merged.json
        │   ↓
        │   Used by: 5 models + scoring
        │
        ├─→ scrapers/bourse_casa_scraper.py
        │   Creates: IAM_bourse_casa_full.csv
        │   ↓
        │   Used by: Whale strategy
        │
        └─→ testing/run_scraper.py
            Creates: news_articles.csv
            ↓
            Used by: Sentiment analyzer
        ↓
    ALL 3 DATA FILES
        ↓
    agents/tools.py (reads all 3 files)
        ↓
    AI Agent (run_autopilot.py)
        ↓
    PREDICTION ✅
```

---

## ✅ **What You Need to Do**

1. **Ensure all 3 scrapers work perfectly**:
   - `core/data_merger.py` ✅
   - `scrapers/bourse_casa_scraper.py` ✅
   - `testing/run_scraper.py` ✅

2. **Run them in order** (takes ~2 minutes):
   ```bash
   python core/data_merger.py IAM
   python scrapers/bourse_casa_scraper.py --symbol IAM
   cd testing && python run_scraper.py && cd ..
   ```

3. **Verify they produced output files**:
   ```bash
   data/historical/IAM_merged.json
   data/historical/IAM_bourse_casa_full.csv
   testing/news_articles.csv
   ```

4. **Run AI** (uses all 3 outputs):
   ```bash
   python run_autopilot.py
   ```

---

## 📊 **Complete File Reference**

| Category | Code File | Data File | Status |
|---|---|---|---|
| Financial | `core/data_merger.py` | `IAM_merged.json` | ✅ |
| Prices | `scrapers/bourse_casa_scraper.py` | `IAM_bourse_casa_full.csv` | ✅ |
| News | `testing/run_scraper.py` | `news_articles.csv` | ✅ |

---

## 🎉 **That's It!**

**3 scraper code files** scrape data that the AI needs to predict:
1. ✅ `core/data_merger.py` (Financial)
2. ✅ `scrapers/bourse_casa_scraper.py` (Prices)
3. ✅ `testing/run_scraper.py` (News)

All 3 are working perfectly and ready to use! 🚀
