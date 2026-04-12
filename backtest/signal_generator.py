"""
Backtest Signal Generator
=========================
Re-runs ScoringEngine + RecommendationEngine at each annual checkpoint
using real historical financials from V3 merged data.

For each year Y, it:
  1. Masks merged data to only include years <= Y (no look-ahead)
  2. Looks up the actual closing price in the CSV for the signal date
  3. Runs the valuation models and scoring engine
  4. Returns a BUY / HOLD / SELL signal with upside% and composite score

Signal dates are set to early February each year, which is when IAM
publishes its full-year results.
"""

import sys
import copy
from pathlib import Path
from typing import List, Dict, Any, Optional
import pandas as pd

# ── make project root importable ─────────────────────────────────────────────
_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_ROOT))

from core.data_merger import load_stock_data as load_merged_data
from core.data_normalizer import normalize_stock_data
from models.dcf_model import DCFModel
from models.ddm_model import DDMModel
from models.graham_model import GrahamModel
from models.relative_valuation import RelativeValuationModel
from models.monte_carlo import MonteCarloModel
from strategies.scoring_engine import ScoringEngine
from strategies.recommendation_engine import RecommendationEngine
import utils.financial_constants as const


# IAM annual results publication schedule (approximate)
SIGNAL_DATES: Dict[int, str] = {
    2020: "2021-03-01",
    2021: "2022-02-15",
    2022: "2023-02-15",
    2023: "2024-02-15",
    2024: "2025-02-13",
    2025: "2026-02-13",
}

VALUATION_CONSTANTS = {
    "risk_free_rate":      const.RISK_FREE_RATE,
    "equity_risk_premium": const.EQUITY_RISK_PREMIUM,
    "beta":                const.IAM_BETA,
    "tax_rate":            const.CORPORATE_TAX_RATE,
    "terminal_growth":     const.TERMINAL_GROWTH_RATE,
    "num_shares":          const.NUM_SHARES,
}


# ─── helpers ──────────────────────────────────────────────────────────────────

def _mask_future_data(stock: dict, cutoff_year: int) -> dict:
    """Return a deep copy with all hist_* data after cutoff_year removed.

    Prevents look-ahead bias — when generating the signal for FY2024,
    we must not see FY2025 results.
    """
    s = copy.deepcopy(stock)
    cutoff = str(cutoff_year)

    for key, value in s.items():
        if key.startswith("hist_") and isinstance(value, dict):
            s[key] = {k: v for k, v in value.items() if k <= cutoff}

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
    """Generates BUY/HOLD/SELL signals at annual checkpoints."""

    def __init__(self, symbol: str = "IAM"):
        self.raw_stock = load_merged_data(symbol, verbose=False)

    def generate_all_signals(
        self,
        price_df: pd.DataFrame,
        fiscal_years: Optional[List[int]] = None,
    ) -> List[Dict[str, Any]]:
        """Generate signals for all available fiscal years."""
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

        from backtest.data_loader import get_price_on_or_after, get_price_on_or_before

        exec_date, exec_price = get_price_on_or_after(price_df, signal_date)
        if exec_date is None or exec_price is None:
            print(f"  [SKIP] FY{fiscal_year}: no price data after {signal_date_str}")
            return None

        _, price_at_signal = get_price_on_or_before(price_df, signal_date)
        if price_at_signal is None:
            price_at_signal = exec_price

        print(f"\n  FY{fiscal_year} | Signal date: {signal_date.date()} "
              f"| Price: {price_at_signal:.2f} MAD")

        # Mask future years from hist_* fields
        masked = _mask_future_data(self.raw_stock, fiscal_year)
        masked["price"] = price_at_signal

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

        print(f"         -> {signal_str:12s} | Upside: {upside:+.1f}%  "
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
