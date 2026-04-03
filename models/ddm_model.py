"""Dividend Discount Model (DDM) valuation.

Multi-stage DDM particularly suited for IAM as a consistent
dividend payer (~70% payout ratio, ~4.5% yield).
"""

from typing import List

from models.base_model import BaseValuationModel, ValuationResult
from utils.financial_constants import (
    COST_OF_EQUITY, TERMINAL_GROWTH_RATE, RISK_FREE_RATE,
)


class DDMModel(BaseValuationModel):
    """Three-stage Dividend Discount Model."""

    def calculate(self) -> ValuationResult:
        cost_of_equity = COST_OF_EQUITY  # 8.05%

        # Stage 1: Explicit dividend forecasts (2026-2028)
        stage1_divs = self._get_stage1_dividends()
        if not stage1_divs:
            return ValuationResult(
                model_name="DDM",
                intrinsic_value=0,
                confidence=0,
                methodology="DDM — insufficient dividend data",
            )

        # Stage 2: Transition period (2029-2033) — decay growth to terminal
        stage1_growth = self._compute_div_growth(stage1_divs)
        stage2_divs = self._project_stage2(stage1_divs[-1], stage1_growth, years=5)

        # Stage 3: Terminal value using Gordon Growth
        terminal_div = stage2_divs[-1] * (1 + TERMINAL_GROWTH_RATE)
        if cost_of_equity <= TERMINAL_GROWTH_RATE:
            terminal_value = terminal_div * 30
        else:
            terminal_value = terminal_div / (cost_of_equity - TERMINAL_GROWTH_RATE)

        # Discount all dividends to present
        all_divs = stage1_divs + stage2_divs
        total_years = len(all_divs)

        pv_dividends = sum(
            d / (1 + cost_of_equity) ** (i + 1)
            for i, d in enumerate(all_divs)
        )
        pv_terminal = terminal_value / (1 + cost_of_equity) ** total_years

        fair_value = pv_dividends + pv_terminal

        # Sensitivity: cost of equity +/- 1%
        low = self._run_scenario(all_divs, cost_of_equity + 0.01)
        high = self._run_scenario(all_divs, cost_of_equity - 0.01)

        upside = self._compute_upside(fair_value)
        confidence = min(75, 35 + len(stage1_divs) * 10)

        return ValuationResult(
            model_name="DDM",
            intrinsic_value=round(fair_value, 2),
            intrinsic_value_low=round(low, 2),
            intrinsic_value_high=round(high, 2),
            upside_pct=round(upside, 1),
            confidence=confidence,
            methodology="Three-stage DDM (explicit + transition + terminal)",
            details={
                "cost_of_equity_pct": round(cost_of_equity * 100, 2),
                "stage1_dividends": [round(d, 2) for d in stage1_divs],
                "stage1_growth_pct": round(stage1_growth * 100, 2),
                "terminal_growth_pct": round(TERMINAL_GROWTH_RATE * 100, 2),
                "pv_dividends": round(pv_dividends, 2),
                "pv_terminal": round(pv_terminal, 2),
            },
        )

    def _get_stage1_dividends(self) -> List[float]:
        """Get explicit dividend per share forecasts."""
        dps_hist = self._get_hist_values("valuation", "dividend_per_share_hist")
        forecast_years = sorted(y for y in dps_hist if int(y) >= 2026)
        divs = [dps_hist[y] for y in forecast_years if dps_hist[y] is not None and dps_hist[y] > 0]

        if divs:
            return divs

        # Fallback: use most recent dividend and assume stable
        recent = sorted(dps_hist.keys(), reverse=True)
        for y in recent:
            if dps_hist[y] and dps_hist[y] > 0:
                return [dps_hist[y]]
        return []

    def _compute_div_growth(self, divs: List[float]) -> float:
        """Compute average growth rate from a dividend series."""
        if len(divs) < 2:
            return TERMINAL_GROWTH_RATE
        growth_rates = []
        for i in range(1, len(divs)):
            if divs[i - 1] > 0:
                growth_rates.append((divs[i] - divs[i - 1]) / divs[i - 1])
        if growth_rates:
            return sum(growth_rates) / len(growth_rates)
        return TERMINAL_GROWTH_RATE

    def _project_stage2(self, last_div: float, initial_growth: float,
                        years: int = 5) -> List[float]:
        """Project dividends with growth decaying linearly to terminal rate."""
        divs = []
        for i in range(years):
            # Linear interpolation from initial_growth to terminal_growth
            weight = (i + 1) / years
            growth = initial_growth * (1 - weight) + TERMINAL_GROWTH_RATE * weight
            last_div = last_div * (1 + growth)
            divs.append(last_div)
        return divs

    def _run_scenario(self, all_divs: List[float], cost_of_equity: float) -> float:
        """Run DDM with a different cost of equity."""
        pv = sum(d / (1 + cost_of_equity) ** (i + 1) for i, d in enumerate(all_divs))
        terminal_div = all_divs[-1] * (1 + TERMINAL_GROWTH_RATE)
        if cost_of_equity <= TERMINAL_GROWTH_RATE:
            tv = terminal_div * 30
        else:
            tv = terminal_div / (cost_of_equity - TERMINAL_GROWTH_RATE)
        pv_tv = tv / (1 + cost_of_equity) ** len(all_divs)
        return pv + pv_tv
