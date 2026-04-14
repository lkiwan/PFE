# Scoring Engine — How Scores Are Calculated

## The Formula

```
Composite = Value × 0.25 + Quality × 0.20 + Growth × 0.20 + Safety × 0.20 + Dividend × 0.15
```

Each factor is scored **0-100** using **linear interpolation** between an "ideal" and "worst" value:

```
score = (value - worst) / (ideal - worst) × 100    clamped to [0, 100]
```

Within each factor, sub-metrics are **averaged** (equal weight). If data is missing for a sub-metric, it's skipped — only available sub-metrics count.

---

## 1. Value Score (25% weight)

*Is the stock cheap?*

| Sub-metric | What it measures | Ideal → 100 | Worst → 0 |
|------------|-----------------|-------------|-----------|
| P/E vs historical median | Current P/E ÷ median P/E (2021-2025) | 0.7× (cheap) | 1.5× (expensive) |
| EV/EBITDA vs sector | Current EV/EBITDA ÷ sector benchmark (6.5) | 0.7× | 1.5× |
| FCF Yield | Free cash flow yield % | 10% | 0% |

---

## 2. Quality Score (20% weight)

*Is the business strong?*

| Sub-metric | What it measures | Ideal → 100 | Worst → 0 |
|------------|-----------------|-------------|-----------|
| ROE | Avg return on equity (2021-2025) | 30% | 5% |
| EBITDA Margin | Avg EBITDA margin (2021-2025) | 55% | 25% |
| ROCE | Avg return on capital employed | 25% | 5% |
| Earnings Stability | Coefficient of variation of ROE (lower = more stable) | 0.0 | 1.0 |

---

## 3. Growth Score (20% weight)

*Is the company growing?*

| Sub-metric | What it measures | Ideal → 100 | Worst → 0 |
|------------|-----------------|-------------|-----------|
| Revenue CAGR | Compound annual growth rate of revenue | 8% | -2% |
| EPS Growth | Annualized EPS growth (first to last year) | 15% | -10% |
| Margin Expansion | EBITDA margin 2025 minus 2023 (pp change) | +5pp | -5pp |

---

## 4. Dividend Score (15% weight)

*Is the dividend attractive and sustainable?*

| Sub-metric | What it measures | Ideal → 100 | Worst → 0 |
|------------|-----------------|-------------|-----------|
| Dividend Yield | Current yield | 7% | 0% |
| Yield Spread | Yield minus risk-free rate (2.87%) | +5pp | -1pp |
| Payout Ratio | Avg distribution rate (sweet spot ~70%) | 70% | 95% |
| DPS Growth | Dividend per share CAGR | 10% | -5% |

---

## 5. Safety Score (20% weight)

*Is the balance sheet healthy?*

| Sub-metric | What it measures | Ideal → 100 | Worst → 0 |
|------------|-----------------|-------------|-----------|
| Debt/Equity | Latest D/E ratio (lower = safer) | 0.3 | 2.0 |
| Current Ratio | Liquidity ratio (higher = safer) | 2.0 | 0.3 |
| Interest Coverage | EBIT ÷ interest expense | 10× | 1.5× |
| FCF Positive Years | How many years had positive free cash flow | 5/5 | 1/5 |

---

## Example Calculation

If a stock has: Value=72, Quality=70, Growth=63, Safety=58, Dividend=60:

```
Composite = 72 × 0.25 + 70 × 0.20 + 63 × 0.20 + 58 × 0.20 + 60 × 0.15
          = 18.0 + 14.0 + 12.6 + 11.6 + 9.0
          = 65.2 / 100
```

---

## Source Code

- Scoring Engine: `strategies/scoring_engine.py`
- Constants & Thresholds: `utils/financial_constants.py`
- Sector Benchmarks: P/E=18, EV/EBITDA=6.5, ROE=20%, EBITDA Margin=40%, D/E=1.0
