"""
SCRAPER CODE FILES DEPENDENCY DIAGRAM
=====================================

This shows which code files scrape data, and what the AI needs from them.
"""

# ============================================================================
# LAYER 1: DATA COLLECTION (SCRAPERS)
# ============================================================================

SCRAPER_1_FINANCIAL = """
┌─────────────────────────────────────────────┐
│ SCRAPER #1: Financial Data                  │
├─────────────────────────────────────────────┤
│ File: scrapers/marketscreener_scraper_v2.py │
│ OR:   scrapers/marketscreener_scraper_v3.py │
│ OR:   core/data_merger.py (combines both)   │
├─────────────────────────────────────────────┤
│ Collects:                                   │
│ • Revenue (8 years)                         │
│ • EBITDA (8 years)                          │
│ • Net Income (8 years)                      │
│ • EPS (8 years)                             │
│ • Debt, Cash, Equity                        │
│ • P/E, P/B, EV/EBITDA ratios               │
│ • Dividend per share                        │
│ • Margins, ROE, ROCE                        │
├─────────────────────────────────────────────┤
│ Output:                                     │
│ → data/historical/IAM_merged.json           │
├─────────────────────────────────────────────┤
│ Used By:                                    │
│ → 5 Valuation Models (DCF, DDM, Graham...) │
│ → Scoring Engine (Value, Quality, Growth)  │
│ → Recommendation Engine                     │
└─────────────────────────────────────────────┘
"""

SCRAPER_2_PRICE = """
┌─────────────────────────────────────────────┐
│ SCRAPER #2: Daily Price Data (OHLCV)        │
├─────────────────────────────────────────────┤
│ File: scrapers/bourse_casa_scraper.py       │
├─────────────────────────────────────────────┤
│ Collects:                                   │
│ • Open (daily)                              │
│ • High (daily)                              │
│ • Low (daily)                               │
│ • Close (daily)                             │
│ • Volume (daily)                            │
│ • 3+ years of history                       │
├─────────────────────────────────────────────┤
│ Output:                                     │
│ → data/historical/IAM_bourse_casa_full.csv  │
├─────────────────────────────────────────────┤
│ Used By:                                    │
│ → Whale Strategy (volume spikes)            │
│ → 50-day SMA calculation                    │
│ → Technical trend detection                 │
└─────────────────────────────────────────────┘
"""

SCRAPER_3_NEWS = """
┌─────────────────────────────────────────────┐
│ SCRAPER #3: News Articles                   │
├─────────────────────────────────────────────┤
│ File: testing/run_scraper.py                │
├─────────────────────────────────────────────┤
│ Collects:                                   │
│ • News headlines                            │
│ • Article dates                             │
│ • News sources                              │
│ • Article URLs                              │
│ • Article content (currently NULL)          │
├─────────────────────────────────────────────┤
│ Output:                                     │
│ → testing/news_articles.csv                 │
├─────────────────────────────────────────────┤
│ Used By:                                    │
│ → News Sentiment Analyzer                   │
│ → Sentiment Score (0-100)                   │
│ → Recent Sentiment Direction                │
└─────────────────────────────────────────────┘
"""

# ============================================================================
# LAYER 2: DATA PROCESSING (NORMALIZATION & CALCULATION)
# ============================================================================

PROCESSING_LAYER = """
┌──────────────────────────────────────────────────────────────┐
│             DATA PROCESSING (In-Memory)                      │
├──────────────────────────────────────────────────────────────┤
│                                                              │
│  core/data_normalizer.py:                                    │
│  • Converts mixed units → millions MAD                       │
│  • Validates financial data                                  │
│                                                              │
│  models/*.py (5 models):                                     │
│  • DCF Model → intrinsic value                               │
│  • DDM Model → intrinsic value                               │
│  • Graham Model → intrinsic value                            │
│  • Monte Carlo Model → intrinsic value                       │
│  • Relative Valuation → intrinsic value                      │
│                                                              │
│  strategies/scoring_engine.py:                               │
│  • Value score (0-100)                                       │
│  • Quality score (0-100)                                     │
│  • Growth score (0-100)                                      │
│  • Safety score (0-100)                                      │
│  • Dividend score (0-100)                                    │
│  • Composite score (0-100)                                   │
│                                                              │
│  strategies/whale_strategy.py:                               │
│  • Volume spike detection                                    │
│  • 50-day SMA trend                                          │
│  • Whale activity signal                                     │
│                                                              │
│  strategies/news_sentiment.py:                               │
│  • Keyword sentiment analysis                                │
│  • Sentiment score (0-100)                                   │
│  • Sentiment direction (Positive/Neutral/Negative)           │
│                                                              │
└──────────────────────────────────────────────────────────────┘
"""

# ============================================================================
# LAYER 3: AI CONTEXT GENERATION
# ============================================================================

CONTEXT_GENERATION = """
┌──────────────────────────────────────────────────────────────┐
│             agents/tools.py                                  │
│             (Context Generator for AI)                       │
├──────────────────────────────────────────────────────────────┤
│                                                              │
│  Calls all processing layers above                           │
│  Returns JSON context with:                                  │
│                                                              │
│  {                                                           │
│    "stock": {                                                │
│      "ticker": "IAM",                                        │
│      "current_price": 95.40  ← From Scraper #1              │
│    },                                                        │
│    "technical_and_whale_data": {                             │
│      "whale_activity_today": true ← From Scraper #2         │
│    },                                                        │
│    "fundamental_valuation": {                                │
│      "calculated_intrinsic_value": 118.75 ← From Models      │
│    },                                                        │
│    "health_scores_out_of_100": {                             │
│      "composite_overall": 67.3 ← From Scoring               │
│    },                                                        │
│    "recent_news_sentiment": {                                │
│      "sentiment": "POSITIVE" ← From Scraper #3              │
│    }                                                         │
│  }                                                           │
│                                                              │
└──────────────────────────────────────────────────────────────┘
"""

# ============================================================================
# LAYER 4: AI PREDICTION
# ============================================================================

AI_PREDICTION = """
┌──────────────────────────────────────────────────────────────┐
│  AI AGENT (run_autopilot.py / advisor_agent.py)             │
│  Model: Groq llama-3.3-70b (via Agno framework)             │
├──────────────────────────────────────────────────────────────┤
│                                                              │
│  Receives: JSON context from agents/tools.py                │
│  Reads: Previous prediction memory (if exists)              │
│  Thinks: Professional stock advisor                         │
│  Outputs:                                                   │
│                                                              │
│  RECOMMENDATION: [BUY / HOLD / SELL]                         │
│  CONFIDENCE: [0-100]                                         │
│  TIMEFRAME: [e.g., 1-3 Months]                               │
│  <3-paragraph professional advisory report>                 │
│                                                              │
└──────────────────────────────────────────────────────────────┘
"""

# ============================================================================
# COMPLETE FLOW
# ============================================================================

COMPLETE_FLOW = """
DATA COLLECTION
       ↓
   Scraper #1: Financial Data
   Scraper #2: Daily Prices  ←─────────────────────┐
   Scraper #3: News Articles                       │
       ↓                                            │
DATA PROCESSING                                    │
   ├─ Normalize financial data                    │
   ├─ Run 5 valuation models → Intrinsic value    │
   ├─ Calculate 5-factor scores                   │
   ├─ Detect whale activity (uses CSV from #2)    │
   └─ Analyze news sentiment (uses CSV from #3)   │
       ↓                                            │
CONTEXT GENERATION (agents/tools.py)              │
   └─ Builds JSON with all above data             │
       ↓                                            │
AI AGENT                                           │
   └─ Reads JSON → Makes prediction ✅             │
       ↓                                            │
DATABASE (PostgreSQL)                              │
   └─ Stores: ai.predictions table
      (prediction_date, predicted_trend, 
       confidence_score, timeframe, ai_reasoning)
"""

# ============================================================================
# SCRAPER STATUS & EXECUTION
# ============================================================================

SCRAPER_EXECUTION = """
To get AI ready to predict:

Step 1: Run Scraper #1 (Financial Data)
────────────────────────────────────────
python core/data_merger.py IAM

Creates: data/historical/IAM_merged.json (100% complete)
Time: ~30 seconds
Status: ✅ READY


Step 2: Run Scraper #2 (Daily Prices)
──────────────────────────────────────
python scrapers/bourse_casa_scraper.py --symbol IAM

Creates: data/historical/IAM_bourse_casa_full.csv
Time: ~10-30 seconds
Status: ✅ READY


Step 3: Run Scraper #3 (News)
──────────────────────────────
cd testing && python run_scraper.py && cd ..

Creates: testing/news_articles.csv
Time: ~20-30 seconds
Status: ✅ READY


Step 4: Run AI Agent
────────────────────
python run_autopilot.py

Uses: All 3 scraper outputs
Produces: Trading prediction + confidence
Time: ~30-60 seconds
Status: ✅ READY
"""

# ============================================================================
# PRINT ALL
# ============================================================================

if __name__ == "__main__":
    print("\n" + "="*70)
    print("SCRAPER ARCHITECTURE DIAGRAM")
    print("="*70)
    
    print("\n" + SCRAPER_1_FINANCIAL)
    print("\n" + SCRAPER_2_PRICE)
    print("\n" + SCRAPER_3_NEWS)
    
    print("\n" + PROCESSING_LAYER)
    print("\n" + CONTEXT_GENERATION)
    print("\n" + AI_PREDICTION)
    
    print("\n" + "="*70)
    print("COMPLETE DATA FLOW")
    print("="*70)
    print(COMPLETE_FLOW)
    
    print("\n" + "="*70)
    print("HOW TO EXECUTE")
    print("="*70)
    print(SCRAPER_EXECUTION)
