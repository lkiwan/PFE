"""Monte Carlo simulation for probabilistic valuation.

Runs 10,000 iterations of a simplified DCF, sampling key inputs
from probability distributions to produce a fair value distribution.
"""

import numpy as np
from typing import Dict

from models.base_model import BaseValuationModel, ValuationResult
from utils.financial_constants import (
    RISK_FREE_RATE, IAM_BETA, EQUITY_RISK_PREMIUM,
    CORPORATE_TAX_RATE, NUM_SHARES,
)


class MonteCarloModel(BaseValuationModel):
    """Monte Carlo DCF simulation."""

    N_SIMULATIONS = 10_000
    FORECAST_YEARS = 5

    def calculate(self) -> ValuationResult:
        # Get base-case inputs from data
        base_revenue = self._get_base_revenue()
        base_ebitda_margin = self._get_base_margin()
        base_capex_ratio = self._get_capex_ratio()
        net_debt = self._get_net_debt()
        cash = self._get_cash()

        if not base_revenue or not base_ebitda_margin:
            return ValuationResult(
                model_name="Monte Carlo",
                intrinsic_value=0,
                confidence=0,
                methodology="Monte Carlo — insufficient base data",
            )

        # Define distributions for uncertain parameters
        np.random.seed(42)  # Reproducibility

        # Revenue growth: Normal(1.5%, 2.0%)
        rev_growth = np.random.normal(0.015, 0.020, self.N_SIMULATIONS)

        # EBITDA margin: Normal(base_margin, 5pp)
        margin = np.random.normal(base_ebitda_margin / 100, 0.05, self.N_SIMULATIONS)
        margin = np.clip(margin, 0.15, 0.70)  # Sensible bounds

        # WACC: Uniform(6.5%, 9.5%)
        wacc = np.random.uniform(0.065, 0.095, self.N_SIMULATIONS)

        # Terminal growth: Uniform(1.5%, 3.5%)
        terminal_g = np.random.uniform(0.015, 0.035, self.N_SIMULATIONS)

        # CapEx as % of revenue: Normal(base_ratio, 2pp)
        capex_pct = np.random.normal(base_capex_ratio, 0.02, self.N_SIMULATIONS)
        capex_pct = np.clip(capex_pct, 0.05, 0.30)

        # Run simulations
        fair_values = np.zeros(self.N_SIMULATIONS)

        for i in range(self.N_SIMULATIONS):
            fair_values[i] = self._simulate_dcf(
                base_revenue=base_revenue,
                rev_growth=rev_growth[i],
                ebitda_margin=margin[i],
                capex_pct=capex_pct[i],
                wacc=wacc[i],
                terminal_g=terminal_g[i],
                net_debt=net_debt,
                cash=cash,
            )

        # Filter out unreasonable values
        fair_values = fair_values[(fair_values > 0) & (fair_values < 1000)]

        if len(fair_values) == 0:
            return ValuationResult(
                model_name="Monte Carlo",
                intrinsic_value=0,
                confidence=0,
                methodology="Monte Carlo — all simulations produced invalid results",
            )

        median_value = float(np.median(fair_values))
        p10 = float(np.percentile(fair_values, 10))
        p90 = float(np.percentile(fair_values, 90))
        mean_value = float(np.mean(fair_values))

        price = self._current_price()
        prob_above_price = float(np.mean(fair_values > price)) * 100

        upside = self._compute_upside(median_value)

        # Confidence: based on distribution tightness
        cv = float(np.std(fair_values) / np.mean(fair_values))  # Coefficient of variation
        confidence = max(30, min(75, 75 - cv * 100))

        return ValuationResult(
            model_name="Monte Carlo",
            intrinsic_value=round(median_value, 2),
            intrinsic_value_low=round(p10, 2),
            intrinsic_value_high=round(p90, 2),
            upside_pct=round(upside, 1),
            confidence=round(confidence, 0),
            methodology=f"Monte Carlo DCF ({self.N_SIMULATIONS:,} simulations)",
            details={
                "median": round(median_value, 2),
                "mean": round(mean_value, 2),
                "p10_bear": round(p10, 2),
                "p25": round(float(np.percentile(fair_values, 25)), 2),
                "p75": round(float(np.percentile(fair_values, 75)), 2),
                "p90_bull": round(p90, 2),
                "prob_above_current_price_pct": round(prob_above_price, 1),
                "valid_simulations": len(fair_values),
                "base_revenue_m": round(base_revenue, 0),
                "base_ebitda_margin_pct": round(base_ebitda_margin, 1),
            },
        )

    def _simulate_dcf(self, base_revenue: float, rev_growth: float,
                      ebitda_margin: float, capex_pct: float,
                      wacc: float, terminal_g: float,
                      net_debt: float, cash: float) -> float:
        """Run a single DCF iteration. Returns per-share value."""
        revenue = base_revenue
        fcfs = []

        for year in range(self.FORECAST_YEARS):
            revenue *= (1 + rev_growth)
            ebitda = revenue * ebitda_margin
            capex = revenue * capex_pct
            # Simplified FCF: EBITDA * (1 - tax) - CapEx
            fcf = ebitda * (1 - CORPORATE_TAX_RATE) - capex
            fcfs.append(fcf)

        # Terminal value
        terminal_fcf = fcfs[-1]
        if wacc <= terminal_g:
            tv = terminal_fcf * 20
        else:
            tv = terminal_fcf * (1 + terminal_g) / (wacc - terminal_g)

        # Discount
        pv_fcf = sum(f / (1 + wacc) ** (i + 1) for i, f in enumerate(fcfs))
        pv_tv = tv / (1 + wacc) ** self.FORECAST_YEARS

        ev = pv_fcf + pv_tv  # millions MAD
        equity = ev - net_debt + cash
        per_share = (equity * 1_000_000) / NUM_SHARES

        return per_share

    def _get_base_revenue(self) -> float:
        """Get most recent revenue in millions MAD."""
        sales = self._get_hist_values("financials", "net_sales")
        for year in ["2025", "2024", "2023"]:
            if year in sales and sales[year]:
                return sales[year]
        return 0

    def _get_base_margin(self) -> float:
        """Get most recent EBITDA margin (%)."""
        margins = self._get_hist_values("financials", "ebitda_margin")
        for year in ["2025", "2024", "2023"]:
            if year in margins and margins[year]:
                return margins[year]
        return 45.0  # Default telecom margin

    def _get_capex_ratio(self) -> float:
        """Get CapEx as fraction of revenue."""
        capex = self._get_hist_values("financials", "capex")
        sales = self._get_hist_values("financials", "net_sales")
        ratios = []
        for year in ["2023", "2024", "2025"]:
            c = capex.get(year)
            s = sales.get(year)
            if c and s and s > 0:
                ratio = abs(c) / s
                if 0.01 < ratio < 0.50:
                    ratios.append(ratio)
        if ratios:
            return sum(ratios) / len(ratios)
        return 0.15  # Default 15% for telecom

    def _get_net_debt(self) -> float:
        """Net debt in millions MAD."""
        nd = self._get_financial("net_debt", "2025")
        if nd and nd > 100:
            return nd
        debt = self._get_financial("total_debt", "2025") or 0
        cash = self._get_cash()
        return debt - cash

    def _get_cash(self) -> float:
        return self._get_financial("cash_and_equivalents", "2025") or 0
