"""
Backtest Engine
===============
Simulates a paper trading portfolio that follows the signals generated
by SignalGenerator. 

Rules:
- Initial capital: 100,000 MAD (configurable)
- Commission: 0.3% per trade (Casablanca Bourse standard)
- No short selling (CSE rules)
- Fully invested on BUY / STRONG BUY (buy as many whole shares as possible)
- Full exit on SELL / STRONG SELL
- HOLD: keep current position unchanged
- Only one position at a time (single-stock IAM backtest)
- Dividends included (approximate — DPS applied on ex-dividend date)
"""

from __future__ import annotations
from dataclasses import dataclass, field
from typing import List, Dict, Any, Optional, Tuple
import pandas as pd
import numpy as np


# ─── config ───────────────────────────────────────────────────────────────────
DEFAULT_INITIAL_CAPITAL = 100_000.0   # MAD
COMMISSION_RATE = 0.003               # 0.3% per trade (Casablanca Bourse)
IAM_DPS_HISTORY = {                   # Dividend per share (MAD), approximate ex-dates
    2021: (4.00,  pd.Timestamp("2021-06-01")),
    2022: (2.19,  pd.Timestamp("2022-06-01")),
    2023: (4.20,  pd.Timestamp("2023-06-01")),
    2024: (1.43,  pd.Timestamp("2024-06-01")),
    2025: (4.183, pd.Timestamp("2025-06-01")),
}

BUY_SIGNALS  = {"BUY", "STRONG BUY"}
SELL_SIGNALS = {"SELL", "STRONG SELL"}


# ─── data classes ─────────────────────────────────────────────────────────────
@dataclass
class Trade:
    date:        pd.Timestamp
    action:      str          # "BUY" | "SELL" | "DIVIDEND"
    shares:      float
    price:       float
    commission:  float
    cash_flow:   float        # negative = cash out, positive = cash in
    portfolio_value_after: float
    fiscal_year: int
    signal:      str
    upside_pct:  float
    score:       float


@dataclass
class PortfolioDay:
    date:            pd.Timestamp
    cash:            float
    shares_held:     float
    price:           float
    portfolio_value: float
    benchmark_value: float    # buy-and-hold value


@dataclass
class BacktestResult:
    trades:         List[Trade]
    equity_curve:   pd.Series    # portfolio value per trading day
    benchmark_curve: pd.Series   # buy-and-hold value per trading day
    signals:        List[Dict]
    initial_capital: float
    final_value:    float
    metrics:        Dict[str, Any] = field(default_factory=dict)


# ─── engine ───────────────────────────────────────────────────────────────────
class BacktestEngine:
    """Paper portfolio simulator for IAM annual-rebalancing strategy."""

    def __init__(
        self,
        price_df: pd.DataFrame,
        signals: List[Dict],
        initial_capital: float = DEFAULT_INITIAL_CAPITAL,
        commission: float = COMMISSION_RATE,
        include_dividends: bool = True,
    ):
        self.price_df         = price_df
        self.signals          = sorted(signals, key=lambda s: s["execution_date"])
        self.initial_capital  = initial_capital
        self.commission       = commission
        self.include_dividends = include_dividends

        # state
        self.cash   = initial_capital
        self.shares = 0.0
        self.trades: List[Trade] = []
        self._portfolio_days: List[PortfolioDay] = []

    # ── public ──────────────────────────────────────────────────────────────

    def run(self) -> BacktestResult:
        """Execute the backtest and return results."""
        print("\n── Portfolio Simulation ──────────────────────────────────────")
        print(f"  Capital: {self.initial_capital:,.0f} MAD | "
              f"Commission: {self.commission*100:.1f}% | "
              f"Signals: {len(self.signals)}")

        # Determine date range
        first_signal_date = self.signals[0]["execution_date"] if self.signals else self.price_df.index[0]
        last_date         = self.price_df.index[-1]
        price_slice       = self.price_df.loc[first_signal_date:last_date]

        # Build a map of signal execution dates  →  signal info
        signal_map = {s["execution_date"]: s for s in self.signals}

        # Build dividend map: date → DPS (only if we hold shares)
        if self.include_dividends:
            div_map = {date: dps for _, (dps, date) in IAM_DPS_HISTORY.items()}
        else:
            div_map = {}

        # Benchmark: buy-and-hold from first signal date
        bench_price_start = float(price_slice.iloc[0]["close"])
        bench_shares = self.initial_capital / bench_price_start

        # Day-by-day simulation
        for date, row in price_slice.iterrows():
            price = float(row["close"])
            if pd.isna(price) or price <= 0:
                continue

            # ── execute signal if today is an execution date ───────────────
            if date in signal_map:
                sig = signal_map[date]
                exec_price = sig["execution_price"]
                self._handle_signal(sig, exec_price, date)

            # ── collect dividends ─────────────────────────────────────────
            if self.include_dividends and self.shares > 0:
                for div_date, dps in div_map.items():
                    # match within a 5-day window (in case of market holiday)
                    if abs((date - div_date).days) <= 5:
                        div_cash = self.shares * dps
                        self.cash += div_cash
                        self.trades.append(Trade(
                            date=date, action="DIVIDEND", shares=self.shares,
                            price=dps, commission=0.0, cash_flow=div_cash,
                            portfolio_value_after=self._portfolio_value(price),
                            fiscal_year=0, signal="DIV", upside_pct=0, score=0,
                        ))

            # ── record daily snapshot ──────────────────────────────────────
            pv = self._portfolio_value(price)
            bv = bench_shares * price
            self._portfolio_days.append(PortfolioDay(
                date=date, cash=self.cash, shares_held=self.shares,
                price=price, portfolio_value=pv, benchmark_value=bv,
            ))

        result = self._build_result()
        self._print_summary(result)
        return result

    # ── private ─────────────────────────────────────────────────────────────

    def _handle_signal(self, sig: dict, exec_price: float, date: pd.Timestamp) -> None:
        action = sig["signal"]
        fy     = sig["fiscal_year"]
        upside = sig["upside_pct"]
        score  = sig["composite_score"]

        if action in BUY_SIGNALS and self.shares == 0:
            self._buy(exec_price, date, fy, action, upside, score)

        elif action in SELL_SIGNALS and self.shares > 0:
            self._sell(exec_price, date, fy, action, upside, score)

        # HOLD: do nothing

    def _buy(self, price: float, date: pd.Timestamp,
             fy: int, signal: str, upside: float, score: float) -> None:
        """Buy as many whole shares as possible from available cash."""
        gross = self.cash / (1 + self.commission)
        shares_to_buy = int(gross / price)
        if shares_to_buy <= 0:
            return
        commission = shares_to_buy * price * self.commission
        cost = shares_to_buy * price + commission
        self.cash  -= cost
        self.shares = shares_to_buy
        pv = self._portfolio_value_at(shares_to_buy, self.cash, price)
        self.trades.append(Trade(
            date=date, action="BUY", shares=shares_to_buy, price=price,
            commission=commission, cash_flow=-cost,
            portfolio_value_after=pv,
            fiscal_year=fy, signal=signal, upside_pct=upside, score=score,
        ))
        print(f"  ✅ BUY  {shares_to_buy:,} shares @ {price:.2f} MAD  "
              f"(commission {commission:.0f} MAD)  — FY{fy}")

    def _sell(self, price: float, date: pd.Timestamp,
              fy: int, signal: str, upside: float, score: float) -> None:
        """Sell all held shares."""
        gross    = self.shares * price
        commission = gross * self.commission
        proceeds = gross - commission
        self.cash  += proceeds
        sold_shares = self.shares
        self.shares = 0.0
        pv = self._portfolio_value_at(0, self.cash, price)
        self.trades.append(Trade(
            date=date, action="SELL", shares=sold_shares, price=price,
            commission=commission, cash_flow=proceeds,
            portfolio_value_after=pv,
            fiscal_year=fy, signal=signal, upside_pct=upside, score=score,
        ))
        print(f"  🔴 SELL {sold_shares:,} shares @ {price:.2f} MAD  "
              f"(commission {commission:.0f} MAD)  — FY{fy}")

    def _portfolio_value(self, price: float) -> float:
        return self.cash + self.shares * price

    @staticmethod
    def _portfolio_value_at(shares: float, cash: float, price: float) -> float:
        return cash + shares * price

    def _build_result(self) -> BacktestResult:
        days = self._portfolio_days
        dates = [d.date for d in days]
        equity    = pd.Series([d.portfolio_value  for d in days], index=dates, name="strategy")
        benchmark = pd.Series([d.benchmark_value  for d in days], index=dates, name="buy_and_hold")
        final_val = equity.iloc[-1] if len(equity) else self.initial_capital
        return BacktestResult(
            trades=self.trades,
            equity_curve=equity,
            benchmark_curve=benchmark,
            signals=self.signals,
            initial_capital=self.initial_capital,
            final_value=final_val,
        )

    def _print_summary(self, r: BacktestResult) -> None:
        buy_trades  = [t for t in r.trades if t.action == "BUY"]
        sell_trades = [t for t in r.trades if t.action == "SELL"]
        tot_return  = (r.final_value / r.initial_capital - 1) * 100
        bh_final    = r.benchmark_curve.iloc[-1] if len(r.benchmark_curve) else r.initial_capital
        bh_return   = (bh_final / r.initial_capital - 1) * 100
        print(f"\n  Final portfolio value : {r.final_value:>12,.2f} MAD")
        print(f"  Buy-and-hold value    : {bh_final:>12,.2f} MAD")
        print(f"  Strategy total return : {tot_return:>+.1f}%")
        print(f"  Buy-and-hold return   : {bh_return:>+.1f}%")
        print(f"  Trades executed       : {len(buy_trades)} BUY, {len(sell_trades)} SELL")
