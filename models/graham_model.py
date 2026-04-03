"""Benjamin Graham intrinsic value formulas.

Classic, conservative valuation methods from "The Intelligent Investor"
and "Security Analysis". Provides a margin-of-safety floor.
"""

import math
from typing import Optional

from models.base_model import BaseValuationModel, ValuationResult
from utils.financial_constants import RISK_FREE_RATE, NUM_SHARES


class GrahamModel(BaseValuationModel):
    """Graham Number + Graham Growth Formula + NCAV."""

    def calculate(self) -> ValuationResult:
        eps = self._get_eps()
        bvps = self._get_book_value_per_share()

        results = {}

        # 1. Graham Number: sqrt(22.5 * EPS * BVPS)
        graham_number = None
        if eps and eps > 0 and bvps and bvps > 0:
            graham_number = math.sqrt(22.5 * eps * bvps)
            results["graham_number"] = round(graham_number, 2)

        # 2. Graham Growth Formula: V = EPS * (8.5 + 2g) * 4.4 / Y
        graham_growth = None
        growth_rate = self._estimate_growth_rate()
        bond_yield = max(RISK_FREE_RATE * 100, 3.0)  # Minimum 3%
        if eps and eps > 0 and growth_rate is not None:
            graham_growth = eps * (8.5 + 2 * growth_rate) * 4.4 / bond_yield
            results["graham_growth_formula"] = round(graham_growth, 2)
            results["assumed_growth_rate"] = round(growth_rate, 2)
            results["bond_yield_used"] = round(bond_yield, 2)

        # 3. Net Current Asset Value (NCAV) — conservative floor
        ncav = self._compute_ncav()
        if ncav is not None:
            results["ncav_per_share"] = round(ncav, 2)

        # Choose primary value: prefer Graham Growth, fallback to Graham Number
        if graham_growth and graham_growth > 0:
            primary = graham_growth
        elif graham_number and graham_number > 0:
            primary = graham_number
        else:
            return ValuationResult(
                model_name="Graham",
                intrinsic_value=0,
                confidence=0,
                methodology="Graham — insufficient data (need EPS and BVPS)",
            )

        # Range: Graham Number as low, Graham Growth as high
        low_val = min(v for v in [graham_number, graham_growth, ncav] if v and v > 0)
        high_val = max(v for v in [graham_number, graham_growth, ncav] if v and v > 0)

        upside = self._compute_upside(primary)

        # Confidence is high for Graham (deterministic formulas, well-established)
        confidence = 70 if (eps and bvps) else 40

        return ValuationResult(
            model_name="Graham",
            intrinsic_value=round(primary, 2),
            intrinsic_value_low=round(low_val, 2),
            intrinsic_value_high=round(high_val, 2),
            upside_pct=round(upside, 1),
            confidence=confidence,
            methodology="Graham Number + Growth Formula (The Intelligent Investor)",
            details=results,
        )

    def _get_eps(self) -> Optional[float]:
        """Get most recent EPS."""
        # Try from financials
        eps_data = self._get_hist_values("financials", "eps")
        if eps_data:
            latest_year = max(eps_data.keys())
            return eps_data[latest_year]

        # Try from valuation page historical
        eps_hist = self._get_hist_values("valuation", "eps_hist")
        if eps_hist:
            latest_year = max(eps_hist.keys())
            return eps_hist[latest_year]

        return None

    def _get_book_value_per_share(self) -> Optional[float]:
        """Get book value per share."""
        bvps = self._get_hist_values("financials", "book_value_per_share")
        if bvps:
            latest = max(bvps.keys())
            return bvps[latest]

        # Derive from shareholders equity
        equity = self._get_financial("shareholders_equity", "2025")
        if equity:
            return (equity * 1_000_000) / NUM_SHARES
        return None

    def _estimate_growth_rate(self) -> Optional[float]:
        """Estimate long-term EPS growth rate (annualized %)."""
        eps_data = self._get_hist_values("financials", "eps")
        if len(eps_data) >= 2:
            years = sorted(eps_data.keys())
            first_val = eps_data[years[0]]
            last_val = eps_data[years[-1]]
            n_years = int(years[-1]) - int(years[0])
            if first_val and first_val > 0 and last_val and n_years > 0:
                cagr = (last_val / first_val) ** (1 / n_years) - 1
                return cagr * 100  # Convert to percentage for Graham formula

        # Fallback: use revenue growth
        sales = self._get_hist_values("financials", "net_sales")
        if len(sales) >= 2:
            years = sorted(sales.keys())
            first_val = sales[years[0]]
            last_val = sales[years[-1]]
            n_years = int(years[-1]) - int(years[0])
            if first_val and first_val > 0 and n_years > 0:
                return ((last_val / first_val) ** (1 / n_years) - 1) * 100

        return 3.0  # Default conservative growth

    def _compute_ncav(self) -> Optional[float]:
        """Net Current Asset Value per share."""
        # NCAV = Current Assets - Total Liabilities
        # We approximate: Working Capital + Cash - long-term liabilities
        total_assets = self._get_financial("total_assets", "2025")
        total_liabilities = self._get_financial("total_liabilities", "2025")

        if total_assets and total_liabilities:
            # Very conservative: 2/3 of (current assets - total liabilities)
            # Since we don't have current assets separately, use total_assets
            ncav = (total_assets - total_liabilities) * 1_000_000 / NUM_SHARES
            return ncav
        return None
