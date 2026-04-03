"""Morocco-specific financial constants and sector benchmarks for IAM valuation."""

# --- Morocco Macro Parameters ---
RISK_FREE_RATE = 0.035          # Bank Al-Maghrib 10-year treasury bond yield (~3.5%)
EQUITY_RISK_PREMIUM = 0.065     # Emerging market equity risk premium
MARKET_RETURN = 0.10            # MASI historical average annual return (~8-10%)
CORPORATE_TAX_RATE = 0.31       # Morocco standard corporate tax rate
TERMINAL_GROWTH_RATE = 0.025    # Long-term perpetuity growth (GDP ~3%, inflation ~2%)

# --- IAM-Specific Parameters ---
IAM_BETA = 0.70                 # Defensive telecom, typically 0.6-0.8
NUM_SHARES = 879_031_000        # Total shares outstanding (879,031 thousands)

# --- Derived: Cost of Equity (CAPM) ---
# Cost_of_equity = Rf + Beta * ERP = 3.5% + 0.70 * 6.5% = 8.05%
COST_OF_EQUITY = RISK_FREE_RATE + IAM_BETA * EQUITY_RISK_PREMIUM

# --- Sector Benchmarks (Emerging Market Telecom) ---
SECTOR_BENCHMARKS = {
    "pe_ratio": 18.0,
    "ev_ebitda": 6.5,
    "ev_sales": 3.0,
    "price_to_book": 3.5,
    "dividend_yield": 4.0,       # %
    "roe": 20.0,                 # %
    "roa": 8.0,                  # %
    "net_margin": 15.0,          # %
    "ebitda_margin": 40.0,       # %
    "operating_margin": 25.0,    # %
    "debt_to_equity": 1.0,       # ratio
    "current_ratio": 1.0,        # ratio
}

# --- Scoring Thresholds ---
# For each factor sub-metric: (ideal_value, worst_value)
# Score is linearly interpolated between these bounds (0-100)
SCORING_THRESHOLDS = {
    # Value: lower is better for multiples
    "pe_vs_historical": (0.7, 1.5),        # ratio of current/historical median
    "ev_ebitda_vs_sector": (0.7, 1.5),
    "fcf_yield": (10.0, 0.0),              # higher is better (%)

    # Quality: higher is better
    "roe": (30.0, 5.0),                    # %
    "ebitda_margin": (55.0, 25.0),         # %
    "roce": (25.0, 5.0),                   # %
    "earnings_stability": (0.0, 1.0),      # coefficient of variation (lower = more stable)

    # Growth: higher is better
    "revenue_cagr": (8.0, -2.0),           # %
    "eps_growth": (15.0, -10.0),           # %
    "margin_expansion": (5.0, -5.0),       # pp change

    # Dividend: balanced
    "dividend_yield": (7.0, 0.0),          # %
    "payout_ratio": (70.0, 95.0),          # % — sweet spot ~60-70%, penalize >90%
    "dps_growth": (10.0, -5.0),            # %
    "yield_spread": (5.0, -1.0),           # % above risk-free

    # Safety: assess financial health
    "debt_to_equity": (0.3, 2.0),          # ratio (lower is better)
    "current_ratio": (2.0, 0.3),           # ratio (higher is better)
    "interest_coverage": (10.0, 1.5),      # ratio
    "fcf_positive_years": (5, 1),          # out of 5 years
}

# --- Model Weights for Final Recommendation ---
MODEL_WEIGHTS = {
    "dcf": 0.30,
    "ddm": 0.20,
    "relative": 0.25,
    "graham": 0.10,
    "monte_carlo": 0.15,
}

# --- Factor Weights for Composite Score ---
FACTOR_WEIGHTS = {
    "value": 0.25,
    "quality": 0.20,
    "growth": 0.20,
    "dividend": 0.15,
    "safety": 0.20,
}

# --- Recommendation Thresholds ---
RECOMMENDATION_RULES = {
    "STRONG BUY":  {"min_upside": 20, "min_score": 65},
    "BUY":         {"min_upside": 10, "min_score": 55},
    "HOLD":        {"min_upside": -10, "min_score": 0},
    "SELL":        {"max_upside": -10, "max_score": 45},
    "STRONG SELL": {"max_upside": -20, "max_score": 35},
}
