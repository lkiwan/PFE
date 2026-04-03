"""
Backtest Metrics
================
Computes all performance statistics from the equity curve
and trade log produced by BacktestEngine.

Metrics computed:
  - Total Return (%)
  - CAGR (Compound Annual Growth Rate)
  - Annualized Volatility
  - Sharpe Ratio (vs risk-free rate)
  - Sortino Ratio (downside deviation)
  - Max Drawdown (%)
  - Calmar Ratio (CAGR / Max Drawdown)
  - Win Rate (% of closed trades that were profitable)
  - Average Win / Average Loss
  - Profit Factor
  - Benchmark comparison (buy-and-hold)
"""

from __future__ import annotations
import numpy as np
import pandas as pd
from typing import Dict, Any, List, Optional

TRADING_DAYS_PER_YEAR = 252
RISK_FREE_RATE_DAILY  = 0.035 / TRADING_DAYS_PER_YEAR   # Bank Al-Maghrib rate


def compute_metrics(
    equity_curve: pd.Series,
    benchmark_curve: pd.Series,
    trades: list,
    initial_capital: float,
) -> Dict[str, Any]:
    """Compute full performance metrics.

    Parameters
    ----------
    equity_curve : pd.Series
        Daily portfolio value (DatetimeIndex).
    benchmark_curve : pd.Series
        Daily buy-and-hold value (same index).
    trades : list of Trade dataclasses
        All trades including dividends.
    initial_capital : float
        Starting capital in MAD.

    Returns
    -------
    dict with all metrics (values are floats or strings).
    """
    m: Dict[str, Any] = {}

    if equity_curve.empty or len(equity_curve) < 2:
        return {"error": "Insufficient data for metrics"}

    # ── basic returns ──────────────────────────────────────────────────────
    start_val = initial_capital
    end_val   = float(equity_curve.iloc[-1])
    bh_end    = float(benchmark_curve.iloc[-1])

    m["initial_capital_mad"]   = round(start_val, 2)
    m["final_value_mad"]       = round(end_val, 2)
    m["total_return_pct"]      = round((end_val / start_val - 1) * 100, 2)
    m["total_profit_mad"]      = round(end_val - start_val, 2)
    m["benchmark_return_pct"]  = round((bh_end / start_val - 1) * 100, 2)
    m["excess_return_pct"]     = round(m["total_return_pct"] - m["benchmark_return_pct"], 2)

    # ── time period ────────────────────────────────────────────────────────
    start_date = equity_curve.index[0]
    end_date   = equity_curve.index[-1]
    n_days     = (end_date - start_date).days
    n_years    = n_days / 365.25

    m["start_date"]  = str(start_date.date())
    m["end_date"]    = str(end_date.date())
    m["period_days"] = n_days
    m["period_years"] = round(n_years, 2)

    # ── CAGR ───────────────────────────────────────────────────────────────
    if n_years > 0 and start_val > 0 and end_val > 0:
        m["cagr_pct"]      = round(((end_val / start_val) ** (1 / n_years) - 1) * 100, 2)
        m["bh_cagr_pct"]   = round(((bh_end / start_val) ** (1 / n_years) - 1) * 100, 2)
    else:
        m["cagr_pct"] = m["bh_cagr_pct"] = 0.0

    # ── daily returns ──────────────────────────────────────────────────────
    daily_ret    = equity_curve.pct_change().dropna()
    bh_daily_ret = benchmark_curve.pct_change().dropna()

    if len(daily_ret) < 2:
        m["sharpe_ratio"] = m["sortino_ratio"] = m["volatility_pct"] = 0.0
    else:
        # Annualized volatility
        vol = daily_ret.std() * np.sqrt(TRADING_DAYS_PER_YEAR)
        m["volatility_pct"]    = round(vol * 100, 2)
        m["bh_volatility_pct"] = round(bh_daily_ret.std() * np.sqrt(TRADING_DAYS_PER_YEAR) * 100, 2)

        # Sharpe ratio
        excess_daily = daily_ret - RISK_FREE_RATE_DAILY
        sharpe = excess_daily.mean() / daily_ret.std() * np.sqrt(TRADING_DAYS_PER_YEAR) if daily_ret.std() > 0 else 0
        m["sharpe_ratio"] = round(sharpe, 3)

        # Sortino ratio (downside deviation only)
        downside = daily_ret[daily_ret < 0]
        down_dev = downside.std() * np.sqrt(TRADING_DAYS_PER_YEAR) if len(downside) > 1 else vol
        sortino = (m["cagr_pct"] / 100 - 0.035) / down_dev if down_dev > 0 else 0
        m["sortino_ratio"] = round(sortino, 3)

    # ── drawdown ───────────────────────────────────────────────────────────
    rolling_max  = equity_curve.cummax()
    drawdown_ser = (equity_curve - rolling_max) / rolling_max * 100
    m["max_drawdown_pct"]  = round(float(drawdown_ser.min()), 2)
    m["drawdown_series"]   = drawdown_ser   # keep for charting

    bh_roll_max = benchmark_curve.cummax()
    bh_dd       = (benchmark_curve - bh_roll_max) / bh_roll_max * 100
    m["bh_max_drawdown_pct"] = round(float(bh_dd.min()), 2)
    m["bh_drawdown_series"]  = bh_dd

    # ── Calmar ratio (CAGR / |Max DD|) ────────────────────────────────────
    if m["max_drawdown_pct"] < 0:
        m["calmar_ratio"] = round(m["cagr_pct"] / abs(m["max_drawdown_pct"]), 3)
    else:
        m["calmar_ratio"] = None

    # ── trade statistics ───────────────────────────────────────────────────
    buy_trades  = [t for t in trades if t.action == "BUY"]
    sell_trades = [t for t in trades if t.action == "SELL"]
    div_trades  = [t for t in trades if t.action == "DIVIDEND"]

    m["total_trades"]      = len(buy_trades)
    m["total_dividends"]   = len(div_trades)
    m["dividend_income_mad"] = round(sum(t.cash_flow for t in div_trades), 2)

    # Match buys with sells to compute win/loss per round trip
    pnl_list = _compute_round_trip_pnl(buy_trades, sell_trades)
    if pnl_list:
        wins  = [p for p in pnl_list if p > 0]
        losses= [p for p in pnl_list if p <= 0]
        m["win_rate_pct"]    = round(len(wins) / len(pnl_list) * 100, 1)
        m["avg_win_mad"]     = round(np.mean(wins), 2) if wins else 0
        m["avg_loss_mad"]    = round(np.mean(losses), 2) if losses else 0
        m["profit_factor"]   = (
            round(abs(sum(wins)) / abs(sum(losses)), 2)
            if losses and sum(losses) != 0 else None
        )
        m["round_trip_pnl"]  = [round(p, 2) for p in pnl_list]
    else:
        m["win_rate_pct"] = m["avg_win_mad"] = m["avg_loss_mad"] = None
        m["profit_factor"] = m["round_trip_pnl"] = None

    # ── total commissions paid ─────────────────────────────────────────────
    m["total_commission_mad"] = round(
        sum(t.commission for t in trades if t.action in ("BUY", "SELL")), 2
    )

    return m


def _compute_round_trip_pnl(buy_trades: list, sell_trades: list) -> List[float]:
    """Match each BUY with the subsequent SELL and compute profit (MAD)."""
    pnl = []
    buy_q   = list(buy_trades)
    sell_q  = list(sell_trades)

    while buy_q and sell_q:
        b = buy_q.pop(0)
        s = sell_q.pop(0)
        proceeds = s.shares * s.price - s.commission
        cost     = b.shares * b.price + b.commission
        pnl.append(proceeds - cost)
    return pnl


def print_metrics(m: Dict[str, Any]) -> None:
    """Pretty-print the metrics dict to console."""
    print("\n" + "═" * 58)
    print("  BACKTEST RESULTS — IAM (Itissalat Al-Maghrib)")
    print("═" * 58)
    print(f"  Period          : {m['start_date']} → {m['end_date']}  ({m['period_years']} years)")
    print(f"  Initial capital : {m['initial_capital_mad']:>12,.0f} MAD")
    print(f"  Final value     : {m['final_value_mad']:>12,.0f} MAD")
    print(f"  Total profit    : {m['total_profit_mad']:>+12,.0f} MAD")
    print()
    print(f"  {'Metric':<28}  {'Strategy':>10}  {'Buy & Hold':>10}")
    print(f"  {'─'*28}  {'─'*10}  {'─'*10}")
    print(f"  {'Total Return':<28}  {m['total_return_pct']:>+9.1f}%  {m['benchmark_return_pct']:>+9.1f}%")
    print(f"  {'CAGR':<28}  {m['cagr_pct']:>+9.1f}%  {m['bh_cagr_pct']:>+9.1f}%")
    print(f"  {'Volatility (ann.)':<28}  {m['volatility_pct']:>9.1f}%  {m['bh_volatility_pct']:>9.1f}%")
    print(f"  {'Sharpe Ratio':<28}  {m['sharpe_ratio']:>10.3f}  {'—':>10}")
    print(f"  {'Sortino Ratio':<28}  {m['sortino_ratio']:>10.3f}  {'—':>10}")
    print(f"  {'Max Drawdown':<28}  {m['max_drawdown_pct']:>9.1f}%  {m['bh_max_drawdown_pct']:>9.1f}%")
    print(f"  {'Calmar Ratio':<28}  {str(m['calmar_ratio']):>10}  {'—':>10}")
    print(f"  {'Excess Return vs B&H':<28}  {m['excess_return_pct']:>+9.1f}%  {'—':>10}")
    print()
    print(f"  Trades executed : {m['total_trades']}  |  Win Rate: {m.get('win_rate_pct', '—')}%")
    print(f"  Avg Win         : {m.get('avg_win_mad', '—')} MAD  |  Avg Loss: {m.get('avg_loss_mad', '—')} MAD")
    print(f"  Dividends rcvd  : {m['total_dividends']} payments = {m['dividend_income_mad']:,.0f} MAD")
    print(f"  Commissions paid: {m['total_commission_mad']:,.0f} MAD")
    print("═" * 58)
