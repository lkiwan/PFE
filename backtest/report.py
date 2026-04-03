"""
Backtest HTML Report Generator
================================
Produces a fully self-contained HTML report with embedded Plotly charts.

Sections:
  1. Header — stock info, date range, summary verdict
  2. Metric Scorecard — key stats vs buy-and-hold
  3. Equity Curve — portfolio vs buy-and-hold over time
  4. Drawdown Chart — rolling drawdown
  5. Signal & Trade Log — table of all annual signals
  6. Parameter Sensitivity Heatmap — Sharpe across param grid
  7. Factor Scores Per Year — radar/bar of scoring engine output
"""

from __future__ import annotations
import json
from pathlib import Path
from typing import Dict, Any, List, Optional
import pandas as pd

try:
    import plotly.graph_objects as go
    import plotly.express as px
    from plotly.subplots import make_subplots
    import plotly.io as pio
    _PLOTLY_OK = True
except ImportError:
    _PLOTLY_OK = False
    print("[WARN] plotly not installed — run: pip install plotly")


_REPORT_DIR = Path(__file__).parent / "reports"


def _fmt(v, suffix="", decimals=1):
    if v is None:
        return "—"
    if isinstance(v, float):
        return f"{v:+.{decimals}f}{suffix}" if suffix == "%" else f"{v:.{decimals}f}{suffix}"
    return str(v)


def generate_report(
    metrics: Dict[str, Any],
    equity_curve: pd.Series,
    benchmark_curve: pd.Series,
    signals: List[Dict],
    sensitivity: Optional[Dict] = None,
    output_path: Optional[Path] = None,
) -> Path:
    """Build and save the HTML report. Returns the path to the file."""
    if not _PLOTLY_OK:
        raise ImportError("Install plotly first: pip install plotly")

    _REPORT_DIR.mkdir(parents=True, exist_ok=True)
    output_path = output_path or (_REPORT_DIR / "IAM_backtest_report.html")

    html = _build_html(metrics, equity_curve, benchmark_curve, signals, sensitivity)
    output_path.write_text(html, encoding="utf-8")
    print(f"\n  📊 Report saved → {output_path}")
    return output_path


# ─── chart builders ───────────────────────────────────────────────────────────

def _equity_chart_html(equity: pd.Series, benchmark: pd.Series) -> str:
    fig = go.Figure()
    fig.add_trace(go.Scatter(
        x=equity.index, y=equity.values,
        name="Your Strategy", line=dict(color="#4ade80", width=2.5),
        fill="tozeroy", fillcolor="rgba(74,222,128,0.07)",
    ))
    fig.add_trace(go.Scatter(
        x=benchmark.index, y=benchmark.values,
        name="Buy & Hold IAM", line=dict(color="#60a5fa", width=2, dash="dash"),
    ))
    fig.update_layout(
        title="Portfolio Value vs Buy & Hold",
        xaxis_title="Date", yaxis_title="Portfolio Value (MAD)",
        template="plotly_dark", height=420,
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
        margin=dict(l=40, r=20, t=60, b=40),
    )
    return pio.to_html(fig, full_html=False, include_plotlyjs=False)


def _drawdown_chart_html(metrics: Dict) -> str:
    dd  = metrics.get("drawdown_series")
    bh  = metrics.get("bh_drawdown_series")
    if dd is None:
        return ""
    fig = go.Figure()
    fig.add_trace(go.Scatter(
        x=dd.index, y=dd.values, name="Strategy Drawdown",
        line=dict(color="#f87171", width=2),
        fill="tozeroy", fillcolor="rgba(248,113,113,0.15)",
    ))
    if bh is not None:
        fig.add_trace(go.Scatter(
            x=bh.index, y=bh.values, name="B&H Drawdown",
            line=dict(color="#94a3b8", width=1.5, dash="dot"),
        ))
    fig.update_layout(
        title="Drawdown (%)",
        xaxis_title="Date", yaxis_title="Drawdown (%)",
        template="plotly_dark", height=300,
        margin=dict(l=40, r=20, t=50, b=40),
    )
    return pio.to_html(fig, full_html=False, include_plotlyjs=False)


def _heatmap_html(sensitivity: Dict) -> str:
    hm: pd.DataFrame = sensitivity.get("heatmap_df")
    if hm is None:
        return ""
    fig = go.Figure(data=go.Heatmap(
        z=hm.values.astype(float),
        x=list(hm.columns),
        y=list(hm.index),
        colorscale="RdYlGn",
        text=[[f"{v:.2f}" if pd.notna(v) else "—" for v in row] for row in hm.values],
        texttemplate="%{text}",
        showscale=True,
        colorbar=dict(title="Sharpe"),
    ))
    fig.update_layout(
        title="Sharpe Ratio — Parameter Sensitivity (Upside% × Composite Score Threshold)",
        template="plotly_dark", height=380,
        xaxis_title="Min Composite Score", yaxis_title="Min Upside Threshold",
        margin=dict(l=80, r=20, t=60, b=60),
    )
    return pio.to_html(fig, full_html=False, include_plotlyjs=False)


def _factor_scores_html(signals: List[Dict]) -> str:
    """Bar chart of composite scores per fiscal year."""
    years, scores, rec_colors = [], [], []
    color_map = {
        "STRONG BUY": "#22c55e", "BUY": "#86efac",
        "HOLD": "#facc15",
        "SELL": "#f97316", "STRONG SELL": "#ef4444",
    }
    for s in signals:
        years.append(f"FY{s['fiscal_year']}")
        scores.append(s.get("composite_score", 0))
        rec_colors.append(color_map.get(s.get("signal", "HOLD"), "#94a3b8"))

    fig = go.Figure()
    for i, (y, sc, col, sig) in enumerate(zip(years, scores, rec_colors, signals)):
        fig.add_trace(go.Bar(
            x=[y], y=[sc],
            name=sig.get("signal", ""),
            marker_color=col,
            showlegend=(i == 0),
            text=[f"{sc:.0f}"],
            textposition="outside",
        ))
    # Reference lines
    fig.add_hline(y=55, line_dash="dash", line_color="#60a5fa",
                  annotation_text="BUY threshold (55)", annotation_position="right")
    fig.add_hline(y=65, line_dash="dot", line_color="#4ade80",
                  annotation_text="STRONG BUY (65)", annotation_position="right")
    fig.update_layout(
        title="Composite Score per Annual Checkpoint",
        xaxis_title="Fiscal Year", yaxis_title="Composite Score (0–100)",
        template="plotly_dark", height=340, barmode="group",
        margin=dict(l=40, r=100, t=50, b=40),
        yaxis=dict(range=[0, 105]),
        showlegend=False,
    )
    return pio.to_html(fig, full_html=False, include_plotlyjs=False)


# ─── signal table ─────────────────────────────────────────────────────────────

def _signal_table_html(signals: List[Dict]) -> str:
    badge = {
        "STRONG BUY":  "background:#16a34a;color:#fff",
        "BUY":         "background:#86efac;color:#14532d",
        "HOLD":        "background:#ca8a04;color:#fff",
        "SELL":        "background:#ea580c;color:#fff",
        "STRONG SELL": "background:#dc2626;color:#fff",
    }
    rows = ""
    for s in signals:
        sig = s.get("signal", "—")
        style = badge.get(sig, "")
        price_sig = s.get("price_at_signal", 0)
        price_exec = s.get("execution_price", price_sig)
        iv = s.get("intrinsic_value", 0)
        rows += f"""
        <tr>
          <td>FY{s['fiscal_year']}</td>
          <td>{str(s['signal_date'].date())}</td>
          <td>{price_sig:.2f}</td>
          <td>{price_exec:.2f}</td>
          <td>{iv:.2f}</td>
          <td style='color:{"#4ade80" if s["upside_pct"]>=0 else "#f87171"}'>{s['upside_pct']:+.1f}%</td>
          <td>{s.get('composite_score', 0):.1f}/100</td>
          <td><span style='padding:2px 8px;border-radius:4px;font-weight:600;{style}'>{sig}</span></td>
        </tr>"""
    return f"""
    <table>
      <thead><tr>
        <th>FY</th><th>Signal Date</th><th>Price (MAD)</th><th>Exec Price</th>
        <th>Fair Value</th><th>Upside</th><th>Score</th><th>Signal</th>
      </tr></thead>
      <tbody>{rows}</tbody>
    </table>"""


# ─── metric card ──────────────────────────────────────────────────────────────

def _metric_card(label: str, val_strat: str, val_bh: str = "", highlight: str = "") -> str:
    color = "#4ade80" if highlight == "good" else ("#f87171" if highlight == "bad" else "#e2e8f0")
    bh_part = f"<span class='bh'>B&H: {val_bh}</span>" if val_bh else ""
    return f"""
    <div class='card'>
      <div class='card-label'>{label}</div>
      <div class='card-value' style='color:{color}'>{val_strat}</div>
      {bh_part}
    </div>"""


# ─── full HTML ────────────────────────────────────────────────────────────────

def _build_html(
    m: Dict[str, Any],
    equity: pd.Series,
    benchmark: pd.Series,
    signals: List[Dict],
    sensitivity: Optional[Dict],
) -> str:

    plotly_cdn = '<script src="https://cdn.plot.ly/plotly-2.30.0.min.js"></script>'
    equity_chart   = _equity_chart_html(equity, benchmark)
    drawdown_chart = _drawdown_chart_html(m)
    factor_chart   = _factor_scores_html(signals)
    heatmap_chart  = _heatmap_html(sensitivity) if sensitivity else ""
    signal_table   = _signal_table_html(signals)

    excess = m.get("excess_return_pct", 0) or 0
    verdict = "✅ Outperformed" if excess > 0 else "❌ Underperformed"
    verdict_color = "#4ade80" if excess > 0 else "#f87171"

    best_params = ""
    if sensitivity and sensitivity.get("best"):
        b = sensitivity["best"]
        best_params = (
            f"<div class='best-params'>★ Optimal parameters found: "
            f"<b>Upside ≥ {b['upside_threshold']}%</b> + "
            f"<b>Score ≥ {b['score_threshold']}</b> "
            f"→ Sharpe = <b>{b['sharpe']}</b> "
            f"(your current: Upside ≥ 10% + Score ≥ 55)</div>"
        )

    cards_html = "".join([
        _metric_card("Total Return", f"{m.get('total_return_pct',0):+.1f}%",
                     f"{m.get('benchmark_return_pct',0):+.1f}%",
                     "good" if (m.get('total_return_pct',0) or 0) > 0 else "bad"),
        _metric_card("CAGR", f"{m.get('cagr_pct',0):+.1f}%",
                     f"{m.get('bh_cagr_pct',0):+.1f}%",
                     "good" if (m.get('cagr_pct',0) or 0) > 0 else "bad"),
        _metric_card("Sharpe Ratio", f"{m.get('sharpe_ratio',0):.3f}", "",
                     "good" if (m.get('sharpe_ratio',0) or 0) > 0.5 else ""),
        _metric_card("Max Drawdown", f"{m.get('max_drawdown_pct',0):.1f}%",
                     f"{m.get('bh_max_drawdown_pct',0):.1f}%",
                     "good" if (m.get('max_drawdown_pct',0) or 0) > -20 else "bad"),
        _metric_card("Sortino Ratio", f"{m.get('sortino_ratio',0):.3f}"),
        _metric_card("Calmar Ratio", f"{m.get('calmar_ratio') or '—'}"),
        _metric_card("Win Rate", f"{m.get('win_rate_pct') or '—'}%"),
        _metric_card("Dividends", f"{m.get('dividend_income_mad',0):,.0f} MAD"),
    ])

    period = f"{m.get('start_date','?')} → {m.get('end_date','?')}  ({m.get('period_years','?')} years)"

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>IAM Backtest Report</title>
{plotly_cdn}
<style>
  *, *::before, *::after {{ box-sizing: border-box; margin: 0; padding: 0; }}
  body {{ background: #0f172a; color: #e2e8f0; font-family: 'Segoe UI', system-ui, sans-serif;
         font-size: 14px; line-height: 1.6; padding: 24px; }}
  h1 {{ font-size: 1.8rem; font-weight: 700; color: #f8fafc; }}
  h2 {{ font-size: 1.1rem; font-weight: 600; color: #94a3b8; margin: 28px 0 12px;
         text-transform: uppercase; letter-spacing: .05em; border-bottom: 1px solid #1e293b;
         padding-bottom: 6px; }}
  .header {{ display: flex; align-items: flex-start; gap: 20px; margin-bottom: 28px;
             background: #1e293b; border-radius: 12px; padding: 20px 24px; }}
  .header-meta {{ flex: 1; }}
  .ticker {{ font-size: 2.8rem; font-weight: 800; color: #60a5fa; line-height: 1; }}
  .sub {{ color: #94a3b8; font-size: .85rem; margin-top: 4px; }}
  .verdict {{ font-size: 1.4rem; font-weight: 700; color: {verdict_color}; margin-top: 8px; }}
  .period {{ color: #64748b; font-size: .82rem; }}
  .cards {{ display: grid; grid-template-columns: repeat(auto-fill, minmax(170px, 1fr)); gap: 12px;
            margin-bottom: 28px; }}
  .card {{ background: #1e293b; border-radius: 10px; padding: 14px 16px;
           border: 1px solid #334155; }}
  .card-label {{ font-size: .75rem; color: #64748b; text-transform: uppercase;
                 letter-spacing: .06em; margin-bottom: 4px; }}
  .card-value {{ font-size: 1.35rem; font-weight: 700; }}
  .bh {{ font-size: .75rem; color: #64748b; margin-top: 2px; display: block; }}
  .chart-box {{ background: #1e293b; border-radius: 12px; padding: 16px; margin-bottom: 20px;
                border: 1px solid #334155; }}
  table {{ width: 100%; border-collapse: collapse; font-size: .82rem; }}
  th {{ background: #1e293b; color: #94a3b8; padding: 8px 10px; text-align: left;
        font-weight: 600; text-transform: uppercase; letter-spacing: .05em; }}
  td {{ padding: 8px 10px; border-bottom: 1px solid #1e293b; }}
  tr:hover td {{ background: #1e293b55; }}
  .best-params {{ background: #1c3a5e; border: 1px solid #3b82f6; border-radius: 8px;
                  padding: 12px 16px; margin: 20px 0; color: #93c5fd; font-size: .9rem; }}
  .footer {{ margin-top: 40px; color: #475569; font-size: .75rem; text-align: center; }}
</style>
</head>
<body>

<div class="header">
  <div class="header-meta">
    <div class="ticker">IAM</div>
    <div class="sub">Itissalat Al-Maghrib (Maroc Telecom) · Casablanca Stock Exchange · MAD</div>
    <div class="verdict">{verdict} Buy & Hold by {abs(excess):.1f}%</div>
    <div class="period">Backtest period: {period}</div>
  </div>
  <div style="text-align:right">
    <div style="font-size:.85rem;color:#64748b">Capital</div>
    <div style="font-size:1.4rem;font-weight:700;color:#e2e8f0">{m.get('initial_capital_mad',0):,.0f} MAD</div>
    <div style="font-size:.85rem;color:#64748b;margin-top:8px">Final Value</div>
    <div style="font-size:1.4rem;font-weight:700;color:#4ade80">{m.get('final_value_mad',0):,.0f} MAD</div>
  </div>
</div>

<h2>📊 Performance Metrics</h2>
<div class="cards">{cards_html}</div>

<div class="chart-box">{equity_chart}</div>
<div class="chart-box">{drawdown_chart}</div>
<div class="chart-box">{factor_chart}</div>

<h2>📋 Annual Signals & Trade Log</h2>
<div class="chart-box">{signal_table}</div>

{'<h2>🔬 Parameter Sensitivity</h2><div class="chart-box">' + heatmap_chart + '</div>' + best_params if heatmap_chart else ''}

<div class="footer">
  Generated by IAM Backtest Engine · Parameters: Commission 0.3% · Risk-Free 3.5% (Bank Al-Maghrib)
</div>
</body>
</html>"""
