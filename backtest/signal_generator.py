"""
Backtest Signal Generator
=========================
Re-runs your ScoringEngine + RecommendationEngine at each annual checkpoint
using real historical financials from stock_data.json.

For each year Y, it:
  1. Slices stock_data.json to only include years <= Y  (no look-ahead)
  2. Looks up the actual closing price in the CSV for the signal date
  3. Runs the valuation models and scoring engine
  4. Returns a BUY / HOLD / SELL signal with upside% and composite score

Signal dates are set to early February each year, which is when IAM
publishes its full-year results (e.g. annual results released ~Feb 2025
for FY2024). This avoids forward-looking bias.
"""

import sys
import os
import json
import copy
from pathlib import Path
from typing import List, Dict, Any, Optional
import pandas as pd

# ── make project root importable ─────────────────────────────────────────────
_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_ROOT))

from core.data_normalizer import normalize_stock_data
from models.dcf_model import DCFModel
from models.ddm_model import DDMModel
from models.graham_model import GrahamModel
from models.relative_valuation import RelativeValuationModel
from models.monte_carlo import MonteCarloModel
from strategies.scoring_engine import ScoringEngine
from strategies.recommendation_engine import RecommendationEngine
import utils.financial_constants as const


# ─── constants ────────────────────────────────────────────────────────────────
_STOCK_DATA_PATH = _ROOT / "testing" / "testing" / "stock_data.json"

# IAM annual results publication schedule (approximate)
# Key: fiscal year results available  →  Value: signal date (first trading day after publication)
SIGNAL_DATES: Dict[int, str] = {
    # FY2020 results published ~Feb 2021 → signal early March 2021
    2020: "2021-03-01",
    # FY2021 results published ~Feb 2022
    2021: "2022-02-15",
    # FY2022 published ~Feb 2023
    2022: "2023-02-15",
    # FY2023 published ~Feb 2024
    2023: "2024-02-15",
    # FY2024 published Feb 2025
    2024: "2025-02-13",
    # FY2025 published Feb 2026
    2025: "2026-02-13",
}

VALUATION_CONSTANTS = {
    "risk_free_rate":    const.RISK_FREE_RATE,
    "equity_risk_premium": const.EQUITY_RISK_PREMIUM,
    "beta":              const.IAM_BETA,
    "tax_rate":          const.CORPORATE_TAX_RATE,
    "terminal_growth":   const.TERMINAL_GROWTH_RATE,
    "num_shares":        const.NUM_SHARES,
}


# ─── helpers ──────────────────────────────────────────────────────────────────

def load_stock_data(path: Optional[Path] = None) -> dict:
    """Load raw stock_data.json and return the first stock entry."""
    path = path or _STOCK_DATA_PATH
    with open(path, "r", encoding="utf-8") as f:
        raw = json.load(f)
    stocks = raw.get("stocks", [])
    if not stocks:
        raise ValueError(f"No stocks found in {path}")
    return stocks[0]


def _mask_future_data(stock: dict, cutoff_year: int) -> dict:
    """Return a deep copy of stock with all data after cutoff_year removed.

    This prevents look-ahead bias — when generating the signal for FY2024,
    we must not see FY2025 results.
    """
    s = copy.deepcopy(stock)
    cutoff = str(cutoff_year)

    def _trim(d: dict) -> dict:
        if isinstance(d, dict):
            return {k: v for k, v in d.items() if k <= cutoff}
        return d

    # Trim all time-series dicts in financials and valuation
    for section in ("financials", "valuation"):
        sec = s.get(section, {})
        for field, value in sec.items():
            if isinstance(value, dict):
                sec[field] = _trim(value)

    return s


def _run_models(data: dict) -> list:
    """Run all 5 valuation models and return their results."""
    models = [
        DCFModel(data, VALUATION_CONSTANTS),
        DDMModel(data, VALUATION_CONSTANTS),
        GrahamModel(data, VALUATION_CONSTANTS),
        RelativeValuationModel(data, VALUATION_CONSTANTS),
        MonteCarloModel(data, VALUATION_CONSTANTS),
    ]
    results = []
    for m in models:
        try:
            r = m.calculate()
            results.append(r)
        except Exception as e:
            print(f"  [WARN] Model {type(m).__name__} failed: {e}")
    return results


# ─── main signal generator ────────────────────────────────────────────────────

class SignalGenerator:
    """Generates BUY/HOLD/SELL signals at annual checkpoints for IAM."""

    def __init__(self, stock_data_path: Optional[Path] = None):
        self.raw_stock = load_stock_data(stock_data_path)

    def generate_all_signals(
        self,
        price_df: pd.DataFrame,
        fiscal_years: Optional[List[int]] = None,
    ) -> List[Dict[str, Any]]:
        """Generate signals for all available fiscal years.

        Parameters
        ----------
        price_df : pd.DataFrame
            Daily price data with DatetimeIndex (from data_loader.load_price_data())
        fiscal_years : list of int, optional
            Which FY snapshots to generate signals for.
            Defaults to all years in SIGNAL_DATES.

        Returns
        -------
        list of dicts, each containing:
            fiscal_year, signal_date, execution_date, price_at_signal,
            signal, upside_pct, composite_score,
            intrinsic_value, model_results, factor_scores
        """
        if fiscal_years is None:
            fiscal_years = sorted(SIGNAL_DATES.keys())

        signals = []
        for fy in fiscal_years:
            if fy not in SIGNAL_DATES:
                print(f"[WARN] No signal date configured for FY{fy}")
                continue

            sig = self._generate_signal(fy, price_df)
            if sig:
                signals.append(sig)

        return signals

    def _generate_signal(self, fiscal_year: int, price_df: pd.DataFrame) -> Optional[Dict]:
        """Generate one signal for a given fiscal year."""
        signal_date_str = SIGNAL_DATES[fiscal_year]
        signal_date = pd.Timestamp(signal_date_str)

        # Find actual execution price (next open after signal date)
        from backtest.data_loader import get_price_on_or_after, get_price_on_or_before

        exec_date, exec_price = get_price_on_or_after(price_df, signal_date)
        if exec_date is None or exec_price is None:
            print(f"  [SKIP] FY{fiscal_year}: no price data after {signal_date_str}")
            return None

        # Find price at signal date (for upside calculation)
        _, price_at_signal = get_price_on_or_before(price_df, signal_date)
        if price_at_signal is None:
            price_at_signal = exec_price

        print(f"\n  FY{fiscal_year} | Signal date: {signal_date.date()} "
              f"| Price: {price_at_signal:.2f} MAD")

        # Build data snapshot — mask future years
        masked = _mask_future_data(self.raw_stock, fiscal_year)
        # Override current price with actual historical price
        masked["price_performance"] = copy.deepcopy(
            self.raw_stock.get("price_performance", {})
        )
        masked["price_performance"]["last_price"] = price_at_signal
        masked["current_price"] = price_at_signal

        # Normalize
        try:
            data = normalize_stock_data(masked)
        except Exception as e:
            print(f"  [WARN] Normalization failed for FY{fiscal_year}: {e}")
            return None

        # Run valuation models
        model_results = _run_models(data)
        valid_results = [r for r in model_results if r.intrinsic_value > 0]

        if not valid_results:
            print(f"  [SKIP] FY{fiscal_year}: all models returned 0")
            return None

        # Score factors
        try:
            scorer = ScoringEngine(data)
            factor_scores = scorer.score()
        except Exception as e:
            print(f"  [WARN] Scoring failed for FY{fiscal_year}: {e}")
            factor_scores = {"composite": 50.0}

        # Generate recommendation
        try:
            engine = RecommendationEngine(model_results, factor_scores, price_at_signal)
            rec = engine.recommend()
        except Exception as e:
            print(f"  [WARN] Recommendation failed for FY{fiscal_year}: {e}")
            rec = {"recommendation": "HOLD", "intrinsic_value": {"upside_pct": 0}}

        signal_str = rec["recommendation"]
        upside = rec["intrinsic_value"]["upside_pct"]
        iv = rec["intrinsic_value"]["weighted_average"]

        print(f"         ➜ {signal_str:12s} | Upside: {upside:+.1f}%  "
              f"| IV: {iv:.2f} MAD  | Score: {factor_scores.get('composite', 0):.1f}/100")

        return {
            "fiscal_year":      fiscal_year,
            "signal_date":      signal_date,
            "execution_date":   exec_date,
            "price_at_signal":  price_at_signal,
            "execution_price":  exec_price,
            "signal":           signal_str,
            "upside_pct":       upside,
            "intrinsic_value":  iv,
            "composite_score":  factor_scores.get("composite", 50.0),
            "factor_scores":    factor_scores,
            "model_results":    model_results,
            "recommendation":   rec,
        }
