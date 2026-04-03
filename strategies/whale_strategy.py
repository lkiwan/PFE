"""
Whale Strategy — IAM (Itissalat Al-Maghrib)
=============================================

CONCEPT: "Follow the Smart Money"
──────────────────────────────────
A "whale" is a large institutional investor (pension fund, investment bank,
foreign fund) that trades hundreds of thousands of shares in one go.
When a whale buys or sells, it leaves a visible footprint in the VOLUME data.

The idea is simple:
  → If today's volume is abnormally HIGH compared to normal days,
    a big player is doing something important.
  → If that big volume came with a RISING price   → they are BUYING  (accumulation)
  → If that big volume came with a FALLING price  → they are SELLING (distribution)
  → We follow them.

DATA USED (100% from IAM CSV files — no external data needed)
──────────────────────────────────────────────────────────────
  - close   : closing price each day
  - open    : opening price each day
  - high    : highest intraday price
  - low     : lowest intraday price
  - volume  : number of shares traded

INDICATORS COMPUTED (all derived from the raw CSV)
────────────────────────────────────────────────────
  1. vol_ma20      : 20-day rolling average volume  (= "normal" volume)
  2. vol_ratio     : today's volume ÷ vol_ma20      (how unusual is today?)
  3. price_change  : (close - open) / open × 100   (intraday direction %)
  4. atr14         : Average True Range 14-day      (market volatility)
  5. sma50         : 50-day moving average of price (trend filter)

SIGNAL RULES
────────────────────────────────────────────────────
  BUY  when:
    • vol_ratio  ≥  VOLUME_THRESHOLD  (e.g. 2.5× normal volume)
    • price_change ≥  PRICE_THRESHOLD (e.g. +0.3% — price went up on that big day)
    • close  >  sma50                 (trend filter: don't buy in a downtrend)

  SELL when:
    • vol_ratio  ≥  VOLUME_THRESHOLD
    • price_change ≤ -PRICE_THRESHOLD (price fell on the big-volume day)
    OR
    • stop-loss hit : price fell STOP_LOSS_PCT below buy price
    • take-profit   : price rose TAKE_PROFIT_PCT above buy price

  HOLD: everything else

DEFAULT PARAMETERS (tunable)
────────────────────────────────────────────────────
  VOLUME_THRESHOLD = 2.5   (volume must be 2.5× the 20-day average)
  PRICE_THRESHOLD  = 0.3   (price must move at least 0.3% on signal day)
  SMA_PERIOD       = 50    (trend filter)
  STOP_LOSS_PCT    = 8.0   (exit if position drops 8% from entry)
  TAKE_PROFIT_PCT  = 25.0  (exit if position gains 25% from entry)
  VOLUME_MA_PERIOD = 20    (rolling average window for "normal" volume)
"""

from __future__ import annotations
from dataclasses import dataclass, field
from typing import Optional, Dict, Any
import pandas as pd
import numpy as np


# ─── parameters ───────────────────────────────────────────────────────────────
@dataclass
class WhaleParams:
    volume_threshold:  float = 2.5    # vol must be N× the rolling average
    price_threshold:   float = 0.3    # min intraday move % to confirm direction
    volume_ma_period:  int   = 20     # rolling window for "normal" volume
    sma_period:        int   = 50     # trend filter (price above SMA = uptrend)
    stop_loss_pct:     float = 8.0    # stop-loss % below entry
    take_profit_pct:   float = 25.0   # take-profit % above entry
    min_volume:        float = 20_000 # ignore days with <20k shares (illiquid)


# ─── signal dataclass ─────────────────────────────────────────────────────────
@dataclass
class WhaleSignal:
    date:         pd.Timestamp
    signal:       str           # "BUY" | "SELL" | "HOLD"
    price:        float
    volume:       float
    vol_ratio:    float         # volume / vol_ma20
    price_change: float         # intraday % move
    reason:       str           # human-readable explanation
    indicators:   Dict[str, Any] = field(default_factory=dict)


# ─── strategy ─────────────────────────────────────────────────────────────────
class WhaleStrategy:
    """
    Detects institutional (whale) activity via volume spikes and
    generates BUY/SELL signals based on price direction confirmation.
    """

    def __init__(self, params: Optional[WhaleParams] = None):
        self.params = params or WhaleParams()

    def compute_indicators(self, df: pd.DataFrame) -> pd.DataFrame:
        """
        Add all indicator columns to the price DataFrame.

        Input columns required: close, open, high, low, volume
        Returns the same DataFrame with extra columns added.
        """
        p = self.params
        out = df.copy()

        # ── volume indicators ────────────────────────────────────────────
        out["vol_ma"]    = out["volume"].rolling(p.volume_ma_period, min_periods=5).mean()
        out["vol_ratio"] = out["volume"] / out["vol_ma"]

        # ── price direction on signal day ────────────────────────────────
        # intraday: (close - open) / open * 100
        out["intraday_chg"] = (out["close"] - out["open"]) / out["open"] * 100

        # ── trend filter ─────────────────────────────────────────────────
        out["sma50"] = out["close"].rolling(p.sma_period, min_periods=20).mean()

        # ── volatility (ATR 14) ──────────────────────────────────────────
        high_low   = out["high"] - out["low"]
        high_close = (out["high"] - out["close"].shift(1)).abs()
        low_close  = (out["low"]  - out["close"].shift(1)).abs()
        tr = pd.concat([high_low, high_close, low_close], axis=1).max(axis=1)
        out["atr14"] = tr.rolling(14, min_periods=5).mean()

        # ── volume spike flag ────────────────────────────────────────────
        out["is_whale_day"] = (
            (out["vol_ratio"] >= p.volume_threshold) &
            (out["volume"]    >= p.min_volume)
        )

        return out

    def generate_signals(self, df: pd.DataFrame) -> pd.DataFrame:
        """
        Generate BUY/SELL/HOLD signals for every day.

        Returns a DataFrame with a 'signal' column and all indicators.
        """
        p   = self.params
        out = self.compute_indicators(df)

        signals = []
        position_price = None   # price at which we entered (None = no position)

        for date, row in out.iterrows():
            sig    = "HOLD"
            reason = "Normal day — no whale activity"

            vol_ratio    = row["vol_ratio"]    if pd.notna(row["vol_ratio"])    else 0
            intraday_chg = row["intraday_chg"] if pd.notna(row["intraday_chg"]) else 0
            price        = float(row["close"])
            sma50        = row["sma50"]         if pd.notna(row["sma50"])        else price

            # ── stop-loss / take-profit (if in position) ──────────────
            if position_price is not None:
                change_from_entry = (price - position_price) / position_price * 100
                if change_from_entry <= -p.stop_loss_pct:
                    sig = "SELL"
                    reason = f"🛑 Stop-loss hit ({change_from_entry:.1f}% from entry)"
                    position_price = None
                elif change_from_entry >= p.take_profit_pct:
                    sig = "SELL"
                    reason = f"🎯 Take-profit hit (+{change_from_entry:.1f}% from entry)"
                    position_price = None

            # ── whale signal detection ────────────────────────────────
            if sig == "HOLD" and row["is_whale_day"]:
                if intraday_chg >= p.price_threshold and price > sma50:
                    # Whale is buying AND price is in uptrend
                    if position_price is None:   # only buy if not already in position
                        sig = "BUY"
                        reason = (
                            f"🐋 Whale ACCUMULATION detected: "
                            f"volume {vol_ratio:.1f}× normal, "
                            f"price +{intraday_chg:.1f}% intraday, "
                            f"above 50-SMA (uptrend)"
                        )
                        position_price = price

                elif intraday_chg <= -p.price_threshold:
                    # Whale is selling
                    if position_price is not None:  # only sell if we hold
                        sig = "SELL"
                        reason = (
                            f"🐋 Whale DISTRIBUTION detected: "
                            f"volume {vol_ratio:.1f}× normal, "
                            f"price {intraday_chg:.1f}% intraday"
                        )
                        position_price = None

            signals.append({
                "date":         date,
                "signal":       sig,
                "close":        price,
                "volume":       float(row["volume"]),
                "vol_ratio":    round(vol_ratio, 2),
                "intraday_chg": round(intraday_chg, 2),
                "vol_ma":       round(float(row["vol_ma"]), 0) if pd.notna(row["vol_ma"]) else None,
                "sma50":        round(sma50, 2),
                "atr14":        round(float(row["atr14"]), 2) if pd.notna(row["atr14"]) else None,
                "is_whale_day": bool(row["is_whale_day"]),
                "reason":       reason,
            })

        result = pd.DataFrame(signals).set_index("date")
        return result

    def filter_actionable(self, signals_df: pd.DataFrame) -> pd.DataFrame:
        """Return only BUY and SELL signals (not HOLD)."""
        return signals_df[signals_df["signal"].isin(["BUY", "SELL"])].copy()

    def summary_stats(self, signals_df: pd.DataFrame) -> Dict[str, Any]:
        """Print a summary of signal statistics."""
        whale_days = signals_df[signals_df["is_whale_day"]]
        buy_signals  = signals_df[signals_df["signal"] == "BUY"]
        sell_signals = signals_df[signals_df["signal"] == "SELL"]
        return {
            "total_days":       len(signals_df),
            "whale_days":       len(whale_days),
            "whale_day_pct":    round(len(whale_days) / len(signals_df) * 100, 1),
            "buy_signals":      len(buy_signals),
            "sell_signals":     len(sell_signals),
            "avg_vol_ratio_on_whale_days": round(whale_days["vol_ratio"].mean(), 2),
            "max_vol_ratio":    round(signals_df["vol_ratio"].max(), 2),
        }
