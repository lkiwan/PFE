"""
Whale Strategy Backtest Runner
================================
Runs the whale strategy against IAM historical price data
and generates an HTML report.

Usage:
    python backtest/run_whale_backtest.py
    python backtest/run_whale_backtest.py --volume-threshold 3.0
    python backtest/run_whale_backtest.py --stop-loss 10 --take-profit 30
    python backtest/run_whale_backtest.py --start 2015-01-01
    python backtest/run_whale_backtest.py --no-report
"""

from __future__ import annotations
import sys
import argparse
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_ROOT))

import numpy as np
import pandas as pd
from backtest.data_loader import load_price_data
from backtest.metrics import compute_metrics, print_metrics
from strategies.whale_strategy import WhaleStrategy, WhaleParams

try:
    import plotly.graph_objects as go
    from plotly.subplots import make_subplots
    import plotly.io as pio
    _PLOTLY = True
except ImportError:
    _PLOTLY = False


# ─── portfolio simulator (whale-specific — daily rebalancing) ─────────────────

def simulate_whale_portfolio(
    price_df: pd.DataFrame,
    signals_df: pd.DataFrame,
    initial_capital: float = 100_000.0,
    commission: float = 0.003,
) -> tuple:
    """
    Simulate the portfolio day by day following whale signals.
    Returns (equity_curve, benchmark_curve, trades_list).
    """
    cash   = initial_capital
    shares = 0.0
    trades = []
    equity_values = []

    bench_start = float(price_df.iloc[0]["close"])
    bench_shares = initial_capital / bench_start

    for date, row in price_df.iterrows():
        price = float(row["close"])
        if pd.isna(price) or price <= 0:
            continue

        # Get signal for this day (if any)
        sig_row  = signals_df.loc[date] if date in signals_df.index else None
        signal   = sig_row["signal"] if sig_row is not None else "HOLD"

        # Execute signal
        if signal == "BUY" and shares == 0 and cash > price:
            buy_amount = cash
            shares_to_buy = int((buy_amount / (1 + commission)) / price)
            if shares_to_buy > 0:
                cost = shares_to_buy * price * (1 + commission)
                commission_paid = shares_to_buy * price * commission
                cash   -= cost
                shares  = shares_to_buy
                trades.append({
                    "date": date, "action": "BUY", "shares": shares_to_buy,
                    "price": price, "commission": commission_paid,
                    "cash_flow": -cost,
                    "reason": sig_row["reason"] if sig_row is not None else "",
                    "vol_ratio": sig_row["vol_ratio"] if sig_row is not None else 0,
                    "portfolio_value": cash + shares * price,
                })

        elif signal == "SELL" and shares > 0:
            gross = shares * price
            commission_paid = gross * commission
            proceeds = gross - commission_paid
            sold = shares
            cash   += proceeds
            shares  = 0.0
            trades.append({
                "date": date, "action": "SELL", "shares": sold,
                "price": price, "commission": commission_paid,
                "cash_flow": proceeds,
                "reason": sig_row["reason"] if sig_row is not None else "",
                "vol_ratio": sig_row["vol_ratio"] if sig_row is not None else 0,
                "portfolio_value": cash,
            })

        pv = cash + shares * price
        bv = bench_shares * price
        equity_values.append({"date": date, "strategy": pv, "benchmark": bv})

    df_eq = pd.DataFrame(equity_values).set_index("date")
    equity    = df_eq["strategy"]
    benchmark = df_eq["benchmark"]
    return equity, benchmark, trades


# ─── report builder ───────────────────────────────────────────────────────────

def _build_whale_report(
    metrics: dict,
    equity: pd.Series,
    benchmark: pd.Series,
    signals_df: pd.DataFrame,
    trades: list,
    params: WhaleParams,
    stats: dict,
) -> str:
    """Build the HTML report."""

    plotly_cdn = '<script src="https://cdn.plot.ly/plotly-2.30.0.min.js"></script>'

    # ── chart 1: equity curve ─────────────────────────────────────────────
    fig1 = go.Figure()
    fig1.add_trace(go.Scatter(x=equity.index, y=equity.values,
        name="Whale Strategy", line=dict(color="#f59e0b", width=2.5),
        fill="tozeroy", fillcolor="rgba(245,158,11,0.07)"))
    fig1.add_trace(go.Scatter(x=benchmark.index, y=benchmark.values,
        name="Buy & Hold IAM", line=dict(color="#60a5fa", width=2, dash="dash")))
    fig1.update_layout(title="Equity Curve — Whale Strategy vs Buy & Hold",
        template="plotly_dark", height=400,
        margin=dict(l=40, r=20, t=50, b=40),
        yaxis_title="Portfolio Value (MAD)", xaxis_title="Date",
        legend=dict(orientation="h", y=1.02, x=1, xanchor="right", yanchor="bottom"))
    chart1 = pio.to_html(fig1, full_html=False, include_plotlyjs=False)

    # ── chart 2: volume with whale signal markers ─────────────────────────
    whale_days = signals_df[signals_df["is_whale_day"]]
    buy_sigs   = signals_df[signals_df["signal"] == "BUY"]
    sell_sigs  = signals_df[signals_df["signal"] == "SELL"]

    fig2 = make_subplots(rows=2, cols=1, shared_xaxes=True,
                         row_heights=[0.6, 0.4], vertical_spacing=0.05)
    fig2.add_trace(go.Scatter(x=signals_df.index, y=signals_df["close"],
        name="Price", line=dict(color="#e2e8f0", width=1.2)), row=1, col=1)
    fig2.add_trace(go.Scatter(x=signals_df.index, y=signals_df["sma50"],
        name="SMA-50", line=dict(color="#94a3b8", width=1, dash="dot")), row=1, col=1)
    if len(buy_sigs):
        fig2.add_trace(go.Scatter(x=buy_sigs.index, y=buy_sigs["close"],
            mode="markers", name="BUY signal",
            marker=dict(symbol="triangle-up", color="#22c55e", size=10)), row=1, col=1)
    if len(sell_sigs):
        fig2.add_trace(go.Scatter(x=sell_sigs.index, y=sell_sigs["close"],
            mode="markers", name="SELL signal",
            marker=dict(symbol="triangle-down", color="#ef4444", size=10)), row=1, col=1)
    # Volume bars
    fig2.add_trace(go.Bar(x=signals_df.index, y=signals_df["volume"],
        name="Daily Volume", marker_color="#334155"), row=2, col=1)
    if len(whale_days):
        fig2.add_trace(go.Bar(x=whale_days.index, y=whale_days["volume"],
            name=f"Whale Day (>{params.volume_threshold}× avg)",
            marker_color="#f59e0b"), row=2, col=1)
    fig2.update_layout(title="IAM Price + Whale Volume Detection",
        template="plotly_dark", height=550, barmode="overlay",
        margin=dict(l=40, r=20, t=50, b=40))
    chart2 = pio.to_html(fig2, full_html=False, include_plotlyjs=False)

    # ── chart 3: drawdown ────────────────────────────────────────────────
    dd = metrics.get("drawdown_series")
    bh_dd = metrics.get("bh_drawdown_series")
    fig3 = go.Figure()
    if dd is not None:
        fig3.add_trace(go.Scatter(x=dd.index, y=dd.values, name="Strategy",
            line=dict(color="#f87171", width=2), fill="tozeroy",
            fillcolor="rgba(248,113,113,0.12)"))
    if bh_dd is not None:
        fig3.add_trace(go.Scatter(x=bh_dd.index, y=bh_dd.values, name="B&H",
            line=dict(color="#94a3b8", width=1.5, dash="dot")))
    fig3.update_layout(title="Drawdown (%)", template="plotly_dark", height=280,
        margin=dict(l=40, r=20, t=50, b=40))
    chart3 = pio.to_html(fig3, full_html=False, include_plotlyjs=False)

    # ── trade table ───────────────────────────────────────────────────────
    trade_rows = ""
    for t in trades:
        color = "#22c55e" if t["action"] == "BUY" else "#ef4444"
        trade_rows += f"""<tr>
          <td>{str(t['date'].date())}</td>
          <td style='color:{color};font-weight:700'>{t['action']}</td>
          <td>{t['shares']:,}</td>
          <td>{t['price']:.2f}</td>
          <td>{t['vol_ratio']:.1f}×</td>
          <td style='font-size:.78rem;color:#94a3b8'>{t['reason'][:90]}</td>
        </tr>"""

    # ── metric cards ─────────────────────────────────────────────────────
    def card(label, val, bh="", good=None):
        col = "#4ade80" if good is True else ("#f87171" if good is False else "#e2e8f0")
        bh_html = f"<span class='bh'>B&H: {bh}</span>" if bh else ""
        return f"<div class='card'><div class='lbl'>{label}</div><div class='val' style='color:{col}'>{val}</div>{bh_html}</div>"

    m = metrics
    tot_ret   = m.get("total_return_pct", 0) or 0
    bh_ret    = m.get("benchmark_return_pct", 0) or 0
    cagr      = m.get("cagr_pct", 0) or 0
    bh_cagr   = m.get("bh_cagr_pct", 0) or 0
    sharpe    = m.get("sharpe_ratio", 0) or 0
    max_dd    = m.get("max_drawdown_pct", 0) or 0
    bh_dd_val = m.get("bh_max_drawdown_pct", 0) or 0
    excess    = m.get("excess_return_pct", 0) or 0
    n_trades  = m.get("total_trades", 0) or 0
    vol       = m.get("volatility_pct", 0) or 0
    sortino   = m.get("sortino_ratio", 0) or 0
    calmar    = m.get("calmar_ratio")

    cards = "".join([
        card("Total Return",   f"{tot_ret:+.1f}%",  f"{bh_ret:+.1f}%",  tot_ret > 0),
        card("CAGR",           f"{cagr:+.1f}%",     f"{bh_cagr:+.1f}%", cagr > 0),
        card("Sharpe Ratio",   f"{sharpe:.3f}",      good=sharpe > 0.5),
        card("Sortino Ratio",  f"{sortino:.3f}"),
        card("Max Drawdown",   f"{max_dd:.1f}%",    f"{bh_dd_val:.1f}%", max_dd > -20),
        card("Calmar Ratio",   f"{calmar or '—'}"),
        card("# Trades",       str(n_trades)),
        card("Volatility",     f"{vol:.1f}%",       f"{m.get('bh_volatility_pct',0):.1f}%"),
        card("Win Rate",       f"{m.get('win_rate_pct') or '—'}%"),
        card("Exc. vs B&H",   f"{excess:+.1f}%",   good=excess > 0),
        card("Whale Days",    f"{stats['whale_day_pct']}% of days"),
        card("Signals",       f"{stats['buy_signals']} BUY / {stats['sell_signals']} SELL"),
    ])

    verdict = "✅ Outperformed" if excess > 0 else "❌ Underperformed"
    verdict_color = "#4ade80" if excess > 0 else "#f87171"
    period = f"{m.get('start_date','?')} → {m.get('end_date','?')} ({m.get('period_years','?')} yrs)"

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>IAM Whale Strategy Backtest</title>
{plotly_cdn}
<style>
  *, *::before, *::after {{ box-sizing: border-box; margin:0; padding:0; }}
  body {{ background:#0f172a; color:#e2e8f0; font-family:'Segoe UI',system-ui,sans-serif;
         font-size:14px; line-height:1.6; padding:24px; }}
  h1   {{ font-size:1.7rem; font-weight:700; color:#f8fafc; }}
  h2   {{ font-size:1rem; font-weight:600; color:#94a3b8; margin:28px 0 12px;
         text-transform:uppercase; letter-spacing:.05em;
         border-bottom:1px solid #1e293b; padding-bottom:6px; }}
  .header {{ background:#1e293b; border-radius:12px; padding:20px 24px;
             margin-bottom:24px; display:flex; gap:24px; align-items:flex-start; }}
  .ticker {{ font-size:2.6rem; font-weight:800; color:#f59e0b; line-height:1; }}
  .sub    {{ color:#94a3b8; font-size:.85rem; margin-top:4px; }}
  .verdict {{ font-size:1.35rem; font-weight:700; color:{verdict_color}; margin-top:8px; }}
  .period  {{ color:#64748b; font-size:.82rem; margin-top:2px; }}
  .params  {{ background:#0f172a; border-radius:8px; padding:10px 14px;
              font-size:.8rem; color:#94a3b8; margin-top:12px; }}
  .params b {{ color:#f59e0b; }}
  .cards {{ display:grid; grid-template-columns:repeat(auto-fill,minmax(155px,1fr));
            gap:12px; margin-bottom:24px; }}
  .card  {{ background:#1e293b; border-radius:10px; padding:14px 16px;
            border:1px solid #334155; }}
  .lbl   {{ font-size:.74rem; color:#64748b; text-transform:uppercase;
            letter-spacing:.06em; margin-bottom:4px; }}
  .val   {{ font-size:1.3rem; font-weight:700; }}
  .bh    {{ font-size:.74rem; color:#64748b; margin-top:2px; display:block; }}
  .box   {{ background:#1e293b; border-radius:12px; padding:16px;
            margin-bottom:20px; border:1px solid #334155; }}
  .how-it-works {{ background:#1e293b; border-radius:12px; padding:20px 24px;
                   margin-bottom:24px; border-left:4px solid #f59e0b; }}
  .how-it-works h3 {{ color:#f59e0b; margin-bottom:12px; font-size:1rem; }}
  .step  {{ display:flex; gap:12px; margin-bottom:10px; }}
  .step-n {{ background:#f59e0b; color:#000; border-radius:50%; width:24px; height:24px;
             display:flex; align-items:center; justify-content:center;
             font-weight:700; font-size:.8rem; flex-shrink:0; margin-top:2px; }}
  .step-txt {{ font-size:.88rem; color:#cbd5e1; }}
  table  {{ width:100%; border-collapse:collapse; font-size:.8rem; }}
  th     {{ background:#1e293b; color:#94a3b8; padding:8px 10px; text-align:left;
            font-weight:600; text-transform:uppercase; letter-spacing:.04em; }}
  td     {{ padding:8px 10px; border-bottom:1px solid #1e293b; }}
  tr:hover td {{ background:#1e293b55; }}
  .footer {{ margin-top:40px; color:#475569; font-size:.74rem; text-align:center; }}
</style>
</head>
<body>

<div class="header">
  <div style="flex:1">
    <div class="ticker">🐋 IAM Whale Strategy</div>
    <div class="sub">Itissalat Al-Maghrib · Casablanca Stock Exchange · Institutional Volume Detection</div>
    <div class="verdict">{verdict} Buy &amp; Hold by {abs(excess):.1f}%</div>
    <div class="period">Period: {period}</div>
    <div class="params">
      Parameters used →
      <b>Volume threshold:</b> {params.volume_threshold}× avg &nbsp;|&nbsp;
      <b>Price move:</b> ≥{params.price_threshold}% &nbsp;|&nbsp;
      <b>SMA filter:</b> {params.sma_period}-day &nbsp;|&nbsp;
      <b>Stop-loss:</b> {params.stop_loss_pct}% &nbsp;|&nbsp;
      <b>Take-profit:</b> {params.take_profit_pct}%
    </div>
  </div>
  <div style="text-align:right">
    <div style="font-size:.85rem;color:#64748b">Final Value</div>
    <div style="font-size:1.5rem;font-weight:700;color:#4ade80">{m.get('final_value_mad',0):,.0f} MAD</div>
    <div style="font-size:.85rem;color:#64748b;margin-top:8px">Whale days detected</div>
    <div style="font-size:1.5rem;font-weight:700;color:#f59e0b">{stats['whale_days']:,}</div>
  </div>
</div>

<div class="how-it-works">
  <h3>🧠 How the Whale Strategy Works — Plain English</h3>
  <div class="step"><div class="step-n">1</div>
    <div class="step-txt"><b>Every day</b>, compute the 20-day rolling average volume. This is your baseline for "normal" trading on IAM.</div></div>
  <div class="step"><div class="step-n">2</div>
    <div class="step-txt"><b>Detect whale days</b>: if today's volume is <b>{params.volume_threshold}× or more</b> of that average, a big institutional player (whale) is active.</div></div>
  <div class="step"><div class="step-n">3</div>
    <div class="step-txt"><b>Confirm direction</b>: did the price go UP ≥{params.price_threshold}% that day? → whale is BUYING (accumulation) → we <b style='color:#22c55e'>BUY</b>. Did it go DOWN? → whale is SELLING → we <b style='color:#ef4444'>SELL</b>.</div></div>
  <div class="step"><div class="step-n">4</div>
    <div class="step-txt"><b>Trend filter</b>: only BUY if price is above the {params.sma_period}-day moving average (confirms we're in an uptrend, not a dead-cat bounce).</div></div>
  <div class="step"><div class="step-n">5</div>
    <div class="step-txt"><b>Exit rules</b>: sell if a whale distribution is detected, OR if the position drops {params.stop_loss_pct}% (stop-loss), OR gains {params.take_profit_pct}% (take-profit).</div></div>
</div>

<h2>📊 Performance Metrics</h2>
<div class="cards">{cards}</div>

<div class="box">{chart1}</div>
<div class="box">{chart2}</div>
<div class="box">{chart3}</div>

<h2>📋 Trade Log</h2>
<div class="box">
<table>
  <thead><tr><th>Date</th><th>Action</th><th>Shares</th><th>Price</th><th>Vol Ratio</th><th>Reason</th></tr></thead>
  <tbody>{trade_rows}</tbody>
</table>
</div>

<div class="footer">
  Whale Strategy · IAM · CSE · Commission 0.3% · Volume MA={params.volume_ma_period}d · Stop={params.stop_loss_pct}% · TP={params.take_profit_pct}%
</div>
</body>
</html>"""


# ─── CLI ──────────────────────────────────────────────────────────────────────

def parse_args():
    p = argparse.ArgumentParser(description="IAM Whale Strategy Backtest")
    p.add_argument("--capital",           type=float, default=100_000)
    p.add_argument("--volume-threshold",  type=float, default=2.5)
    p.add_argument("--price-threshold",   type=float, default=0.3)
    p.add_argument("--stop-loss",         type=float, default=8.0)
    p.add_argument("--take-profit",       type=float, default=25.0)
    p.add_argument("--sma-period",        type=int,   default=50)
    p.add_argument("--start",             type=str,   default=None,
                   help="Start date e.g. 2015-01-01")
    p.add_argument("--no-report",         action="store_true")
    return p.parse_args()


def main():
    args = parse_args()

    print("=" * 60)
    print("  🐋 IAM WHALE STRATEGY BACKTEST")
    print("=" * 60)

    # 1. Load price data
    print("\n── Step 1: Loading price data ────────────────────────────────")
    df = load_price_data()
    if args.start:
        df = df[df.index >= pd.Timestamp(args.start)]
        print(f"  Filtered to start from {args.start} ({len(df):,} days)")

    # 2. Build parameters & run strategy
    print("\n── Step 2: Detecting whale activity ──────────────────────────")
    params = WhaleParams(
        volume_threshold = args.volume_threshold,
        price_threshold  = args.price_threshold,
        stop_loss_pct    = args.stop_loss,
        take_profit_pct  = args.take_profit,
        sma_period       = args.sma_period,
    )
    strategy   = WhaleStrategy(params)
    signals_df = strategy.generate_signals(df)
    stats      = strategy.summary_stats(signals_df)

    print(f"  Total trading days : {stats['total_days']:,}")
    print(f"  Whale days detected: {stats['whale_days']:,} ({stats['whale_day_pct']}% of all days)")
    print(f"  Max volume ratio   : {stats['max_vol_ratio']}× normal")
    print(f"  BUY signals        : {stats['buy_signals']}")
    print(f"  SELL signals       : {stats['sell_signals']}")

    # 3. Simulate portfolio
    print("\n── Step 3: Simulating portfolio ──────────────────────────────")
    equity, benchmark, trades = simulate_whale_portfolio(
        df, signals_df, initial_capital=args.capital
    )
    print(f"  Trades executed    : {sum(1 for t in trades if t['action']=='BUY')} BUY, "
          f"{sum(1 for t in trades if t['action']=='SELL')} SELL")

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
        out_path = report_dir / "IAM_whale_strategy_report.html"
        html = _build_whale_report(metrics, equity, benchmark,
                                   signals_df, trades, params, stats)
        out_path.write_text(html, encoding="utf-8")
        print(f"  📊 Saved → {out_path}")
        import webbrowser
        webbrowser.open(out_path.as_uri())
        print(f"  ✅ Report opened in browser.")

    print("\n✅ Whale backtest complete.\n")


if __name__ == "__main__":
    main()
