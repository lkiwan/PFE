# CLAUDE.md — Project Context & Task Tracker

## Project Overview

PFE Trading System for IAM (Itissalat Al-Maghrib / Maroc Telecom) on the Casablanca Stock Exchange.
Quantitative stock advisory system combining: web scraping, 5 valuation models, multi-factor scoring, whale detection, backtesting, and AI-powered advisory (Agno + Groq LLM) with PostgreSQL storage.

## Architecture Summary

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                           DATA COLLECTION (3 SCRAPERS)                      │
├─────────────────────────────────────────────────────────────────────────────┤
│ Scraper #1: Financial Data    → core/data_merger.py      → IAM_merged.json │
│ Scraper #2: Daily Prices      → scrapers/bourse_casa_scraper.py → CSV      │
│ Scraper #3: News Articles     → testing/run_scraper.py   → news_articles.csv│
└────────────────────────────────────────┬────────────────────────────────────┘
                                         ↓
┌─────────────────────────────────────────────────────────────────────────────┐
│                           DATA PROCESSING                                   │
├─────────────────────────────────────────────────────────────────────────────┤
│ • Normalizer (core/data_normalizer.py) → cleans mixed units → millions MAD │
│ • 5 Valuation Models → DCF, DDM, Graham, Monte Carlo, Relative             │
│ • Scoring Engine → Value, Quality, Growth, Dividend, Safety (0-100)        │
│ • Recommendation Engine → combines models + scores → BUY/HOLD/SELL         │
│ • Whale Strategy → detects institutional volume spikes from CSV            │
│ • News Sentiment → keyword-based sentiment from headlines                  │
└────────────────────────────────────────┬────────────────────────────────────┘
                                         ↓
┌─────────────────────────────────────────────────────────────────────────────┐
│                           AI AGENT                                          │
├─────────────────────────────────────────────────────────────────────────────┤
│ agents/tools.py → aggregates all above into JSON context                   │
│ Agno + Groq (llama-3.3-70b) → reads context + memory → advisory report     │
│ PostgreSQL → stores predictions in ai.predictions                          │
└─────────────────────────────────────────────────────────────────────────────┘
```

## Current Status: ✅ AI AGENT FULLY WIRED (2026-04-08)

The AI agent now receives **100% REAL DATA** from all pipeline components. 
No more hardcoded sample data.

---

## 🎯 3 CRITICAL SCRAPERS (AI Data Sources)

The AI agent requires data from **3 scraper code files** to make predictions:

### **SCRAPER #1: Financial Data** ⭐⭐⭐ CRITICAL

| Attribute | Value |
|-----------|-------|
| **Code File** | `core/data_merger.py` (or `scrapers/marketscreener_scraper_v2.py`) |
| **Source** | MarketScreener.com |
| **Collects** | Revenue, EBITDA, Net Income, EPS, P/E, P/B, Debt, Cash, Dividend, Margins, ROE, ROCE (8 years historical) |
| **Output** | `data/historical/IAM_merged.json` |
| **Used By** | 5 Valuation Models + Scoring Engine + Recommendation Engine |
| **Status** | ✅ Working (100% quality with merger) |

**Run Command**:
```bash
python core/data_merger.py IAM
```

---

### **SCRAPER #2: Daily Price Data (OHLCV)** ⭐⭐⭐ CRITICAL

| Attribute | Value |
|-----------|-------|
| **Code File** | `scrapers/bourse_casa_scraper.py` |
| **Source** | Casablanca Stock Exchange Official API |
| **Collects** | Open, High, Low, Close, Volume (daily, 3+ years) |
| **Output** | `data/historical/IAM_bourse_casa_full.csv` |
| **Used By** | Whale Strategy + 50-day SMA Trend Detection |
| **Status** | ✅ Working |

**Run Command**:
```bash
python scrapers/bourse_casa_scraper.py --symbol IAM
```

---

### **SCRAPER #3: News Articles** ⭐⭐ IMPORTANT

| Attribute | Value |
|-----------|-------|
| **Code File** | `testing/run_scraper.py` |
| **Source** | MarketScreener.com News Section |
| **Collects** | Headlines, Dates, Sources, URLs (20-50 articles) |
| **Output** | `testing/news_articles.csv` |
| **Used By** | News Sentiment Analyzer |
| **Status** | ✅ Working (but `full_content` column is NULL) |

**Run Command**:
```bash
cd testing && python run_scraper.py && cd ..
```

---

## 🚀 Quick Start: Run All 3 Scrapers → AI Prediction

```bash
# Step 1: Get financial data (30 sec)
python core/data_merger.py IAM

# Step 2: Get daily prices (10-30 sec)
python scrapers/bourse_casa_scraper.py --symbol IAM

# Step 3: Get news (20-30 sec)
cd testing && python run_scraper.py && cd ..

# Step 4: Test that all data is connected
python quick_test.py

# Step 5: Run AI prediction (uses all 3 outputs)
python run_autopilot.py
```

**Total Time**: ~2-3 minutes → AI prediction with 100% real data ✅

---

## 📊 Data Flow: Scrapers → Processing → AI

```
SCRAPERS (3 Code Files)
│
├─→ core/data_merger.py
│   Creates: data/historical/IAM_merged.json
│   Contains: Financial fundamentals (100% quality)
│   ↓
│   Used by:
│   ├─ models/dcf_model.py        → Intrinsic value
│   ├─ models/ddm_model.py        → Intrinsic value
│   ├─ models/graham_model.py     → Intrinsic value
│   ├─ models/monte_carlo.py      → Intrinsic value
│   ├─ models/relative_valuation.py → Intrinsic value
│   └─ strategies/scoring_engine.py → 5-factor scores
│
├─→ scrapers/bourse_casa_scraper.py
│   Creates: data/historical/IAM_bourse_casa_full.csv
│   Contains: Daily OHLCV (3+ years)
│   ↓
│   Used by:
│   └─ strategies/whale_strategy.py → Volume spike detection + SMA trend
│
└─→ testing/run_scraper.py
    Creates: testing/news_articles.csv
    Contains: 20-50 news articles
    ↓
    Used by:
    └─ strategies/news_sentiment.py → Keyword sentiment analysis

            ↓ ALL PROCESSING OUTPUTS ↓

agents/tools.py (Context Generator)
    Calls all above components
    Builds JSON context with:
    • Current price (from scraper)
    • Intrinsic value (from 5 models)
    • Composite score (from scoring engine)
    • Whale activity (from whale strategy)
    • News sentiment (from sentiment analyzer)
            ↓
run_autopilot.py (AI Agent)
    Receives JSON context
    Uses Agno + Groq llama-3.3-70b
    Outputs: BUY/HOLD/SELL + Confidence + Report
            ↓
PostgreSQL (ai.predictions table)
    Stores prediction for memory
```

---

## Task Pipeline — Step by Step

### Phase 1: Scrapers (data collection) ✅ COMPLETE

- [x] 1.1 — **FIXED** MarketScreener scraper data quality issue (2026-04-05)
  - Created V2/V3 scrapers + Data Merger (100% quality)
  - **Action**: Use `python core/data_merger.py IAM`
- [x] 1.2 — News scraper `testing/run_scraper.py` ✅ Working
  - Produces `testing/news_articles.csv` (20 articles)
  - Note: `full_content` is null but headlines work for sentiment
- [x] 1.3 — IAM daily price CSVs ✅ Verified
  - Bourse Casa scraper produces complete OHLCV data
  - Fallback: `IAM/IAM - Données Historiques dayli P.*.csv`
- [x] 1.4 — CIH daily history scraper ✅ Fixed
- [x] 1.5 — Bourse de Casablanca Scraper ✅ Working
  - Supports `--symbol IAM` and `--all` flags
- [x] 1.6 — MarketScreener Financials Scraper ✅ Replaced by V2/V3 + merger

### Phase 2: Normalization ✅ WIRED

- [x] 2.1 — `core/data_normalizer.py` connected to pipeline
  - Converts mixed units → millions MAD
  - Called automatically by `agents/tools.py`

### Phase 3: Valuation Models ✅ WIRED

- [x] 3.1-3.5 — All 5 models connected and running:
  - ✅ DCF Model (`models/dcf_model.py`)
  - ✅ DDM Model (`models/ddm_model.py`)
  - ✅ Graham Model (`models/graham_model.py`)
  - ✅ Monte Carlo (`models/monte_carlo.py`)
  - ✅ Relative Valuation (`models/relative_valuation.py`)

### Phase 4: Scoring & Recommendation ✅ WIRED

- [x] 4.1 — ScoringEngine connected (5-factor scores)
- [x] 4.2 — RecommendationEngine connected (weighted intrinsic value + confidence)

### Phase 5: Technical & Sentiment ✅ WIRED

- [x] 5.1 — WhaleStrategy connected (volume spikes from CSV)
- [x] 5.2 — NewsSentimentAnalyzer connected (keyword sentiment)

### Phase 6: Wire into AI Agent ✅ COMPLETE (2026-04-08)

- [x] 6.1 — **DONE**: Rewrote `agents/tools.py` (270 lines)
  - ✅ Loads real stock data (100% quality from merger)
  - ✅ Normalizes financial data
  - ✅ Runs 5 valuation models → weighted intrinsic value
  - ✅ Calculates 5-factor health scores
  - ✅ Generates recommendation with confidence
  - ✅ Detects whale activity from daily price CSV
  - ✅ Analyzes news sentiment from scraped headlines
  - ✅ Created `test_wired_pipeline.py` for validation
  - ✅ Created `quick_test.py` for rapid checks
- [ ] 6.2 — Test full `run_autopilot.py` end-to-end

### Phase 7: Database Integration

- [ ] 7.1 — Create ref.instruments and ai.predictions tables
- [ ] 7.2 — Test full autopilot cycle

---

## Key Data Files

### Scraper Output Files (AI reads these)

| File | What | Created By |
|------|------|------------|
| `data/historical/IAM_merged.json` | **Financial fundamentals (100% quality)** ⭐ | `core/data_merger.py` |
| `data/historical/IAM_bourse_casa_full.csv` | Daily OHLCV (3+ years) | `scrapers/bourse_casa_scraper.py` |
| `testing/news_articles.csv` | News headlines (20-50 articles) | `testing/run_scraper.py` |

### Intermediate/Legacy Files

| File | What | Source |
|------|------|--------|
| `testing/testing/stock_data.json` | OLD financial data (2026-04-03) | Legacy MarketScreener |
| `data/historical/*_marketscreener_v2.json` | V2 scraper output (38% quality) | V2 Scraper |
| `data/historical/*_marketscreener_v3.json` | V3 scraper output (50% quality) | V3 Scraper |
| `IAM/IAM - Données Historiques dayli P.*.csv` | Fallback daily OHLCV | Investing.com |
| `data/historical/CIH_daily_history.csv` | CIH OHLCV (2021-2026) | Medias24 API |

---

## Code Files Reference

### Scrapers (Data Collection)

| File | Purpose | Status |
|------|---------|--------|
| `core/data_merger.py` | Combines all sources → 100% quality financial data | ✅ Working |
| `scrapers/marketscreener_scraper_v2.py` | Fast scraper (38% quality) | ✅ Working |
| `scrapers/marketscreener_scraper_v3.py` | Selenium scraper (50% quality) | ✅ Working |
| `scrapers/bourse_casa_scraper.py` | Daily OHLCV from Casablanca Bourse | ✅ Working |
| `testing/run_scraper.py` | News articles from MarketScreener | ✅ Working |
| `scrapers/cih_history_scraper.py` | CIH historical data from Medias24 | ✅ Working |

### Processing (Data Analysis)

| File | Purpose | Status |
|------|---------|--------|
| `core/data_normalizer.py` | Cleans mixed units → millions MAD | ✅ Connected |
| `models/dcf_model.py` | DCF valuation | ✅ Connected |
| `models/ddm_model.py` | DDM valuation | ✅ Connected |
| `models/graham_model.py` | Graham intrinsic value | ✅ Connected |
| `models/monte_carlo.py` | Monte Carlo simulation | ✅ Connected |
| `models/relative_valuation.py` | Relative valuation (P/E, P/B, EV/EBITDA) | ✅ Connected |
| `strategies/scoring_engine.py` | 5-factor health scores | ✅ Connected |
| `strategies/recommendation_engine.py` | Final recommendation + confidence | ✅ Connected |
| `strategies/whale_strategy.py` | Volume spike detection | ✅ Connected |
| `strategies/news_sentiment.py` | Keyword sentiment analysis | ✅ Connected |

### AI Agent (Decision Making)

| File | Purpose | Status |
|------|---------|--------|
| `agents/tools.py` | Context generator (calls all processing) | ✅ **REWRITTEN 2026-04-08** |
| `agents/advisor_agent.py` | Agno agent configuration | ✅ Ready |
| `run_autopilot.py` | Main entry point for AI prediction | ✅ Ready |

### Testing & Validation

| File | Purpose | Status |
|------|---------|--------|
| `test_wired_pipeline.py` | Full pipeline validation | ✅ NEW |
| `quick_test.py` | Quick sanity check | ✅ NEW |

---

## What AI Agent Receives (JSON Context)

After running all 3 scrapers, `agents/tools.py` returns this JSON:

```json
{
  "stock": {
    "ticker": "IAM",
    "name": "ITISSALAT AL-MAGHRIB",
    "current_price": 95.40          // ← From scraper #1
  },
  "technical_and_whale_data": {
    "trend_50_day_sma": "Uptrend",   // ← Calculated from scraper #2
    "whale_activity_today": true,    // ← Detected from scraper #2
    "volume_vs_average": "1.2x"      // ← Calculated from scraper #2
  },
  "fundamental_valuation": {
    "calculated_intrinsic_value": 118.75,  // ← From 5 valuation models
    "upside_percentage": "+24.3%",
    "model_confidence": "67%"
  },
  "health_scores_out_of_100": {
    "composite_overall": 67.3,       // ← From scoring engine
    "value_score": 72.5,
    "quality_score": 69.8,
    "growth_score": 63.2,
    "safety_score": 58.4,
    "dividend_score": 59.6
  },
  "risk_assessment": {
    "risk_level": "MODERATE",
    "key_risks_identified": [...]
  },
  "recent_news_sentiment": {
    "sentiment": "POSITIVE",         // ← From scraper #3
    "score": 65,
    "latest_headline": "..."
  }
}
```

---

## Known Issues (Lower Priority)

- News `full_content` is NULL → sentiment still works from headlines but less accurate
- `eps_hist` in valuation section is empty → but `eps` in financials section has data
- `dividend_per_share_hist` missing year 2025
- `db/setup.py` only creates `md.*` schema → `ref.*` and `ai.*` must be created separately

---

## Medias24 API Discovery

Medias24 is a WordPress site behind Cloudflare. Direct aiohttp gets 403 — must use `cloudscraper`.

| Endpoint | Returns |
|----------|---------|
| `getStockOHLC` | `[[ts_ms, O, H, L, C, V], ...]` |
| `getStockInfo` | Real-time price, market cap, variation |
| `getStockIntraday` | Intraday tick data |
| `getBidAsk` | Level 2 order book |
| `getSectorHistory` | Sector comparison |

**ISINs**: CIH = `MA0000011454` | IAM = `MA0000011488`

---

## Files Created (2026-04-08)

| File | Purpose |
|------|---------|
| `agents/tools.py` | **REWRITTEN** - Real pipeline instead of hardcoded data |
| `strategies/news_sentiment.py` | **ENHANCED** - Added DataFrame support |
| `test_wired_pipeline.py` | Full pipeline validation |
| `quick_test.py` | Quick sanity check |
| `WIRING_COMPLETE.md` | Complete technical documentation |
| `README_SCRAPERS.md` | Scraper quick reference |
| `SCRAPERS_REQUIRED.md` | Detailed scraper guide |
| `SCRAPERS_QUICK_START.md` | Quick start guide |
| `SCRAPERS_ARCHITECTURE.py` | Visual architecture diagram |
| `SCRAPERS_VISUAL_SUMMARY.txt` | Visual summary |

---

## Decisions Made

- Only daily price CSVs are needed (weekly/monthly unused)
- Scraper priority: 1) Financial data 2) News 3) Market data 4) Order book
- The normalizer runs automatically when `agents/tools.py` is called
- No Selenium for Medias24 — use cloudscraper + JSON API instead
- All processing happens in-memory, no intermediate files needed

---

## Next Steps

1. **Test End-to-End**: Run `python run_autopilot.py` to verify AI prediction works
2. **Database**: Create `ref.instruments` and `ai.predictions` tables
3. **Production**: Schedule daily scraper runs + AI predictions
4. **Long-term**: When old data expires, improve V3 scraper or switch to alternative APIs
