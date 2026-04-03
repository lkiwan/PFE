"""Relative valuation using historical and sector multiples.

Compares current multiples (P/E, EV/EBITDA, P/B, EV/Revenue) against:
1. The stock's own historical median (mean-reversion thesis)
2. Sector benchmark averages
"""

import statistics
from typing import Dict, Optional, List

from models.base_model import BaseValuationModel, ValuationResult
from utils.financial_constants import SECTOR_BENCHMARKS, NUM_SHARES


class RelativeValuationModel(BaseValuationModel):
    """Multiples-based relative valuation."""

    # Weight each implied fair value in the composite
    MULTIPLE_WEIGHTS = {
        "pe": 0.25,
        "ev_ebitda": 0.35,      # Most reliable for telecoms
        "pb": 0.15,
        "ev_revenue": 0.10,
        "fcf_yield": 0.15,
    }

    def calculate(self) -> ValuationResult:
        price = self._current_price()
        implied_values = {}
        details = {}

        # 1. P/E-based fair value
        pe_fv = self._pe_fair_value()
        if pe_fv:
            implied_values["pe"] = pe_fv["value"]
            details["pe"] = pe_fv

        # 2. EV/EBITDA-based fair value
        ev_ebitda_fv = self._ev_ebitda_fair_value()
        if ev_ebitda_fv:
            implied_values["ev_ebitda"] = ev_ebitda_fv["value"]
            details["ev_ebitda"] = ev_ebitda_fv

        # 3. P/B-based fair value
        pb_fv = self._pb_fair_value()
        if pb_fv:
            implied_values["pb"] = pb_fv["value"]
            details["pb"] = pb_fv

        # 4. EV/Revenue-based fair value
        ev_rev_fv = self._ev_revenue_fair_value()
        if ev_rev_fv:
            implied_values["ev_revenue"] = ev_rev_fv["value"]
            details["ev_revenue"] = ev_rev_fv

        # 5. FCF yield implied value
        fcf_fv = self._fcf_yield_fair_value()
        if fcf_fv:
            implied_values["fcf_yield"] = fcf_fv["value"]
            details["fcf_yield"] = fcf_fv

        if not implied_values:
            return ValuationResult(
                model_name="Relative Valuation",
                intrinsic_value=0,
                confidence=0,
                methodology="Relative — insufficient multiples data",
            )

        # Weighted composite fair value
        total_weight = sum(
            self.MULTIPLE_WEIGHTS.get(k, 0) for k in implied_values
        )
        composite = sum(
            implied_values[k] * self.MULTIPLE_WEIGHTS.get(k, 0)
            for k in implied_values
        ) / total_weight

        all_values = list(implied_values.values())
        low_val = min(all_values)
        high_val = max(all_values)

        upside = self._compute_upside(composite)
        confidence = min(80, 30 + len(implied_values) * 10)

        return ValuationResult(
            model_name="Relative Valuation",
            intrinsic_value=round(composite, 2),
            intrinsic_value_low=round(low_val, 2),
            intrinsic_value_high=round(high_val, 2),
            upside_pct=round(upside, 1),
            confidence=confidence,
            methodology="Weighted composite of historical and sector multiples",
            details=details,
        )

    def _pe_fair_value(self) -> Optional[dict]:
        """Fair value based on P/E ratio."""
        pe_hist = self._get_hist_values("valuation", "pe_ratio_hist",
                                         years=["2021", "2022", "2023", "2024", "2025"])
        if not pe_hist:
            return None

        hist_median = statistics.median(pe_hist.values())
        sector_pe = SECTOR_BENCHMARKS["pe_ratio"]

        # Use blend: 60% historical median, 40% sector
        blended_pe = hist_median * 0.6 + sector_pe * 0.4

        eps = self._get_latest_eps()
        if not eps or eps <= 0:
            return None

        fair_value = blended_pe * eps

        return {
            "value": round(fair_value, 2),
            "historical_median_pe": round(hist_median, 1),
            "sector_pe": sector_pe,
            "blended_pe": round(blended_pe, 1),
            "eps_used": round(eps, 2),
        }

    def _ev_ebitda_fair_value(self) -> Optional[dict]:
        """Fair value based on EV/EBITDA."""
        ev_ebitda_hist = self._get_hist_values("valuation", "ev_ebitda_hist",
                                                years=["2021", "2022", "2023", "2024", "2025"])
        if not ev_ebitda_hist:
            return None

        hist_median = statistics.median(ev_ebitda_hist.values())
        sector_ev = SECTOR_BENCHMARKS["ev_ebitda"]
        blended = hist_median * 0.6 + sector_ev * 0.4

        ebitda = self._get_financial("ebitda", "2025")
        net_debt = self._get_financial("net_debt", "2025") or 0
        cash = self._get_financial("cash_and_equivalents", "2025") or 0

        if not ebitda or ebitda <= 0:
            return None

        # EV = multiple * EBITDA; Equity = EV - net_debt + cash
        implied_ev = blended * ebitda
        equity_value = implied_ev - net_debt + cash
        per_share = (equity_value * 1_000_000) / NUM_SHARES

        return {
            "value": round(per_share, 2),
            "historical_median": round(hist_median, 2),
            "sector_benchmark": sector_ev,
            "blended_multiple": round(blended, 2),
            "ebitda_used": round(ebitda, 0),
        }

    def _pb_fair_value(self) -> Optional[dict]:
        """Fair value based on Price-to-Book."""
        pb_hist = self._get_hist_values("valuation", "pbr_hist",
                                         years=["2021", "2022", "2023", "2024", "2025"])
        if not pb_hist:
            return None

        hist_median = statistics.median(pb_hist.values())
        sector_pb = SECTOR_BENCHMARKS["price_to_book"]
        blended = hist_median * 0.6 + sector_pb * 0.4

        bvps = self._get_book_value_per_share()
        if not bvps or bvps <= 0:
            return None

        fair_value = blended * bvps

        return {
            "value": round(fair_value, 2),
            "historical_median_pb": round(hist_median, 2),
            "sector_pb": sector_pb,
            "bvps_used": round(bvps, 2),
        }

    def _ev_revenue_fair_value(self) -> Optional[dict]:
        """Fair value based on EV/Revenue."""
        ev_rev_hist = self._get_hist_values("valuation", "ev_revenue_hist",
                                             years=["2021", "2022", "2023", "2024", "2025"])
        if not ev_rev_hist:
            return None

        hist_median = statistics.median(ev_rev_hist.values())
        sector_ev_rev = SECTOR_BENCHMARKS["ev_sales"]
        blended = hist_median * 0.6 + sector_ev_rev * 0.4

        revenue = self._get_financial("net_sales", "2025")
        net_debt = self._get_financial("net_debt", "2025") or 0
        cash = self._get_financial("cash_and_equivalents", "2025") or 0

        if not revenue or revenue <= 0:
            return None

        implied_ev = blended * revenue
        equity_value = implied_ev - net_debt + cash
        per_share = (equity_value * 1_000_000) / NUM_SHARES

        return {
            "value": round(per_share, 2),
            "historical_median": round(hist_median, 2),
            "blended_multiple": round(blended, 2),
        }

    def _fcf_yield_fair_value(self) -> Optional[dict]:
        """Implied value from FCF yield."""
        fcf_yield_hist = self._get_hist_values("valuation", "fcf_yield_hist",
                                                years=["2021", "2022", "2023", "2024", "2025"])
        if not fcf_yield_hist:
            return None

        hist_median = statistics.median(fcf_yield_hist.values())
        if hist_median <= 0:
            return None

        price = self._current_price()
        # Current FCF yield relative to historical: if yield is higher now,
        # stock is cheaper; implied value = price * (current_yield / historical_median)
        current_yield = self._get_valuation("fcf_yield_hist")
        if isinstance(current_yield, dict):
            current_yield = current_yield.get("2025")

        if current_yield and current_yield > 0:
            fair_value = price * (current_yield / hist_median)
            return {
                "value": round(fair_value, 2),
                "current_yield": round(current_yield, 2),
                "historical_median_yield": round(hist_median, 2),
            }
        return None

    def _get_latest_eps(self) -> Optional[float]:
        """Get latest EPS value."""
        eps = self._get_hist_values("financials", "eps")
        if eps:
            latest = max(eps.keys())
            return eps[latest]
        return None

    def _get_book_value_per_share(self) -> Optional[float]:
        """Get book value per share."""
        bvps = self._get_hist_values("financials", "book_value_per_share")
        if bvps:
            return bvps[max(bvps.keys())]

        equity = self._get_financial("shareholders_equity", "2025")
        if equity:
            return (equity * 1_000_000) / NUM_SHARES
        return None
