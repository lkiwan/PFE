"""
Parameter Sensitivity Analysis
================================
Sweeps the two key recommendation thresholds from financial_constants.py
and reports which combo gives the best Sharpe ratio.

Parameters swept:
  - min_upside_pct   : threshold to trigger BUY (your current = 10%)
  - min_score        : composite score threshold for BUY (your current = 55)

For each parameter combo it re-runs the engine and records metrics,
then outputs a ranked leaderboard and a 2-D heatmap matrix.
"""

from __future__ import annotations
import copy
import itertools
from typing import List, Dict, Any, Optional
import numpy as np
import pandas as pd

from backtest.engine import BacktestEngine
from backtest.metrics import compute_metrics


# ─── parameter grid ──────────────────────────────────────────────────────────
UPSIDE_GRID = [5, 10, 15, 20, 25]          # min upside % to trigger BUY
SCORE_GRID  = [45, 50, 55, 60, 65, 70]     # min composite score for BUY


def run_sensitivity(
    price_df: pd.DataFrame,
    raw_signals: List[Dict],
    initial_capital: float = 100_000.0,
    upside_grid: Optional[List[float]] = None,
    score_grid:  Optional[List[float]] = None,
) -> Dict[str, Any]:
    """
    Sweep upside_threshold × composite_score_threshold and compute Sharpe
    for each combination.

    Parameters
    ----------
    price_df : pd.DataFrame
        Daily OHLCV data.
    raw_signals : list of dict
        Signals from SignalGenerator (with upside_pct and composite_score).
    initial_capital : float

    Returns
    -------
    dict with:
        results   : list of result dicts (one per param combo), sorted by Sharpe
        heatmap_df: pd.DataFrame — rows=upside threshold, cols=score threshold
        best      : dict — the best-performing parameter combo
    """
    upside_grid = upside_grid or UPSIDE_GRID
    score_grid  = score_grid  or SCORE_GRID

    results = []

    total = len(upside_grid) * len(score_grid)
    print(f"\n── Parameter Sensitivity ({total} combos) ────────────────────")

    for upside_thresh, score_thresh in itertools.product(upside_grid, score_grid):
        # Re-map signals using this param combo
        remapped = _remap_signals(raw_signals, upside_thresh, score_thresh)

        if not any(s["signal"] in ("BUY", "STRONG BUY") for s in remapped):
            results.append({
                "upside_threshold": upside_thresh,
                "score_threshold":  score_thresh,
                "sharpe":  -999,
                "cagr":    0,
                "max_dd":  0,
                "total_return": 0,
                "n_trades": 0,
                "signal_summary": "No BUY signals",
            })
            continue

        engine = BacktestEngine(
            price_df=price_df,
            signals=remapped,
            initial_capital=initial_capital,
            commission=0.003,
            include_dividends=False,    # keep sensitivity clean
        )
        # Suppress console output during sweep
        import io, sys
        buf = io.StringIO()
        old_stdout = sys.stdout
        sys.stdout = buf
        try:
            bt = engine.run()
        finally:
            sys.stdout = old_stdout

        m = compute_metrics(
            bt.equity_curve, bt.benchmark_curve, bt.trades, initial_capital
        )

        sharpe = m.get("sharpe_ratio", 0) or 0
        cagr   = m.get("cagr_pct", 0) or 0
        max_dd = m.get("max_drawdown_pct", 0) or 0
        tot_ret = m.get("total_return_pct", 0) or 0
        n_buy   = sum(1 for t in bt.trades if t.action == "BUY")

        results.append({
            "upside_threshold": upside_thresh,
            "score_threshold":  score_thresh,
            "sharpe":           round(sharpe, 3),
            "cagr":             round(cagr, 2),
            "max_dd":           round(max_dd, 2),
            "total_return":     round(tot_ret, 2),
            "n_trades":         n_buy,
            "signal_summary": (
                f"{sum(1 for s in remapped if s['signal'] in ('BUY','STRONG BUY'))} BUY, "
                f"{sum(1 for s in remapped if s['signal'] in ('SELL','STRONG SELL'))} SELL, "
                f"{sum(1 for s in remapped if s['signal'] == 'HOLD')} HOLD"
            ),
        })

    # ── sort by Sharpe ────────────────────────────────────────────────────
    results.sort(key=lambda r: r["sharpe"], reverse=True)

    # ── build heatmap matrix ──────────────────────────────────────────────
    heatmap = pd.DataFrame(
        index=[f"Upside≥{u}%" for u in upside_grid],
        columns=[f"Score≥{s}" for s in score_grid],
        dtype=float,
    )
    for r in results:
        row = f"Upside≥{r['upside_threshold']}%"
        col = f"Score≥{r['score_threshold']}"
        heatmap.loc[row, col] = r["sharpe"]

    best = results[0] if results else {}

    # ── print leaderboard (top 10) ────────────────────────────────────────
    print(f"\n  {'Upside%':>8}  {'Score':>6}  {'Sharpe':>8}  {'CAGR%':>7}  {'MaxDD%':>7}  {'Trades':>6}")
    print(f"  {'─'*8}  {'─'*6}  {'─'*8}  {'─'*7}  {'─'*7}  {'─'*6}")
    for r in results[:10]:
        marker = " ◀ BEST" if r == best else ""
        print(
            f"  {r['upside_threshold']:>7}%  {r['score_threshold']:>6}  "
            f"{r['sharpe']:>8.3f}  {r['cagr']:>6.1f}%  {r['max_dd']:>6.1f}%  "
            f"{r['n_trades']:>6}{marker}"
        )

    if best:
        print(f"\n  ★ Best combo: Upside ≥ {best['upside_threshold']}%  |  "
              f"Score ≥ {best['score_threshold']}  →  Sharpe = {best['sharpe']}")
        print(f"    Your current params: Upside ≥ 10%  |  Score ≥ 55")

    return {"results": results, "heatmap_df": heatmap, "best": best}


def _remap_signals(raw_signals: List[Dict], upside_thresh: float, score_thresh: float) -> List[Dict]:
    """Re-classify each signal based on new thresholds."""
    remapped = []
    for sig in raw_signals:
        s = copy.deepcopy(sig)
        upside = s["upside_pct"]
        score  = s["composite_score"]

        if upside >= 20 and score >= score_thresh + 10:
            new_sig = "STRONG BUY"
        elif upside >= upside_thresh and score >= score_thresh:
            new_sig = "BUY"
        elif upside <= -20 and score < score_thresh - 15:
            new_sig = "STRONG SELL"
        elif upside <= -upside_thresh and score < score_thresh - 5:
            new_sig = "SELL"
        else:
            new_sig = "HOLD"

        s["signal"] = new_sig
        remapped.append(s)
    return remapped
