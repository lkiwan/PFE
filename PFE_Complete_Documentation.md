# 📈 Complete PFE Project Documentation: AI Quantitative Advisory System

## 1. Project Philosophy & Core Concept
This project is an advanced **Quantitative Trading & Advisory System** for the Moroccan Stock Market (Casablanca Stock Exchange). Instead of relying on human emotion or simple moving averages, this system combines three powerful domains:
1. **Fundamental Analysis:** Deep accounting mathematics to find the true "Intrinsic Value" of a company.
2. **Quantitative Momentum (Whale Strategy):** High-frequency technical algorithms to detect when institutional investors are injecting massive volume.
3. **Artificial Intelligence (Agentic LLMs):** Using localized LLMs (Qwen via Agno) to synthesize the complex mathematics into a human-readable advisory report.

**The Golden Rule:** The AI never does the math. Python does 100% of the mathematical heavy-lifting, and hands the final calculated metrics to the AI to narrate.

---

## 2. System Architecture Schema

```mermaid
graph TD
    subgraph Data Acquisition Layer
        S1[MarketScreener Scraper] -->|Fundamentals & News| J1(stock_data.json / CSV)
        S2[Investing.com Scraper] -->|Daily OHLCV Prices| C1(IAM_Historical.csv)
        S3[Medias24 Scraper / OrderBook] -->|Bid/Ask Depth| DB[(Local Database)]
        S4[AMMC PDF Extractor] -->|Annual Reports| J1
    end

    subgraph The Quantitative Brain (Python)
        J1 --> VE[Valuation Engines]
        J1 --> SE[Factor Scoring Engine]
        C1 --> WS[Whale Strategy Engine]
        
        VE -->|DCF, DDM, Graham Valuations| RE[Recommendation Engine]
        SE -->|Score out of 100| RE
        WS -->|Volume Spikes / Trend| HY[Hybrid Signal Filter]
        RE --> HY
    end

    subgraph Agentic AI Layer (Agno)
        HY -->|Structured JSON Payload| TL[Agent Tools]
        TL --> AG[Agno Advisor Agent]
        OLLAMA((Ollama: Qwen2.5:7b)) --> AG
        AG -->|Narrates| OUT[Final Stock Advisory Report]
    end

    classDef dataset fill:#f9f,stroke:#333,stroke-width:2px;
    classDef brain fill:#bbf,stroke:#333,stroke-width:2px;
    classDef ai fill:#bfb,stroke:#333,stroke-width:2px;
    
    class J1,C1,DB dataset;
    class VE,SE,WS,RE,HY brain;
    class AG,OLLAMA ai;
```

---

## 3. The Data (What we use & Where it is)

### A. Fundamental & News Data 
* **What it is:** Revenue, EBITDA, Free Cash Flow, Debt, Margins, Dividends, and recent news articles.
* **Source:** MarketScreener.
* **File:** `testing/testing/stock_data.json` and `testing/testing/stock_data.csv`.
* **Code:** `testing/scraper.py` and `testing/run_scraper.py`.

### B. Daily Market Data (The "Whale" Fuel)
* **What it is:** Daily Close, Open, High, Low, and most importantly: **Volume** (how many shares traded).
* **Source:** Investing.com & Casablanca Bourse.
* **File:** `IAM/IAM - Données Historiques dayli P*.csv`.
* **Code:** `scrapers/market_data_scraper.py` (MasiScraper).

### C. Level 2 Market Depth
* **What it is:** Real-time Bid and Ask sizes in the order book.
* **Source:** Medias24.
* **Code:** `scrapers/order_book_scraper.py` (Uses Selenium because order books are rendered in JavaScript).

### D. Primary AMMC Reports
* **What it is:** Official Bilan and CPR PDFs from the AMMC (Moroccan SEC).
* **Code:** `scrapers/financial_reports.py` (Uses regex and `pdfplumber` to extract metrics like "Total Actif" directly from PDF grids).

---

## 4. The Quantitative Brain (How the Math Works)

### 4.1 The Valuation Engine (`models/`)
Calculates the absolute "fair value" (Intrinsic Value) of a stock using 5 distinct financial models:
1. **DCF (Discounted Cash Flow):** Projects cash flows 5 years into the future and discounts them back to today's value.
2. **DDM (Dividend Discount Model):** Values the stock based purely on its future dividend payout trajectory.
3. **Graham Number:** Evaluates defensive Benjamin Graham principles (EPS & Book Value).
4. **Relative Valuation (Multiples):** Values the company based on EV/EBITDA and P/E ratios.
5. **Monte Carlo Simulations:** Runs thousands of randomized probabilistic scenarios to find a risk-adjusted fair price.

### 4.2 The Factor Scoring Engine (`strategies/scoring_engine.py`)
Grades the company out of 100 on five institutional pillars:
* **Value:** Is it cheap?
* **Quality:** Are margins high? Is ROE strong?
* **Growth:** Is EPS growing year-over-year?
* **Safety:** Does it have too much debt?
* **Dividend:** Is the yield safe and growing?

### 4.3 The Whale Strategy (`strategies/whale_strategy.py`)
A quantitative momentum algorithm that completely ignores fundamentals and only watches volume.
* Calculates the 20-day average volume for the stock.
* If today's volume is > **2.5x** the normal average, an institutional "Whale" is active.
* If price goes up on whale volume, it indicates **Smart Money Accumulation** (BUY).

---

## 5. The Master Formula: Hybrid Strategy
Found in `strategies/hybrid_whale_strategy.py`.
We do not blindly buy every volume spike. We merge the math:
**[ Whale accumulation detected ] + [ Composite Health Score >= 50/100 ] = EXECUTABLE TRADE SYSTEM SIGNAL**

If a whale buys a company with a score of 30/100, the system blocks the trade (assumes it is smart money covering a short, or a mistake).

---

## 6. The Agno AI Agent (`agents/`)
Instead of having an investor read messy technical charts and complex DCF spreadsheets, we pass the synthesized data to an AI Agent.
* **Framework:** Agno (previously Phidata) -> `agents/advisor_agent.py`
* **Model:** Ollama running `qwen2.5:7b` locally.
* **The Tools:** The AI is given a single tool: `get_iam_stock_advisory_context()`. 

When asked for advice, the AI runs that tool. The tool activates the Python engines, runs the DCF, checks the Whale state, and returns a clean, perfectly structured JSON payload (like "Intrinsic Value: 116 MAD, Whale: False"). 

The AI then translates this JSON into a beautiful, 3-paragraph executive summary recommending a Buy, Hold, or Sell.

---

## 7. Directory Map

```text
C:\Users\arhou\OneDrive\Bureau\PFE.0\
│
├── core/                  # Math normalizers & financial constants
├── models/                # The 5 Valuation models (DCF, DDM, etc.)
├── strategies/            # Scoring Engine, Recommendation Engine, Whale Strategy
├── scrapers/              # OP-based Web & PDF extractors (Base, Masi, AMMC)
├── agents/                # Agno setup, Agent Tools, and LLM Prompts
├── backtest/              # Historic simulation loop & HTML Plotly generation
├── IAM/                   # Daily CSV historical data for technical testing
└── testing/               # Original base scraper for stock_data.json
```

## 8. Quick Start Guide
* **To run an AI Advisory generation:** `python -m agents.advisor_agent --test`
* **To run a full 10-year Quantitative Backtest:** `python backtest/run_hybrid_backtest.py`
* **To update your fundamentals:** `python testing/run_scraper.py`
