"""
IAM Backtesting Engine
======================
Validates your fundamental scoring parameters against historical price data.

Quick start:
    python backtest/run_backtest.py

Or programmatically:
    from backtest.data_loader      import load_price_data
    from backtest.signal_generator import SignalGenerator
    from backtest.engine           import BacktestEngine
    from backtest.metrics          import compute_metrics, print_metrics
    from backtest.report           import generate_report
"""
