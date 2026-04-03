# 📂 Comprehensive Codebase Structure: PFE.0

This document provides a deep-dive map into every directory and file in the `PFE.0` project. It accurately describes what each piece of code does, where it gets its data, and what part of the pipeline it supports.

---

## 1. `agents/` (The AI Layer)
This folder manages the Artificial Intelligence that communicates the mathematical results to the user.
* **`advisor_agent.py`**: The main executable script. It constructs the Agno Agent using the Groq API (specifically the `llama-3.3-70b-versatile` model). It injects strict instructions so the AI acts as a quantitative hedge fund advisor.
* **`tools.py`**: Contains `get_iam_stock_advisory_context()`. This is the single "Tool" the AI is allowed to use. It runs the Python math engines in the background and returns a clean, formatted JSON payload (Intrinsic Value, Whale Activity, Risk Scores) directly to the LLM.

## 2. `scrapers/` (The Data Gatherers)
This folder contains the Object-Oriented web scraping tools that go out into the real world to fetch raw data.
* **`base_scraper.py`**: The parent logic. It handles setting up secure HTTP requests (via `aiohttp`) and initiating hidden web browsers (via `Selenium`). It also centralizes the Database connection logic using SQLAlchemy.
* **`financial_reports.py`**: Contains the `AMMCReportExtractor`. It takes Bilan and CPR (PDF files) published by the Moroccan AMMC, parses the grid layouts using Regex and `pdfplumber`, and extracts critical accounting metrics (Total Actif, Debt, etc.).
* **`market_data_scraper.py`**: 
  * `MasiScraper`: Connects to Investing.com using Selenium to bypass Cloudflare. Grabs the last 18 days of the absolute MASI index points.
  * `Medias24Scraper`: A lightweight `aiohttp` scraper that pulls the 18-day trading history (price/volume) of specifically requested Morrocan stocks.
* **`order_book_scraper.py`**: Contains `OrderBookScraper`. Uses Selenium to render Medias24's live Level 2 tables to capture active Bid and Ask limits.

## 3. `models/` (The Valuation Math)
This folder contains the 5 formal corporate finance models. Each receives data (from `data_normalizer.py`), runs the math, and returns exactly what the stock *should* be worth.
* **`base_model.py`**: Abstract foundation ensuring every standard model returns a common `calculation_results` dictionary.
* **`dcf_model.py`**: Discounted Cash Flow. Projects Free Cash Flow 5-years ahead using terminal growth rates, and discounts it back.
* **`ddm_model.py`**: Dividend Discount Model (Gordon Growth). Values the stock based exclusively on its expected growing dividend yields.
* **`graham_model.py`**: Benjamin Graham’s defensive formula. Examines strict Book Value and Earnings Per Share.
* **`relative_valuation.py`**: Values the stock by comparing its P/E and EV/EBITDA multiples against industry averages.
* **`monte_carlo.py`**: Runs 10,000 probabilistic, randomized simulations to generate a risk-adjusted "Confidence Interval" of the stock's price.

## 4. `strategies/` (The Grading & Trading Systems)
Translates the hard mathematical models into actionable signals (Scores out of 100 or BUY/SELL triggers). 
* **`scoring_engine.py`**: Tests fundamentals to output a 0-100 Score on 5 factors (Value, Quality, Growth, Safety, Dividend) and computes a final `Composite Score`.
* **`recommendation_engine.py`**: Takes the Intrinsic Value (from `models/`) and the Composite Score, calculates the upside percentage, and outputs a strict verdict (e.g. STRONG BUY vs SELL).
* **`whale_strategy.py`**: A pure momentum technical trading algorithm. It watches daily volume. If today's volume is >2.5x the average volume, it flags institutional "Whale" activity.
* **`hybrid_whale_strategy.py`**: The Master Module. It blocks trades unless **BOTH** conditions exist: (1) True Whale accumulate, and (2) Fundamental score >= 50/100.
* **`news_sentiment.py`**: Calculates a basic sentiment score based on scraped MarketScreener news headlines.

## 5. `backtest/` (Historical Simulation)
Contains a custom-built, highly accurate portfolio simulator to test the strategies on historical data.
* **`data_loader.py`**: Parses the deeply flawed French/Moroccan CSV files (handling commas, periods, and the 'K', 'M' suffixes) and loads them into memory.
* **`signal_generator.py`**: Prevents "look-ahead bias" by acting as a time machine, ensuring the AI only feeds 2022 financials into the engine while trading the 2023 calendar year.
* **`engine.py`**: The actual Paper Portfolio. Executes trades requested by the signals, strictly deducting 0.3% commission fees on every buy/sell, and tracks cash balances.
* **`metrics.py`**: Calculates professional Wall Street metrics on the Portfolio's returns: CAGR, Sharpe Ratio, Sortino Ratio, and Max Drawdown.
* **`parameter_sensitivity.py`**: A grid-search loop that tests hundreds of volume thresholds to find the mathematically optimal parameters.
* **`report.py`**: Uses `plotly` to render a beautiful, self-contained HTML visual report of the backtest (equity curve, drawdowns, factor history).
* **`run_backtest.py`, `run_whale_backtest.py`, `run_hybrid_backtest.py`**: The CLI entry points you execute to actually start the simulations.

## 6. `core/` & `utils/` (The Piping)
* **`core/data_normalizer.py`**: Standardizes currency units. MarketScreener gives some data in 'Thousands' and some in raw numbers. This script mathematically ensures the Models don't crash from unit mismatch.
* **`utils/financial_constants.py`**: Stores all the core macro-economic standards the math relies on (e.g., Risk-Free Rate = 3.2%, Equity Risk Premium = 6.0%).

## 7. `testing/` & `IAM/` (Raw Source Datasets)
* **`testing/scraper.py`**: The original MarketScreener massive extraction script. Gathers the 300+ financial variables you saw.
* **`testing/testing/stock_data.json`**: The final output payload containing all the fundamental statistics.
* **`IAM/IAM - Données Historiques dayli P.1.csv`**: The raw exports of everyday trading activity (Open, High, Low, Close, Volume) used by the whale strategy.

---

### TL;DR Summary
1. `scrapers/` gets the data from the internet.
2. The data lands in `testing/` (Fundamentals) and `IAM/` (Prices).
3. `core/` cleans it up.
4. `models/` runs absolute valuations.
5. `strategies/` tests for Whale momentum and Composite Quality.
6. `backtest/` proves the logic historically.
7. `agents/advisor_agent.py` takes the final results, sends them to Groq AI, and writes the Advisory Report.
