"""
IAM Backtester — Entry Point
=============================
Usage:
    python backtest/run_backtest.py
    python backtest/run_backtest.py --no-sensitivity   (skip grid sweep, faster)
    python backtest/run_backtest.py --capital 200000
    python backtest/run_backtest.py --no-report        (console output only)
"""

import sys
import argparse
from pathlib import Path

# ── make project root importable ─────────────────────────────────────────────
_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_ROOT))

from backtest.data_loader      import load_price_data
from backtest.signal_generator import SignalGenerator
from backtest.engine           import BacktestEngine
from backtest.metrics          import compute_metrics, print_metrics
from backtest.parameter_sensitivity import run_sensitivity
from backtest.report           import generate_report


def parse_args():
    p = argparse.ArgumentParser(description="IAM Fundamentals-Based Backtest")
    p.add_argument("--capital",          type=float, default=100_000,
                   help="Starting capital in MAD (default: 100,000)")
    p.add_argument("--no-sensitivity",   action="store_true",
                   help="Skip parameter sensitivity sweep")
    p.add_argument("--no-report",        action="store_true",
                   help="Skip HTML report generation")
    p.add_argument("--no-dividends",     action="store_true",
                   help="Exclude dividend income from simulation")
    p.add_argument("--commission",       type=float, default=0.003,
                   help="Commission rate per trade (default: 0.003 = 0.3%%)")
    return p.parse_args()


def main():
    args = parse_args()

    print("=" * 60)
    print("  IAM BACKTEST ENGINE")
    print("  Itissalat Al-Maghrib — Casablanca Stock Exchange")
    print("=" * 60)

    # ── 1. Load price data ───────────────────────────────────────────────
    print("\n── Step 1: Loading price data ────────────────────────────────")
    price_df = load_price_data()

    # ── 2. Generate signals ──────────────────────────────────────────────
    print("\n── Step 2: Generating annual signals ─────────────────────────")
    generator = SignalGenerator()
    signals = generator.generate_all_signals(price_df)

    if not signals:
        print("\n[ERROR] No signals generated. Check that stock_data.json exists at:")
        print(f"  testing/testing/stock_data.json")
        sys.exit(1)

    print(f"\n  Generated {len(signals)} signals:")
    for s in signals:
        print(f"    FY{s['fiscal_year']}  {s['signal']:12s}  "
              f"upside {s['upside_pct']:+.1f}%  score {s['composite_score']:.0f}/100")

    # ── 3. Run backtest ──────────────────────────────────────────────────
    print("\n── Step 3: Simulating portfolio ──────────────────────────────")
    engine = BacktestEngine(
        price_df=price_df,
        signals=signals,
        initial_capital=args.capital,
        commission=args.commission,
        include_dividends=not args.no_dividends,
    )
    result = engine.run()

    # ── 4. Compute metrics ───────────────────────────────────────────────
    print("\n── Step 4: Computing metrics ─────────────────────────────────")
    metrics = compute_metrics(
        result.equity_curve,
        result.benchmark_curve,
        result.trades,
        args.capital,
    )
    result.metrics = metrics
    print_metrics(metrics)

    # ── 5. Parameter sensitivity ─────────────────────────────────────────
    sensitivity = None
    if not args.no_sensitivity:
        print("\n── Step 5: Parameter sensitivity sweep ───────────────────────")
        sensitivity = run_sensitivity(price_df, signals, initial_capital=args.capital)

    # ── 6. HTML report ───────────────────────────────────────────────────
    if not args.no_report:
        print("\n── Step 6: Generating report ─────────────────────────────────")
        try:
            report_path = generate_report(
                metrics=metrics,
                equity_curve=result.equity_curve,
                benchmark_curve=result.benchmark_curve,
                signals=signals,
                sensitivity=sensitivity,
            )
            # Try to auto-open in browser
            import webbrowser
            webbrowser.open(report_path.as_uri())
            print(f"  ✅ Report opened in browser.")
        except ImportError as e:
            print(f"  [WARN] Could not generate report: {e}")
            print("  Run: pip install plotly")

    print("\n✅ Backtest complete.\n")


if __name__ == "__main__":
    main()
