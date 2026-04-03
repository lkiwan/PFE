"""Normalize scraped MarketScreener data to consistent units.

The scraper pulls data from different pages that use different denominations:
- Income statement page: full MAD (e.g., 35,790,000,000)
- Forecasts page: millions of MAD (e.g., 35,790)
- Ratios: percentages or pure ratios (e.g., 0.35)

This module standardizes everything to millions MAD for monetary values,
and percentages for ratios/margins.
"""

import copy
import statistics
from typing import Dict, Optional


def normalize_stock_data(raw_data: dict) -> dict:
    """Return a clean dict with all monetary values in millions MAD.

    Performs:
    1. Deep copy to avoid mutating original
    2. Normalize financial statement items to millions MAD
    3. Cross-validate using margins
    4. Derive missing values where possible
    5. Clean up valuation metrics
    """
    data = copy.deepcopy(raw_data)

    _normalize_financials(data.get("financials", {}))
    _normalize_valuation(data.get("valuation", {}))
    _derive_missing_values(data)

    return data


def _normalize_financials(fin: dict) -> None:
    """Normalize all financial fields to millions MAD."""
    if not fin:
        return

    # Fields that come from the income statement / balance sheet pages in full MAD
    # These have values like 35,790,000,000 — need to divide by 1,000,000
    full_mad_fields = [
        "revenues", "cost_of_sales", "gross_profit", "operating_income",
        "ebitda", "ebit", "total_assets", "total_liabilities",
        "shareholders_equity", "cash_and_equivalents", "total_debt",
        "working_capital", "dividends_paid",
    ]

    for field_name in full_mad_fields:
        field_data = fin.get(field_name)
        if not isinstance(field_data, dict):
            continue
        for year, value in field_data.items():
            if value is not None and abs(value) > 100_000:
                # This is in full MAD, convert to millions
                field_data[year] = value / 1_000_000

    # net_sales from forecasts page is already in millions (35,790)
    # No conversion needed for net_sales

    # Fields with mixed units between actuals and forecasts:
    # The scraper stores different pages' data with different denominations.
    # Actuals (2021-2025) from ratio pages are tiny numbers (percentages or ratios).
    # Forecasts (2026-2028) from estimates pages are in millions MAD.
    # We need to reconstruct actuals from known correct values.

    # Net income: reconstruct from net_margin * net_sales
    _normalize_mixed_field(fin, "net_income", "net_margin", "net_sales")

    # Net debt: reconstruct from total_debt - cash for years where value is tiny
    _reconstruct_net_debt(fin)

    # FCF: reconstruct from EBITDA and CapEx for years where value is tiny
    _reconstruct_fcf(fin)

    # CapEx: reconstruct from capex% * revenue for years where value is tiny
    _reconstruct_capex(fin)

    # Operating cash flow: reconstruct from OCF ratio * revenue
    _reconstruct_ocf(fin)

    # Ratio/percentage fields — keep as-is (already in %)
    # ebitda_margin, operating_margin, net_margin, roe, roa, roce,
    # debt_to_equity, current_ratio


def _normalize_mixed_field(fin: dict, field_name: str,
                           margin_field: str = None,
                           revenue_field: str = "net_sales") -> None:
    """Reconstruct fields where actuals are percentages but forecasts are millions.

    Uses margin * revenue to reconstruct absolute values.
    """
    field_data = fin.get(field_name)
    if not isinstance(field_data, dict):
        return

    net_sales = fin.get(revenue_field, {})
    if not net_sales:
        return

    ref_revenue = statistics.median(
        [v for v in net_sales.values() if v is not None and v > 100]
    ) if net_sales else 0

    for year, value in field_data.items():
        if value is None:
            continue
        abs_val = abs(value)

        # If tiny relative to revenue, reconstruct from margin
        if abs_val < 100 and ref_revenue > 1000:
            if margin_field and margin_field in fin:
                margin = fin[margin_field].get(year)
                rev = net_sales.get(year)
                if margin is not None and rev is not None:
                    field_data[year] = margin * rev / 100
        # If in full MAD
        elif abs_val > 1_000_000:
            field_data[year] = value / 1_000_000


def _reconstruct_net_debt(fin: dict) -> None:
    """Reconstruct net debt = total_debt - cash for years with bad values."""
    nd = fin.get("net_debt")
    debt = fin.get("total_debt", {})
    cash = fin.get("cash_and_equivalents", {})
    if not isinstance(nd, dict):
        return

    for year, value in nd.items():
        if value is not None and abs(value) < 100:
            # This is a ratio, not millions — reconstruct
            d = debt.get(year)
            c = cash.get(year)
            if d is not None and c is not None:
                nd[year] = d - c


def _reconstruct_fcf(fin: dict) -> None:
    """Reconstruct FCF from EBITDA for years with bad values."""
    fcf = fin.get("free_cash_flow")
    ebitda = fin.get("ebitda", {})
    capex_data = fin.get("capex", {})
    net_sales = fin.get("net_sales", {})
    if not isinstance(fcf, dict):
        return

    for year, value in fcf.items():
        if value is not None and abs(value) < 100:
            # Try: FCF = EBITDA * (1 - 0.31) - CapEx
            eb = ebitda.get(year)
            rev = net_sales.get(year)
            if eb and eb > 100:
                # Estimate capex as ~15% of revenue (if capex data is also bad)
                cx = capex_data.get(year)
                if cx and cx > 100:
                    capex_val = cx
                elif rev:
                    capex_val = rev * 0.15
                else:
                    capex_val = 0
                fcf[year] = eb * 0.69 - capex_val


def _reconstruct_capex(fin: dict) -> None:
    """Reconstruct CapEx for years where it's stored as a ratio."""
    capex = fin.get("capex")
    net_sales = fin.get("net_sales", {})
    if not isinstance(capex, dict):
        return

    for year, value in capex.items():
        if value is not None and abs(value) < 100:
            rev = net_sales.get(year)
            if rev and rev > 100:
                # Value looks like a percentage of revenue
                capex[year] = value * rev / 100


def _reconstruct_ocf(fin: dict) -> None:
    """Reconstruct operating cash flow for years where it's stored as a ratio."""
    ocf = fin.get("operating_cash_flow")
    net_sales = fin.get("net_sales", {})
    if not isinstance(ocf, dict):
        return

    for year, value in ocf.items():
        if value is not None and abs(value) < 10:
            rev = net_sales.get(year)
            if rev and rev > 100:
                # Value looks like OCF/Revenue ratio — multiply by revenue
                ocf[year] = value * rev


def _normalize_valuation(val: dict) -> None:
    """Normalize valuation fields."""
    if not val:
        return

    # market_cap and enterprise_value are in full MAD
    for field in ["market_cap", "enterprise_value"]:
        if val.get(field) and val[field] > 1_000_000:
            val[field] = val[field] / 1_000_000  # Now in millions MAD

    # num_shares: stored as thousands (879,031), convert to actual count
    if val.get("num_shares"):
        val["num_shares_actual"] = val["num_shares"] * 1000


def _derive_missing_values(data: dict) -> None:
    """Compute derived metrics that may be missing."""
    fin = data.get("financials", {})
    val = data.get("valuation", {})
    price = data.get("price_performance", {})

    # Derive EPS if missing (net_income / shares)
    if not fin.get("eps") or not any(fin["eps"].values()):
        net_income = fin.get("net_income", {})
        num_shares = val.get("num_shares_actual") or val.get("num_shares", 0) * 1000
        if net_income and num_shares:
            fin["eps"] = {}
            for year, ni in net_income.items():
                if ni is not None:
                    # net_income is in millions, shares in actual
                    fin["eps"][year] = (ni * 1_000_000) / num_shares

    # Derive Book Value Per Share
    equity = fin.get("shareholders_equity", {})
    num_shares = val.get("num_shares_actual") or val.get("num_shares", 0) * 1000
    if equity and num_shares:
        fin["book_value_per_share"] = {}
        for year, eq in equity.items():
            if eq is not None:
                fin["book_value_per_share"][year] = (eq * 1_000_000) / num_shares

    # Derive Interest Expense approximation (EBIT - Operating Income)
    ebit = fin.get("ebit", {})
    net_income_dict = fin.get("net_income", {})
    if ebit and net_income_dict:
        fin["interest_expense_approx"] = {}
        for year in ebit:
            e = ebit.get(year)
            ni = net_income_dict.get(year)
            if e is not None and ni is not None:
                # Rough: interest ~ EBIT - pre-tax income ~ EBIT - NI / (1-tax)
                fin["interest_expense_approx"][year] = max(0, e - ni / 0.69)

    # Derive Net Debt / EBITDA ratio
    net_debt = fin.get("net_debt", {})
    ebitda = fin.get("ebitda", {})
    if net_debt and ebitda:
        fin["net_debt_to_ebitda"] = {}
        for year in net_debt:
            nd = net_debt.get(year)
            eb = ebitda.get(year)
            if nd is not None and eb is not None and eb != 0:
                fin["net_debt_to_ebitda"][year] = nd / eb

    # Store current price for easy access
    data["current_price"] = price.get("last_price")
