"""
Data Merger — V3 MarketScreener + Bourse Casa
==============================================
Combines data from two sources:
1. MarketScreener V3 JSON (fundamentals, ratios, analyst consensus)
2. Bourse Casa CSV (daily OHLCV → price, volume, market_cap, 52w high/low)

Bourse Casa overrides V3 for market fields (exchange data is more current).

Usage:
    from data_merger import load_stock_data
    data = load_stock_data("IAM")
"""

import csv
import json
from pathlib import Path
from typing import Dict, Any, Optional, List
from datetime import datetime, timezone

# Paths
_ROOT = Path(__file__).resolve().parent.parent
V3_DATA_DIR = _ROOT / "data" / "historical"


def _safe_float(value: Any) -> Optional[float]:
    """Convert API/CSV numeric values to float safely."""
    if value in (None, ""):
        return None
    try:
        return float(str(value).replace(" ", "").replace(",", "."))
    except (ValueError, TypeError):
        return None


def load_v3_data(symbol: str) -> Optional[Dict[str, Any]]:
    """Load data from V3 scraper output."""
    v3_file = V3_DATA_DIR / f"{symbol}_marketscreener_v3.json"
    try:
        with open(v3_file, "r", encoding="utf-8") as f:
            return json.load(f)
    except FileNotFoundError:
        return None


def load_bourse_data(symbol: str) -> Optional[Dict[str, Any]]:
    """
    Load OHLCV/market-cap fallback data from Bourse Casa CSV and derive
    latest volume + rolling 52-week high/low.
    """
    csv_path = V3_DATA_DIR / f"{symbol}_bourse_casa_full.csv"
    if not csv_path.exists():
        return None

    with open(csv_path, "r", encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        rows = list(reader)
        fieldnames = reader.fieldnames or []

    if not rows:
        return None

    header_map = {h.strip().lower(): h for h in fieldnames if h}

    def pick_col(*names: str) -> Optional[str]:
        for name in names:
            col = header_map.get(name.lower())
            if col:
                return col
        return None

    date_col = pick_col("Séance", "seance", "date")
    close_col = pick_col("Dernier Cours", "close", "courscourant")
    high_col = pick_col("+haut du jour", "high", "highprice")
    low_col = pick_col("+bas du jour", "low", "lowprice")
    vol_col = pick_col("Nombre de titres échangés", "volume", "cumultitresechanges")
    mcap_col = pick_col("Capitalisation", "capitalisation", "market_cap")

    parsed_rows: List[Dict[str, Any]] = []
    for row in rows:
        raw_date = (row.get(date_col) or "") if date_col else ""
        try:
            trade_date = datetime.strptime(str(raw_date)[:10], "%Y-%m-%d")
        except ValueError:
            continue
        parsed_rows.append({
            "date": trade_date,
            "close": _safe_float(row.get(close_col)) if close_col else None,
            "high": _safe_float(row.get(high_col)) if high_col else None,
            "low": _safe_float(row.get(low_col)) if low_col else None,
            "volume": _safe_float(row.get(vol_col)) if vol_col else None,
            "market_cap": _safe_float(row.get(mcap_col)) if mcap_col else None,
        })

    if not parsed_rows:
        return None

    parsed_rows.sort(key=lambda x: x["date"])
    latest = parsed_rows[-1]
    trailing = parsed_rows[-252:]  # ~1 trading year

    highs = [r["high"] for r in trailing if r["high"] is not None]
    lows = [r["low"] for r in trailing if r["low"] is not None]

    return {
        "price": latest["close"],
        "volume": int(latest["volume"]) if latest["volume"] is not None else None,
        "market_cap": latest["market_cap"],
        "high_52w": max(highs) if highs else None,
        "low_52w": min(lows) if lows else None,
    }


def merge_stock_data(symbol: str) -> Dict[str, Any]:
    """
    Merge V3 MarketScreener + Bourse Casa data.

    Priority:
    - Base fundamentals/ratios/analyst: V3 JSON
    - Market fields (price, volume, market_cap, 52w): Bourse Casa overrides V3
      (exchange data is more current than scraper snapshot)
    """
    v3 = load_v3_data(symbol)
    bourse = load_bourse_data(symbol)

    if not v3 and not bourse:
        raise FileNotFoundError(f"No data found for {symbol}")

    # Start with V3 as base
    merged = v3.copy() if v3 else {"symbol": symbol}

    # Bourse Casa overrides market fields (more current than scraper snapshot)
    if bourse:
        for field in ("price", "volume", "market_cap", "high_52w", "low_52w"):
            if bourse.get(field) is not None:
                merged[field] = bourse[field]

    # Metadata
    merged['data_source'] = {
        'v3_scraper': bool(v3),
        'bourse_casa': bool(bourse),
        'merged_at': datetime.now(timezone.utc).isoformat()
    }

    return merged


# --- Quality check: all 28 fields ---

SCALAR_FIELDS = [
    'price', 'market_cap', 'pe_ratio', 'price_to_book',
    'dividend_yield', 'high_52w', 'low_52w', 'consensus', 'target_price',
]

HIST_FIELDS = [
    'hist_revenue', 'hist_net_income', 'hist_eps', 'hist_ebitda',
    'hist_fcf', 'hist_ocf', 'hist_capex', 'hist_debt',
    'hist_cash', 'hist_equity',
    'hist_net_margin', 'hist_ebit_margin', 'hist_ebitda_margin', 'hist_gross_margin',
    'hist_roe', 'hist_roce',
    'hist_ev_ebitda', 'hist_dividend_per_share', 'hist_eps_growth',
]

ALL_FIELDS = SCALAR_FIELDS + HIST_FIELDS


def get_data_quality(data: Dict[str, Any]) -> Dict[str, Any]:
    """Calculate data quality metrics across all 28 fields."""
    filled = 0
    for field in SCALAR_FIELDS:
        if data.get(field):
            filled += 1
    for field in HIST_FIELDS:
        if data.get(field) and len(data[field]) > 0:
            filled += 1

    total = len(ALL_FIELDS)
    quality_pct = (filled / total) * 100

    hist_years = {}
    for field in HIST_FIELDS:
        hist_years[field] = len(data.get(field, {}))

    return {
        'quality_pct': quality_pct,
        'filled_fields': filled,
        'total_fields': total,
        'historical_years': hist_years,
        'is_sufficient': quality_pct >= 70,
    }


def load_stock_data(symbol: str, verbose: bool = True) -> Dict[str, Any]:
    """
    Load and merge stock data from V3 + Bourse Casa.

    Args:
        symbol: Stock symbol (e.g., 'IAM')
        verbose: Print data quality summary

    Returns:
        Merged stock data dictionary
    """
    data = merge_stock_data(symbol)
    quality = get_data_quality(data)

    if verbose:
        print(f"\n{'='*55}")
        print(f"  {symbol} Data Summary")
        print(f"{'='*55}")
        print(f"  Quality: {quality['quality_pct']:.0f}% ({quality['filled_fields']}/{quality['total_fields']} fields)")

        # Scalars
        print(f"\n  Scalars:")
        for f in SCALAR_FIELDS:
            val = data.get(f)
            tag = "OK" if val else "MISSING"
            print(f"    {f:20s} {tag}")

        # Historical grouped
        groups = {
            "Fundamentals": ['hist_revenue', 'hist_net_income', 'hist_eps', 'hist_ebitda'],
            "Cash Flow":    ['hist_fcf', 'hist_ocf', 'hist_capex'],
            "Balance Sheet": ['hist_debt', 'hist_cash', 'hist_equity'],
            "Profitability": ['hist_net_margin', 'hist_ebit_margin', 'hist_ebitda_margin', 'hist_gross_margin'],
            "Returns":      ['hist_roe', 'hist_roce'],
            "Valuation":    ['hist_ev_ebitda', 'hist_dividend_per_share', 'hist_eps_growth'],
        }
        for group_name, fields in groups.items():
            print(f"\n  {group_name}:")
            for f in fields:
                yrs = len(data.get(f, {}))
                print(f"    {f:30s} {yrs} years")

        status = "SUFFICIENT" if quality['is_sufficient'] else "INSUFFICIENT"
        print(f"\n  Status: {status} for AI predictions")

        sources = data.get('data_source', {})
        parts = []
        if sources.get('v3_scraper'):
            parts.append("V3 MarketScreener")
        if sources.get('bourse_casa'):
            parts.append("Bourse Casa")
        print(f"  Sources: {' + '.join(parts) if parts else 'Unknown'}")
        print(f"{'='*55}\n")

    return data


# CLI interface
if __name__ == "__main__":
    import sys

    if len(sys.argv) < 2:
        print("Usage: python data_merger.py <SYMBOL>")
        print("Example: python data_merger.py IAM")
        sys.exit(1)

    symbol = sys.argv[1].upper()

    try:
        data = load_stock_data(symbol, verbose=True)

        # Save merged output
        output_file = V3_DATA_DIR / f"{symbol}_merged.json"
        with open(output_file, 'w') as f:
            json.dump(data, f, indent=2)

        print(f"Saved to: {output_file}")

    except FileNotFoundError as e:
        print(f"Error: {e}")
        sys.exit(1)
