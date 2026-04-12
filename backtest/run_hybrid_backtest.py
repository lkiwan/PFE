"""
Hybrid Whale strategy Backtest Runner
======================================
Runs the hybrid (Technical + Fundamental) whale strategy and 
generates an HTML report.

Usage:
    python backtest/run_hybrid_backtest.py
"""

from __future__ import annotations
import sys
import argparse
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_ROOT))

import pandas as pd
from backtest.data_loader import load_price_data
from backtest.metrics import compute_metrics, print_metrics
from strategies.hybrid_whale_strategy import HybridWhaleStrategy
from strategies.whale_strategy import WhaleParams
from backtest.run_whale_backtest import simulate_whale_portfolio, _build_whale_report

try:
    import plotly.io as pio
    _PLOTLY = True
except ImportError:
    _PLOTLY = False

def parse_args():
    p = argparse.ArgumentParser(description="IAM Hybrid Whale Strategy Backtest")
    p.add_argument("--capital",           type=float, default=100_000)
    p.add_argument("--volume-threshold",  type=float, default=2.5)
    p.add_argument("--price-threshold",   type=float, default=0.3)
    p.add_argument("--stop-loss",         type=float, default=8.0)
    p.add_argument("--take-profit",       type=float, default=25.0)
    p.add_argument("--sma-period",        type=int,   default=50)
    p.add_argument("--min-score",         type=float, default=50.0)
    p.add_argument("--start",             type=str,   default="2021-01-01")
    p.add_argument("--no-report",         action="store_true")
    return p.parse_args()


def main():
    args = parse_args()

    print("=" * 60)
    print("  🧬 IAM HYBRID WHALE STRATEGY BACKTEST")
    print("=" * 60)

    # 1. Load price data
    print("\n── Step 1: Loading price data ────────────────────────────────")
    df = load_price_data("IAM")
    if args.start:
        df = df[df.index >= pd.Timestamp(args.start)]
        print(f"  Filtered to start from {args.start} ({len(df):,} days)")

    # 2. Build parameters & run strategy
    print("\n── Step 2: Running Technical + Fundamental analysis ──────────")
    params = WhaleParams(
        volume_threshold = args.volume_threshold,
        price_threshold  = args.price_threshold,
        stop_loss_pct    = args.stop_loss,
        take_profit_pct  = args.take_profit,
        sma_period       = args.sma_period,
    )
    
    strategy = HybridWhaleStrategy(params, min_composite_score=args.min_score)
    signals_df = strategy.generate_signals(df)
    stats      = strategy.summary_stats(signals_df)

    print(f"  Total trading days : {stats['total_days']:,}")
    print(f"  Whale days detected: {stats['whale_days']:,}")
    print(f"  Final HYBRID BUYs  : {stats['buy_signals']} (after filtering weak fundamentals)")

    # 3. Simulate portfolio
    print("\n── Step 3: Simulating portfolio ──────────────────────────────")
    equity, benchmark, trades = simulate_whale_portfolio(
        df, signals_df, initial_capital=args.capital
    )
    
    # 4. Metrics
    print("\n── Step 4: Computing metrics ─────────────────────────────────")
    class _FakeTrade:
        def __init__(self, t):
            self.action = t["action"]
            self.shares = t["shares"]
            self.price  = t["price"]
            self.commission = t["commission"]

    fake_trades = [_FakeTrade(t) for t in trades]
    metrics = compute_metrics(equity, benchmark, fake_trades, args.capital)
    print_metrics(metrics)

    # 5. Report
    if not args.no_report and _PLOTLY:
        print("\n── Step 5: Generating HTML report ────────────────────────────")
        report_dir = Path(__file__).parent / "reports"
        report_dir.mkdir(exist_ok=True)
        out_path = report_dir / "IAM_hybrid_whale_report.html"
        html = _build_whale_report(metrics, equity, benchmark,
                                   signals_df, trades, params, stats)
        # Update title for hybrid
        html = html.replace("🐋 IAM Whale Strategy", "🧬 IAM Hybrid Whale Strategy")
        html = html.replace("Institutional Volume Detection", "Volume Spikes + Fundamental Scoring Engine Filtering")
        out_path.write_text(html, encoding="utf-8")
        print(f"  📊 Saved → {out_path}")
        import webbrowser
        webbrowser.open(out_path.as_uri())
        print(f"  ✅ Report opened in browser.")

    print("\n✅ Hybrid backtest complete.\n")


if __name__ == "__main__":
    main()
