1. Stock Identity
   Ticker symbol (e.g., IAM)

Full company name

Exchange (e.g., Casablanca Stock Exchange)

Sector and industry

Market capitalization

Free float percentage

Currency

2. Price Data (Time-Series)
   Daily OHLCV: Open, High, Low, Close, Volume — minimum 2 years of history
   ​

Adjusted close price (post-dividend, post-split)

1-day, 5-day, 1-month, 3-month, 6-month, 1-year returns

52-week high and 52-week low

Distance from 52-week high (%)

Distance from 52-week low (%)

3. Technical Indicators
   Moving Averages: SMA 20, SMA 50, SMA 200, EMA 12, EMA 26

MACD line, Signal line, MACD histogram

RSI (14-day)

Bollinger Bands: Upper band, Lower band, Band width, %B

ATR — Average True Range (volatility proxy)

Stochastic Oscillator (%K, %D)

OBV — On-Balance Volume

VWAP — Volume Weighted Average Price

ADX — Average Directional Index (trend strength)

Ichimoku Cloud: Tenkan-sen, Kijun-sen, Senkou Span A & B

4. Volume & Liquidity
   Daily volume

Volume vs. 20-day average ratio

Volume vs. 50-day average ratio

Bid-ask spread

Average daily traded value in MAD

Days to liquidate position (float / avg volume)

5. Fundamental Financials
   Income Statement (annual + quarterly)

Revenue and revenue growth (YoY, QoQ)

EBITDA and EBITDA margin

Operating income (EBIT)

Net income and net income margin

EPS (Basic and Diluted)

EPS growth (YoY)

Balance Sheet

Total assets, total liabilities

Total equity

Net debt (Debt – Cash)

Net debt / EBITDA ratio

Current ratio, Quick ratio

Cash Flow

Operating cash flow

Capital expenditure (CapEx)

Free cash flow (FCF = Operating CF – CapEx)

FCF yield

FCF per share
​

6. Valuation Multiples
   P/E ratio (trailing and forward)

P/B ratio (Price to Book)

P/S ratio (Price to Sales)

EV/EBITDA

EV/Revenue

Dividend yield

Payout ratio

Calculated intrinsic value (DCF or DDM)

Upside / downside % vs. intrinsic value

Analyst consensus price target (if available)
​

7. Dividend Data
   Dividend per share (last paid)

Dividend per share (expected next)

Ex-dividend date

Dividend payment date

Dividend growth rate (3-year and 5-year CAGR)

Dividend stability score / history of cuts

8. Market & Sector Context
   MASI index daily return (benchmark)

Telecom sector index daily return

Stock beta (vs. MASI)

Relative strength vs. MASI (1M, 3M, 6M)

Relative strength vs. telecom peers

Correlation with MASI (rolling 60-day)

Global telecom sector trend signal (MSCI Telecom)
​

9. Risk Metrics
   Historical volatility: 10-day, 20-day, 60-day rolling

Maximum drawdown (1-year and 3-year)

Sharpe ratio (rolling 1-year)

Sortino ratio (rolling 1-year)

VaR 95% (Value at Risk, 1-day)

CVaR / Expected Shortfall

Model disagreement spread (range between valuation methods / base value %)
​

10. Analyst & Institutional Data
    Number of analysts covering the stock

Buy / Hold / Sell breakdown

Consensus price target

Highest and lowest price targets

Recent rating changes (upgrade / downgrade)

Institutional ownership %

Major shareholder changes (filings)
​

11. News & Sentiment
    Latest 10–20 news headlines with timestamps

Sentiment score per headline (Positive / Neutral / Negative)

Aggregate sentiment score (rolling 7-day)

Sentiment trend: improving or deteriorating

Key topics detected: earnings, regulation, capex, dividend, 5G, Africa operations

Social media or financial forum sentiment (if available)
​

12. Company-Specific Events Calendar
    Next earnings release date

Last earnings surprise (actual vs. expected EPS %)

Next dividend announcement date

AGM (General Assembly) date

Regulatory hearings or ANRT fine decisions

5G license / spectrum auction dates

M&A rumors or confirmed deals

Capex cycle phase (expansion vs. harvest)
​

13. Macroeconomic Context (Morocco)
    Bank Al-Maghrib policy rate

Morocco CPI (inflation)

USD/MAD and EUR/MAD exchange rates

Morocco GDP growth forecast

Morocco telecom penetration rate

Regulatory environment signal (ANRT decisions)
​

14. Prediction Target Definition
    Define exactly one target variable before building the model:

Short-term (1–5 days): Next-day direction (Up / Down / Flat), or next-5-day return

Medium-term (1 month): Probability of +5% gain within 30 days

Long-term (3–12 months): Probability of closing the intrinsic value gap, or annualized return bucket

15. Model Output Schema (what the agent should return)
    json
    {
    "prediction_target": "5-day direction",
    "signal": "BUY / HOLD / SELL",
    "confidence_score": 0.0–1.0,
    "price_target_low": ...,
    "price_target_mid": ...,
    "price_target_high": ...,
    "key_drivers": ["RSI oversold", "Earnings beat", "MASI uptrend"],
    "key_risks": ["High net debt", "Regulatory fine", "Model disagreement"],
    "valuation_methods_used": ["DCF", "DDM", "EV/EBITDA"],
    "data_freshness": "timestamp",
    "model_version": "v1.0"
    }
