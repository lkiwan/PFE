# AI Algorithmic Trading Agent - How It Works

## Projet de Fin d'Etudes (PFE) - Casablanca Stock Exchange

---

## Table of Contents

1. [Project Overview](#project-overview)
2. [System Architecture](#system-architecture)
3. [Phase 1: Web Scraper](#phase-1-web-scraper)
4. [Phase 2: Prediction & Advisory Engine](#phase-2-prediction--advisory-engine)
5. [Data Pipeline](#data-pipeline)
6. [Valuation Models](#valuation-models)
7. [Multi-Factor Scoring](#multi-factor-scoring)
8. [Recommendation Engine](#recommendation-engine)
9. [Output & Report](#output--report)
10. [Project Structure](#project-structure)
11. [How to Run](#how-to-run)
12. [Technical Details](#technical-details)

---

## Project Overview

This project is an **AI-powered stock advisory system** designed for the **Moroccan Stock Exchange (Casablanca)**. It targets **IAM (Itissalat Al-Maghrib)**, Morocco's largest telecommunications operator, as the initial stock for analysis.

The system operates in two main phases:

1. **Data Collection** — An asynchronous web scraper extracts ~295 financial data points from MarketScreener.com
2. **Prediction & Advisory** — A multi-model valuation engine processes the data and generates investment recommendations

The goal is to automate fundamental analysis and produce actionable **BUY / HOLD / SELL** recommendations backed by quantitative models, factor scoring, and risk assessment.

---

## System Architecture

```
                          PHASE 1: DATA COLLECTION
                          ========================

    MarketScreener.com
    (7 pages per stock)
           |
           v
    +------------------+
    |   Async Scraper   |     8 specialized scrapers running concurrently
    |   (aiohttp +      |     - QuoteScraper      (price, identity)
    |    BeautifulSoup)  |     - FinanceScraper     (income, balance sheet, cash flow, ratios)
    +------------------+      - ConsensusScraper   (analyst ratings)
           |                  - RatingsScraper      (trader/investor/ESG ratings)
           v                  - ValuationScraper    (P/E, EV/EBITDA, historical multiples)
    +------------------+      - DividendScraper     (dividend history)
    |  stock_data.json  |     - CalendarScraper     (ex-dividend, earnings dates)
    |  stock_data.csv   |     - CompanyScraper      (employees, description, revenue split)
    +------------------+
           |
           |
                          PHASE 2: ADVISORY ENGINE
                          ========================
           |
           v
    +------------------+
    |   Data Loader     |     Reads JSON output from scraper
    +------------------+
           |
           v
    +------------------+
    |  Data Normalizer  |     Fixes mixed units (full MAD vs millions vs ratios)
    |                   |     Cross-validates using margins and balance sheet
    |                   |     Reconstructs broken historical values
    +------------------+
           |
           v
    +------------------+     +------------------+
    | 5 Valuation      |     | 5-Factor Scoring |
    | Models            |     | Engine           |
    |                   |     |                  |
    | - DCF        30%  |     | - Value     25%  |
    | - DDM        20%  |     | - Quality   20%  |
    | - Graham     10%  |     | - Growth    20%  |
    | - Relative   25%  |     | - Dividend  15%  |
    | - Monte Carlo 15% |     | - Safety    20%  |
    +------------------+     +------------------+
           |                        |
           v                        v
    +--------------------------------------+
    |       Recommendation Engine           |
    |                                       |
    |  Weighted fair value + composite      |
    |  score -> BUY / HOLD / SELL           |
    |  + confidence level + risk assessment |
    +--------------------------------------+
           |
           v
    +------------------+
    |  Report Generator |     JSON report + formatted text output
    +------------------+
```

---

## Phase 1: Web Scraper

### What It Does

The scraper (`testing/scraper.py`) is a fully asynchronous Python application that extracts financial data for Moroccan stocks from **MarketScreener.com**. It uses `aiohttp` for non-blocking HTTP requests and `BeautifulSoup` for HTML parsing.

### Pages Scraped

For each stock, the scraper visits **7 different pages** on MarketScreener:

| Page | URL Suffix | Data Extracted |
|------|-----------|----------------|
| Main Quote | `/` | Current price, daily/weekly/YTD changes, market cap, P/E ratio, dividend yield |
| Finances | `/finances/` | Income statement, balance sheet, cash flow statement, financial ratios (2021-2028) |
| Consensus | `/consensus/` | Analyst consensus (BUY/HOLD/SELL), target prices, number of analysts |
| Valuation | `/valuation/` | Historical P/E, P/B, PEG, EV/EBITDA, EV/Revenue, FCF yield, dividend per share |
| Dividend | `/valuation-dividend/` | Dividend per share history, distribution rates, EPS history |
| Calendar | `/calendar/` | Ex-dividend dates, dividend amounts, next earnings date |
| Company | `/company/` | Business description, employee count, revenue breakdown, international exposure |

### Data Extracted (~295 fields)

The scraper populates 8 data categories:

**Stock Identity** — Full name, ticker (IAM), ISIN (MA0000011488), exchange, sector, currency

**Price Performance** — Last price, changes (1-day, 1-week, 1-month, 3-month, 6-month, YTD, 1-year)

**Valuation Metrics** — Market cap, enterprise value, free float %, P/E ratio, EV/Sales, dividend yield, price-to-book, EV/EBITDA, plus historical data for all these multiples from 2021 to 2028

**Financial Statements** — Net sales, revenues, cost of sales, gross profit, EBITDA, EBIT, net income, EPS, total assets, total liabilities, shareholders equity, net debt, cash, total debt, working capital, operating cash flow, CapEx, free cash flow, dividends paid — all with yearly data from 2021 to 2028

**Financial Ratios** — EBITDA margin, operating margin, net margin, ROE, ROA, ROCE, debt-to-equity, current ratio — yearly from 2021 to 2028

**Analyst Consensus** — Overall recommendation, number of analysts, target prices (average, high, low), upside percentage

**Ratings** — Trader rating, investor rating, global rating, quality rating, ESG rating

**Calendar Events** — Ex-dividend date, dividend amount, payment date, next earnings date

**Company Profile** — Number of employees, full business description, international revenue percentage

### Anti-Bot Measures

The scraper implements several techniques to avoid being blocked:
- User-Agent rotation (4 different browser signatures)
- Random delays between requests (2-5 seconds)
- Connection pooling with limited concurrency (3 simultaneous requests)
- Retry logic with exponential backoff on server errors
- Standard browser headers (Accept, Accept-Language, etc.)

### Output Format

Data is saved in two formats:
- **JSON** (`stock_data.json`) — Nested structure preserving the hierarchy (identity > valuation > financials > etc.)
- **CSV** (`stock_data.csv`) — Flattened structure with all fields as columns, prefixed by category (e.g., `fin_net_sales_2025`, `valuation_pe_ratio_hist_2023`)

---

## Phase 2: Prediction & Advisory Engine

### What It Does

The advisory engine takes the scraped data and runs it through a pipeline of **5 valuation models** and a **5-factor scoring system** to produce a final investment recommendation.

### Why These Models?

The scraped data is **fundamental data** (financial statements, ratios, analyst estimates) — not daily price time-series. This means traditional technical analysis (moving averages, RSI, MACD) or deep learning price prediction (LSTM, transformers) would not work here.

Instead, we use **fundamental valuation models** — the same methods used by professional equity analysts, investment banks, and academic finance:

- **Discounted Cash Flow (DCF)** — The gold standard of intrinsic valuation
- **Dividend Discount Model (DDM)** — Ideal for consistent dividend payers like IAM
- **Benjamin Graham formulas** — Classic value investing from "The Intelligent Investor"
- **Relative Valuation** — Market-based comparison using multiples
- **Monte Carlo Simulation** — Probabilistic approach that handles uncertainty

Using **5 different models** rather than one reduces the risk of any single model's assumptions dominating the result. It is a form of "ensemble" approach applied to financial modeling.

---

## Data Pipeline

### The Data Normalization Problem

The scraper extracts data from different MarketScreener pages, and each page uses **different units**:

| Source Page | Example Value | Unit |
|-------------|--------------|------|
| Income Statement | 35,790,000,000 | Full MAD |
| Forecasts/Estimates | 35,790 | Millions MAD |
| Ratios page | 0.35 | Ratio (e.g., OCF/Revenue) |
| Margins page | 54.28 | Percentage |

The **Data Normalizer** (`core/data_normalizer.py`) is the most critical component. It:

1. **Detects the denomination** of each field by comparing magnitudes against revenue
2. **Converts all monetary values** to a consistent unit: **millions MAD**
3. **Cross-validates** using margins (e.g., EBITDA should equal EBITDA margin % times revenue)
4. **Reconstructs broken values** — For example, if net debt for 2021-2025 is stored as a tiny ratio (1.59), it reconstructs it from total_debt minus cash (19,603 - 2,164 = 17,439 million)
5. **Derives missing metrics** — EPS from net income / shares, book value per share, interest coverage

### Data Flow

```
stock_data.json
       |
       v
  DataLoader        -->  Raw dict with mixed units
       |
       v
  DataNormalizer    -->  Clean dict, all in millions MAD
       |
       +----------> 5 Valuation Models (each gets the same clean data)
       |
       +----------> Scoring Engine (evaluates quality, value, growth, etc.)
       |
       v
  RecommendationEngine  -->  Final advisory
```

---

## Valuation Models

### 1. Discounted Cash Flow (DCF) — Weight: 30%

**File:** `models/dcf_model.py`

The DCF is the most theoretically rigorous valuation method. It answers: "What is the present value of all future cash flows this company will generate?"

**How it works:**

1. **Compute WACC** (Weighted Average Cost of Capital):
   ```
   Cost of Equity = Risk-Free Rate + Beta x Equity Risk Premium
                  = 3.5% + 0.70 x 6.5%
                  = 8.05%

   WACC = (Equity Weight x Cost of Equity) + (Debt Weight x Cost of Debt x (1 - Tax Rate))
        = (81.1% x 8.05%) + (18.9% x 5.0% x 69%)
        = 7.18%
   ```

2. **Project Free Cash Flow** for 5 years using MarketScreener analyst estimates (2026-2028) extended with decaying growth

3. **Compute Terminal Value** using the Gordon Growth Model:
   ```
   Terminal Value = FCF(last year) x (1 + g) / (WACC - g)
   where g = 2.5% (long-term growth rate)
   ```

4. **Discount everything to present value**:
   ```
   Enterprise Value = PV(projected FCFs) + PV(Terminal Value)
   Equity Value = Enterprise Value - Net Debt + Cash
   Per-Share Value = Equity Value / Number of Shares
   ```

5. **Sensitivity analysis**: Run the model with WACC +/- 1% and growth +/- 0.5% to produce bear/bull range

**Morocco-specific parameters:**
- Risk-free rate: 3.5% (Bank Al-Maghrib 10-year government bond)
- Equity risk premium: 6.5% (emerging market premium)
- IAM Beta: 0.70 (defensive telecom sector)
- Corporate tax rate: 31% (Morocco standard rate)
- Terminal growth: 2.5% (aligned with Morocco GDP growth)

---

### 2. Dividend Discount Model (DDM) — Weight: 20%

**File:** `models/ddm_model.py`

The DDM is particularly well-suited for IAM because it is a **consistent dividend payer** with a ~70% payout ratio and ~4.5% dividend yield.

**How it works (3-stage model):**

1. **Stage 1 — Explicit Forecasts (2026-2028):**
   Uses the actual dividend per share estimates from MarketScreener:
   - 2026: 4.18 MAD
   - 2027: 4.25 MAD
   - 2028: 4.74 MAD

2. **Stage 2 — Transition Period (2029-2033):**
   Dividend growth rate decays linearly from the Stage 1 growth rate down to the terminal growth rate (2.5%)

3. **Stage 3 — Terminal Value:**
   ```
   Terminal Value = Final Dividend x (1 + g) / (Cost of Equity - g)
   ```

4. **Discount all dividends** back to present using Cost of Equity (8.05%)

---

### 3. Benjamin Graham Intrinsic Value — Weight: 10%

**File:** `models/graham_model.py`

Classic formulas from Benjamin Graham, the father of value investing and mentor to Warren Buffett.

**Graham Number:**
```
Graham Number = sqrt(22.5 x EPS x Book Value Per Share)
```
Where 22.5 = 15 (reasonable P/E) x 1.5 (reasonable P/B). This gives the maximum price a defensive investor should pay.

**Graham Growth Formula (revised):**
```
V = EPS x (8.5 + 2g) x 4.4 / Y
```
Where:
- 8.5 = P/E for a zero-growth company
- g = expected annual growth rate (%)
- 4.4 = average AAA bond yield when Graham wrote the formula
- Y = current AAA corporate bond yield in Morocco

**Net Current Asset Value (NCAV):**
```
NCAV = (Total Assets - Total Liabilities) / Shares
```
This is the liquidation floor — the absolute minimum the stock should be worth.

---

### 4. Relative Valuation — Weight: 25%

**File:** `models/relative_valuation.py`

This model answers: "Compared to its own history and its sector, is the stock cheap or expensive?"

**How it works:**

For each of 5 valuation multiples (P/E, EV/EBITDA, P/B, EV/Revenue, FCF Yield):

1. Compute the **historical median** (2021-2025) for the stock
2. Get the **sector benchmark** for emerging market telecoms
3. Create a **blended multiple** = 60% historical median + 40% sector benchmark
4. Calculate implied fair value:
   ```
   Fair Price (P/E) = Blended P/E x Current EPS
   Fair Price (EV/EBITDA) = (Blended EV/EBITDA x EBITDA - Net Debt + Cash) / Shares
   ```

The final fair value is a **weighted composite** of all implied values, with **EV/EBITDA getting the highest weight (35%)** because it is the most reliable multiple for capital-intensive telecoms (it is unaffected by depreciation policy or capital structure differences).

Using the **median** instead of the mean filters out outlier years (e.g., IAM's 2024 had an anomalous P/E of 40x due to one-time charges).

---

### 5. Monte Carlo Simulation — Weight: 15%

**File:** `models/monte_carlo.py`

Monte Carlo addresses the fundamental truth of valuation: **the future is uncertain**. Instead of picking single-point estimates, it samples from probability distributions.

**How it works:**

1. Define distributions for uncertain inputs:
   - Revenue growth: Normal(mean=1.5%, std=2.0%)
   - EBITDA margin: Normal(mean=50%, std=5%)
   - WACC: Uniform(6.5%, 9.5%)
   - Terminal growth: Uniform(1.5%, 3.5%)
   - CapEx ratio: Normal(mean=15%, std=2%)

2. Run **10,000 iterations** of a simplified DCF, each with randomly sampled parameters

3. Output a full probability distribution:
   - **Median** fair value (the 50th percentile)
   - **P10** (bear case — 90% chance the stock is worth more)
   - **P90** (bull case — 90% chance the stock is worth less)
   - **Probability that fair value exceeds current price**

This gives investors not just a single number, but a sense of **how confident** the valuation is and **what the range of outcomes looks like**.

---

## Multi-Factor Scoring

**File:** `strategies/scoring_engine.py`

Beyond intrinsic value, the system evaluates the stock across **5 qualitative/quantitative dimensions**, each scored from 0 to 100:

### Factor 1: Value (Weight: 25%)

Measures whether the stock is cheap or expensive relative to its fundamentals.

| Sub-metric | What it measures | IAM Data |
|-----------|-----------------|----------|
| P/E vs Historical Median | Is current P/E below its own average? | 15.6x vs ~20x median |
| EV/EBITDA vs Sector | How does it compare to telecom peers? | 7.36x vs 6.5x sector |
| FCF Yield | How much free cash flow per unit of enterprise value? | ~8% |

### Factor 2: Quality (Weight: 20%)

Measures the company's profitability and earnings consistency.

| Sub-metric | What it measures | IAM Data |
|-----------|-----------------|----------|
| ROE Level | How efficiently does it use shareholder equity? | ~20-39% range |
| ROE Consistency | Is profitability stable or volatile? | Coefficient of variation |
| EBITDA Margin | How much of revenue becomes operating profit? | ~50% (excellent) |
| ROCE | Return on total capital employed | ~19% average |

### Factor 3: Growth (Weight: 20%)

Measures revenue and earnings growth trajectory.

| Sub-metric | What it measures | IAM Data |
|-----------|-----------------|----------|
| Revenue CAGR | Compound annual growth rate of sales | ~0.8% (2021-2028) |
| EPS Growth | Earnings per share trajectory | From data |
| Margin Expansion | Are margins improving over time? | 2025 vs 2023 comparison |

### Factor 4: Dividend (Weight: 15%)

Measures the attractiveness and sustainability of dividend payments.

| Sub-metric | What it measures | IAM Data |
|-----------|-----------------|----------|
| Dividend Yield | Annual dividend as % of price | 4.45% |
| Payout Sustainability | Is the payout ratio manageable? | ~70% (sustainable) |
| DPS Growth | Is the dividend growing over time? | Trend analysis |
| Yield Spread | How much above risk-free rate? | ~0.95% above bonds |

### Factor 5: Safety (Weight: 20%)

Measures financial health and risk of distress.

| Sub-metric | What it measures | IAM Data |
|-----------|-----------------|----------|
| Debt-to-Equity | Leverage level | Monitored |
| Current Ratio | Short-term liquidity | 0.39 (below 1.0 = concern) |
| Interest Coverage | Can it service its debt? | EBIT / Interest |
| FCF Consistency | How many years of positive free cash flow? | Out of 5 years |

### Composite Score

```
Composite = 25% x Value + 20% x Quality + 20% x Growth + 15% x Dividend + 20% x Safety
```

---

## Recommendation Engine

**File:** `strategies/recommendation_engine.py`

The recommendation engine combines the outputs of all 5 valuation models and the factor scores into a final advisory.

### Step 1: Weighted Fair Value

Each model's intrinsic value is weighted:

```
Fair Value = 30% x DCF + 20% x DDM + 10% x Graham + 25% x Relative + 15% x Monte Carlo
```

The weights reflect each model's reliability:
- **DCF (30%)** — Most theoretically grounded
- **Relative (25%)** — Market-anchored, practical
- **DDM (20%)** — Strong for dividend stocks
- **Monte Carlo (15%)** — Captures uncertainty
- **Graham (10%)** — Conservative floor, formulas designed for a different era

### Step 2: Upside Calculation

```
Upside % = (Fair Value - Current Price) / Current Price x 100
```

### Step 3: Recommendation Mapping

The recommendation depends on **both** the upside percentage **and** the composite factor score:

| Recommendation | Upside Condition | Score Condition |
|---------------|-----------------|-----------------|
| **STRONG BUY** | > +20% | AND composite >= 65 |
| **BUY** | > +10% | AND composite >= 55 |
| **HOLD** | -10% to +10% | Any score |
| **SELL** | < -10% | AND composite < 45 |
| **STRONG SELL** | < -20% | AND composite < 35 |

This dual-condition approach prevents the system from recommending a "BUY" on a stock that is cheap but fundamentally weak, or a "SELL" on a stock that is expensive but fundamentally strong.

### Step 4: Confidence Score

Confidence is calculated from three components:

1. **Model Agreement (40%)** — How closely the 5 models agree. Low standard deviation = high confidence
2. **Average Model Confidence (35%)** — Each model reports its own confidence based on data availability
3. **Coverage (25%)** — What percentage of models produced valid results

### Step 5: Risk Assessment

Risk level is determined by the safety and composite scores:
- **LOW** — Safety >= 70 AND Composite >= 65
- **MODERATE** — Safety >= 45 AND Composite >= 45
- **HIGH** — Below moderate thresholds

Specific risks are flagged:
- High leverage or low liquidity
- Limited growth prospects
- Overvaluation signals
- High model disagreement

---

## Output & Report

**File:** `utils/report_generator.py`

The system produces two outputs:

### 1. JSON Report (`advisory_report.json`)

A structured machine-readable report containing all model outputs, scores, and the recommendation. This can be consumed by other systems, dashboards, or APIs.

```json
{
  "recommendation": "BUY",
  "confidence": 54,
  "current_price": 95.5,
  "intrinsic_value": {
    "weighted_average": 116.35,
    "low_estimate": 72.65,
    "high_estimate": 152.10,
    "upside_pct": 21.8
  },
  "factor_scores": {
    "value": 72.7,
    "quality": 69.6,
    "growth": 62.3,
    "dividend": 57.2,
    "safety": 56.7,
    "composite": 64.5
  },
  "risk_assessment": {
    "level": "MODERATE",
    "key_risks": ["..."]
  },
  "model_details": { "...each model's full breakdown..." },
  "key_metrics": { "...P/E, EV/EBITDA, ROE, margins, etc..." }
}
```

### 2. Formatted Text Report (Console)

A human-readable report with visual bar charts for factor scores, a summary table of all model outputs, and key metrics at a glance.

---

## Project Structure

```
PFE.0/
|
|-- testing/                        # PHASE 1: Web Scraper
|   |-- scraper.py                  # Main async scraper (~1500 lines)
|   |-- config.py                   # Scraper configuration
|   |-- requirements.txt            # Scraper dependencies
|   |-- SCRAPER_PLAN.md             # Scraper implementation plan
|   |-- stock_data.csv              # Latest scraped data (flat)
|   |-- testing/
|       |-- stock_data.json         # Latest scraped data (nested)
|       |-- stock_data.csv          # Backup CSV
|
|-- core/                           # Data pipeline
|   |-- data_loader.py              # Load JSON from scraper
|   |-- data_normalizer.py          # Fix units, cross-validate, derive metrics
|
|-- models/                         # PHASE 2: Valuation Models
|   |-- base_model.py               # Abstract base + ValuationResult
|   |-- dcf_model.py                # Discounted Cash Flow
|   |-- ddm_model.py                # Dividend Discount Model
|   |-- graham_model.py             # Graham Number + Growth Formula
|   |-- relative_valuation.py       # Multiples-based relative valuation
|   |-- monte_carlo.py              # Monte Carlo simulation (10,000 iterations)
|
|-- strategies/                     # Scoring & Recommendation
|   |-- scoring_engine.py           # 5-factor scoring (value, quality, growth, dividend, safety)
|   |-- recommendation_engine.py    # Combines models + scores into final advisory
|
|-- utils/                          # Utilities
|   |-- financial_constants.py      # Morocco parameters, sector benchmarks, thresholds
|   |-- report_generator.py         # JSON + text report generation
|
|-- main_advisory.py                # Entry point for the advisory system
|-- advisory_report.json            # Generated report output
|-- how.md                          # This documentation file
```

---

## How to Run

### Prerequisites

```bash
pip install aiohttp beautifulsoup4 lxml pandas numpy scipy
```

### Step 1: Scrape Latest Data

```bash
cd testing
python scraper.py
```

This fetches fresh data from MarketScreener for IAM and saves it to `stock_data.json` and `stock_data.csv`.

### Step 2: Run the Advisory

```bash
cd ..
python main_advisory.py
```

This runs the full pipeline: load data, normalize, run 5 models, score, recommend, and output the report.

### Step 3: Read the Report

- **Console**: The formatted text report prints directly
- **JSON**: Open `advisory_report.json` for the full structured output

---

## Technical Details

### Dependencies

| Library | Version | Purpose |
|---------|---------|---------|
| `aiohttp` | >= 3.9.0 | Async HTTP requests for scraper |
| `beautifulsoup4` | >= 4.12.0 | HTML parsing |
| `lxml` | >= 5.1.0 | Fast XML/HTML parser backend |
| `pandas` | >= 2.1.0 | Data manipulation |
| `numpy` | >= 1.24.0 | Monte Carlo simulation, statistics |
| `scipy` | >= 1.10.0 | Probability distributions |

### Key Design Decisions

**Why fundamental models, not ML/deep learning?**
With a single snapshot of data (not thousands of training samples), ML models would overfit. Fundamental valuation is the correct tool for this data type. It is also more defensible academically — citing Damodaran, Graham & Dodd, and Fama-French.

**Why 5 models instead of 1?**
Model ensembling reduces the risk of any single model's assumptions dominating. Each model captures a different aspect: DCF captures cash flow generation, DDM captures income return, Graham captures margin of safety, relative valuation captures market context, Monte Carlo captures uncertainty.

**Why median instead of mean for historical comparisons?**
IAM's 2024 was an anomalous year (P/E of 40x, ROE of 13.4%). Using the median filters out such outliers automatically.

**Why these model weights?**
DCF gets the highest weight (30%) because it is the most theoretically grounded. Relative valuation gets 25% because for a liquid stock like IAM, market multiples are informative. Graham gets only 10% because the formulas assume manufacturing-era capital structures that don't perfectly fit modern telecoms.

### Data Quality Handling

The system handles several real-world data challenges:

- **Mixed units**: Different MarketScreener pages report data in different denominations
- **Missing values**: Not all fields are populated for all years — models gracefully handle nulls
- **Outlier years**: 2024 was anomalous for IAM — median-based comparisons reduce its impact
- **Forecast vs actual**: Years 2021-2025 are historical; 2026-2028 are analyst estimates

---

*Built as part of the PFE (Projet de Fin d'Etudes) - AI Algorithmic Trading Agent for the Casablanca Stock Exchange*
