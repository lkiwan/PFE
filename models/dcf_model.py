"""Discounted Cash Flow (DCF) valuation model.

Uses projected Free Cash Flow and a terminal value to estimate
the intrinsic per-share value of the stock.
"""

import statistics
from typing import List, Tuple

from models.base_model import BaseValuationModel, ValuationResult
from utils.financial_constants import (
    RISK_FREE_RATE, EQUITY_RISK_PREMIUM, IAM_BETA,
    CORPORATE_TAX_RATE, TERMINAL_GROWTH_RATE, NUM_SHARES,
)


class DCFModel(BaseValuationModel):
    """Two-stage DCF with terminal value via Gordon Growth Model."""

    def calculate(self) -> ValuationResult:
        # 1. Compute WACC
        wacc = self._compute_wacc()

        # 2. Get projected FCF (millions MAD)
        fcf_projections = self._get_fcf_projections()
        if not fcf_projections:
            return ValuationResult(
                model_name="DCF",
                intrinsic_value=0,
                confidence=0,
                methodology="DCF — insufficient FCF data",
            )

        # 3. Extend projections to 5 years if needed
        fcf_projections = self._extend_projections(fcf_projections, years_total=5)

        # 4. Compute terminal value
        terminal_fcf = fcf_projections[-1]
        terminal_value = self._terminal_value(terminal_fcf, wacc, TERMINAL_GROWTH_RATE)

        # 5. Discount all cash flows
        enterprise_value = self._discount_cashflows(fcf_projections, terminal_value, wacc)

        # 6. Equity value per share
        net_debt = self._get_net_debt()
        cash = self._get_cash()
        equity_value = enterprise_value - net_debt + cash  # millions MAD
        per_share = (equity_value * 1_000_000) / NUM_SHARES

        # 7. Sensitivity analysis for range
        low = self._run_scenario(fcf_projections, wacc + 0.01, TERMINAL_GROWTH_RATE - 0.005,
                                 net_debt, cash)
        high = self._run_scenario(fcf_projections, wacc - 0.01, TERMINAL_GROWTH_RATE + 0.005,
                                  net_debt, cash)

        upside = self._compute_upside(per_share)

        # Confidence based on how much data we had
        confidence = min(80, 40 + len(fcf_projections) * 8)

        return ValuationResult(
            model_name="DCF",
            intrinsic_value=round(per_share, 2),
            intrinsic_value_low=round(low, 2),
            intrinsic_value_high=round(high, 2),
            upside_pct=round(upside, 1),
            confidence=confidence,
            methodology="Two-stage DCF with Gordon Growth terminal value",
            details={
                "wacc": round(wacc * 100, 2),
                "terminal_growth": round(TERMINAL_GROWTH_RATE * 100, 2),
                "enterprise_value_m": round(enterprise_value, 0),
                "net_debt_m": round(net_debt, 0),
                "fcf_projections": [round(f, 0) for f in fcf_projections],
            },
        )

    def _compute_wacc(self) -> float:
        """Weighted Average Cost of Capital."""
        cost_of_equity = RISK_FREE_RATE + IAM_BETA * EQUITY_RISK_PREMIUM

        # Get debt and equity values
        market_cap = self._get_valuation("market_cap") or 83_954  # millions MAD
        total_debt = self._get_financial("total_debt", "2025") or 19_603
        total_capital = market_cap + total_debt

        # Cost of debt: use a reasonable estimate for Moroccan corporate debt
        # (risk-free + credit spread of ~1.5-2%)
        cost_of_debt = RISK_FREE_RATE + 0.015  # ~5% for investment-grade Moroccan corporate

        weight_equity = market_cap / total_capital
        weight_debt = total_debt / total_capital

        wacc = (weight_equity * cost_of_equity +
                weight_debt * cost_of_debt * (1 - CORPORATE_TAX_RATE))
        return wacc

    def _get_fcf_projections(self) -> List[float]:
        """Get FCF projections in millions MAD."""
        fcf = self._get_hist_values("financials", "free_cash_flow")
        # Use forecast years (2026+)
        forecast_years = sorted(y for y in fcf if int(y) >= 2026)
        values = [fcf[y] for y in forecast_years if fcf[y] is not None and fcf[y] > 0]

        if values:
            return values

        # Fallback: derive from EBITDA, CapEx, tax
        ebitda = self._get_hist_values("financials", "ebitda")
        capex = self._get_hist_values("financials", "capex")
        for year in ["2025", "2024", "2023"]:
            eb = ebitda.get(year)
            cx = capex.get(year)
            if eb and cx:
                fcf_approx = eb * (1 - CORPORATE_TAX_RATE) - abs(cx)
                if fcf_approx > 0:
                    return [fcf_approx]
        return []

    def _extend_projections(self, fcf: List[float], years_total: int = 5) -> List[float]:
        """Extend FCF list to desired length using growth decay."""
        while len(fcf) < years_total:
            # Grow last value at a rate decaying toward terminal growth
            remaining = years_total - len(fcf)
            decay_rate = TERMINAL_GROWTH_RATE + 0.02 * (remaining / years_total)
            fcf.append(fcf[-1] * (1 + decay_rate))
        return fcf[:years_total]

    def _terminal_value(self, fcf_terminal: float, wacc: float, g: float) -> float:
        """Gordon Growth Model terminal value."""
        if wacc <= g:
            return fcf_terminal * 20  # Cap at 20x terminal FCF
        return fcf_terminal * (1 + g) / (wacc - g)

    def _discount_cashflows(self, fcfs: List[float], terminal_value: float,
                            wacc: float) -> float:
        """Present value of FCFs + terminal value (millions MAD)."""
        pv_fcf = sum(fcf / (1 + wacc) ** (i + 1) for i, fcf in enumerate(fcfs))
        pv_terminal = terminal_value / (1 + wacc) ** len(fcfs)
        return pv_fcf + pv_terminal

    def _get_net_debt(self) -> float:
        """Net debt in millions MAD."""
        nd = self._get_financial("net_debt", "2025")
        if nd and nd > 100:
            return nd
        # Derive: total_debt - cash
        debt = self._get_financial("total_debt", "2025") or 0
        cash = self._get_cash()
        return debt - cash

    def _get_cash(self) -> float:
        """Cash in millions MAD."""
        return self._get_financial("cash_and_equivalents", "2025") or 0

    def _run_scenario(self, fcf: List[float], wacc: float, g: float,
                      net_debt: float, cash: float) -> float:
        """Run a DCF scenario and return per-share value."""
        tv = self._terminal_value(fcf[-1], wacc, g)
        ev = self._discount_cashflows(fcf, tv, wacc)
        equity = ev - net_debt + cash
        return (equity * 1_000_000) / NUM_SHARES
