"""Multi-factor scoring engine.

Evaluates a stock across 5 dimensions (Value, Quality, Growth, Dividend, Safety),
each scored 0-100, combined into a weighted composite score.
"""

import statistics
from typing import Dict, Optional, List

from utils.financial_constants import (
    SECTOR_BENCHMARKS, SCORING_THRESHOLDS, FACTOR_WEIGHTS, RISK_FREE_RATE,
)


class ScoringEngine:
    """Score a stock across value, quality, growth, dividend, and safety factors."""

    def __init__(self, stock_data: dict):
        self.data = stock_data
        self.fin = stock_data.get("financials", {})
        self.val = stock_data.get("valuation", {})
        self.price = stock_data.get("price_performance", {})

    def score(self) -> Dict[str, float]:
        """Run all factor scores and return composite."""
        scores = {
            "value": self._score_value(),
            "quality": self._score_quality(),
            "growth": self._score_growth(),
            "dividend": self._score_dividend(),
            "safety": self._score_safety(),
        }

        composite = sum(
            scores[f] * FACTOR_WEIGHTS[f] for f in scores
        )
        scores["composite"] = round(composite, 1)

        return scores

    # ---- Value Factor ----

    def _score_value(self) -> float:
        sub_scores = []

        # P/E vs historical median
        pe_hist = self._hist_values("valuation", "pe_ratio_hist",
                                     ["2021", "2022", "2023", "2024", "2025"])
        current_pe = self.val.get("pe_ratio")
        if pe_hist and current_pe:
            median_pe = statistics.median(pe_hist)
            ratio = current_pe / median_pe
            sub_scores.append(self._linear_score(ratio, *SCORING_THRESHOLDS["pe_vs_historical"]))

        # EV/EBITDA vs sector
        ev_ebitda = self.val.get("ev_ebitda")
        if ev_ebitda:
            ratio = ev_ebitda / SECTOR_BENCHMARKS["ev_ebitda"]
            sub_scores.append(self._linear_score(ratio, *SCORING_THRESHOLDS["ev_ebitda_vs_sector"]))

        # FCF yield
        fcf_yield = self._hist_values("valuation", "fcf_yield_hist", ["2025"])
        if fcf_yield:
            sub_scores.append(self._linear_score(fcf_yield[0], *SCORING_THRESHOLDS["fcf_yield"]))

        return round(self._avg(sub_scores), 1) if sub_scores else 50.0

    # ---- Quality Factor ----

    def _score_quality(self) -> float:
        sub_scores = []

        # ROE level
        roe_vals = self._hist_values("financials", "roe", ["2021", "2022", "2023", "2024", "2025"])
        if roe_vals:
            avg_roe = statistics.mean(roe_vals)
            sub_scores.append(self._linear_score(avg_roe, *SCORING_THRESHOLDS["roe"]))

            # Earnings stability (coefficient of variation of ROE)
            if len(roe_vals) >= 3:
                cv = statistics.stdev(roe_vals) / abs(avg_roe) if avg_roe != 0 else 1
                sub_scores.append(self._linear_score(cv, *SCORING_THRESHOLDS["earnings_stability"]))

        # EBITDA margin
        margin_vals = self._hist_values("financials", "ebitda_margin",
                                         ["2021", "2022", "2023", "2024", "2025"])
        if margin_vals:
            avg_margin = statistics.mean(margin_vals)
            sub_scores.append(self._linear_score(avg_margin, *SCORING_THRESHOLDS["ebitda_margin"]))

        # ROCE
        roce_vals = self._hist_values("financials", "roce", ["2021", "2022", "2023", "2024", "2025"])
        if roce_vals:
            avg_roce = statistics.mean(roce_vals)
            sub_scores.append(self._linear_score(avg_roce, *SCORING_THRESHOLDS["roce"]))

        return round(self._avg(sub_scores), 1) if sub_scores else 50.0

    # ---- Growth Factor ----

    def _score_growth(self) -> float:
        sub_scores = []

        # Revenue CAGR
        sales = self._get_dict("financials", "net_sales")
        if len(sales) >= 2:
            years = sorted(sales.keys())
            first, last = sales[years[0]], sales[years[-1]]
            n = int(years[-1]) - int(years[0])
            if first and first > 0 and n > 0:
                cagr = ((last / first) ** (1 / n) - 1) * 100
                sub_scores.append(self._linear_score(cagr, *SCORING_THRESHOLDS["revenue_cagr"]))

        # EPS growth (latest vs 2 years prior)
        eps = self._get_dict("financials", "eps")
        if len(eps) >= 2:
            years = sorted(eps.keys())
            recent = eps[years[-1]]
            older = eps[years[0]]
            if older and older > 0:
                growth = ((recent / older) ** (1 / max(1, int(years[-1]) - int(years[0]))) - 1) * 100
                sub_scores.append(self._linear_score(growth, *SCORING_THRESHOLDS["eps_growth"]))

        # Margin expansion: compare 2025 estimate vs 2023 actual
        margin_2025 = self._get_val("financials", "ebitda_margin", "2025")
        margin_2023 = self._get_val("financials", "ebitda_margin", "2023")
        if margin_2025 is not None and margin_2023 is not None:
            expansion = margin_2025 - margin_2023
            sub_scores.append(self._linear_score(expansion, *SCORING_THRESHOLDS["margin_expansion"]))

        return round(self._avg(sub_scores), 1) if sub_scores else 50.0

    # ---- Dividend Factor ----

    def _score_dividend(self) -> float:
        sub_scores = []

        # Current dividend yield
        div_yield = self.val.get("dividend_yield")
        if div_yield:
            sub_scores.append(self._linear_score(div_yield, *SCORING_THRESHOLDS["dividend_yield"]))

            # Yield spread vs risk-free rate
            spread = div_yield - RISK_FREE_RATE * 100
            sub_scores.append(self._linear_score(spread, *SCORING_THRESHOLDS["yield_spread"]))

        # Payout ratio sustainability
        dist_rates = self._hist_values("valuation", "distribution_rate_hist",
                                        ["2021", "2022", "2023", "2024"])
        if dist_rates:
            avg_payout = statistics.mean(dist_rates)
            # Score: 60-75% is ideal, penalize above 90%
            sub_scores.append(self._linear_score(avg_payout, *SCORING_THRESHOLDS["payout_ratio"]))

        # DPS growth
        dps = self._get_dict("valuation", "dividend_per_share_hist")
        if len(dps) >= 2:
            years = sorted(dps.keys())
            first, last = dps[years[0]], dps[years[-1]]
            n = int(years[-1]) - int(years[0])
            if first and first > 0 and n > 0:
                growth = ((last / first) ** (1 / n) - 1) * 100
                sub_scores.append(self._linear_score(growth, *SCORING_THRESHOLDS["dps_growth"]))

        return round(self._avg(sub_scores), 1) if sub_scores else 50.0

    # ---- Safety Factor ----

    def _score_safety(self) -> float:
        sub_scores = []

        # Debt to equity
        de_vals = self._hist_values("financials", "debt_to_equity", ["2024", "2025"])
        if de_vals:
            latest_de = de_vals[-1]
            # debt_to_equity from data might be a ratio or percentage
            # If > 5, it's likely a percentage representation
            if latest_de > 5:
                latest_de = latest_de / 100
            sub_scores.append(self._linear_score(latest_de, *SCORING_THRESHOLDS["debt_to_equity"]))

        # Current ratio
        cr_vals = self._hist_values("financials", "current_ratio", ["2024", "2025"])
        if cr_vals:
            sub_scores.append(self._linear_score(cr_vals[-1], *SCORING_THRESHOLDS["current_ratio"]))

        # Interest coverage (EBIT / interest expense)
        ebit = self._get_val("financials", "ebit", "2025")
        interest = self._get_val("financials", "interest_expense_approx", "2025")
        if ebit and interest and interest > 0:
            coverage = ebit / interest
            sub_scores.append(self._linear_score(coverage, *SCORING_THRESHOLDS["interest_coverage"]))

        # FCF positive years out of 5
        fcf = self._get_dict("financials", "free_cash_flow")
        if fcf:
            positive_years = sum(1 for v in fcf.values() if v and v > 0)
            total = len(fcf)
            if total > 0:
                sub_scores.append(self._linear_score(
                    positive_years, *SCORING_THRESHOLDS["fcf_positive_years"]))

        return round(self._avg(sub_scores), 1) if sub_scores else 50.0

    # ---- Helpers ----

    def _linear_score(self, value: float, ideal: float, worst: float) -> float:
        """Map a value to 0-100 using linear interpolation between ideal and worst."""
        if ideal == worst:
            return 50.0
        score = (value - worst) / (ideal - worst) * 100
        return max(0, min(100, score))

    def _avg(self, scores: List[float]) -> float:
        return sum(scores) / len(scores) if scores else 50.0

    def _hist_values(self, section: str, field: str, years: List[str]) -> List[float]:
        """Get values for specified years from a section."""
        data = self.data.get(section, {}).get(field, {})
        if not isinstance(data, dict):
            return []
        return [data[y] for y in years if y in data and data[y] is not None]

    def _get_dict(self, section: str, field: str) -> Dict[str, float]:
        """Get a dict field, filtering nulls."""
        data = self.data.get(section, {}).get(field, {})
        if isinstance(data, dict):
            return {k: v for k, v in data.items() if v is not None}
        return {}

    def _get_val(self, section: str, field: str, year: str) -> Optional[float]:
        data = self.data.get(section, {}).get(field, {})
        if isinstance(data, dict):
            return data.get(year)
        return None
