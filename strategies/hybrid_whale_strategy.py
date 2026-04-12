"""
Hybrid Technical-Fundamental Strategy — IAM
=============================================

CONCEPT: "Smart Money + Strong Company"
────────────────────────────────────────
Volume spikes (Whales) tell us WHEN to buy.
Fundamental data (from V3 merged data) tells us WHAT to buy.

We combine them:
  1. Calculate the fundamental "Composite Score" (Value, Quality, Growth, Safety, Dividend)
     for the company based on its latest annual results.
  2. Detect daily volume spikes (Whale activity).
  3. We ONLY buy if:
       (A) A Whale is buying (volume spike + price going up)
            AND
       (B) The company is fundamentally strong (Composite Score ≥ 55)

If a whale buys a weak company (Score < 55), we ignore the signal (maybe they are just covering a short, or gambling).
"""

from __future__ import annotations
import pandas as pd
from typing import Optional, Dict, Any, List
import sys
from pathlib import Path
_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_ROOT))

from strategies.whale_strategy import WhaleStrategy, WhaleParams
from backtest.signal_generator import SignalGenerator


class HybridWhaleStrategy(WhaleStrategy):
    """
    Subclasses the pure WhaleStrategy to add a fundamental filter.
    Only allows BUY signals if the most recent fundamental composite score
    is above a threshold.
    """

    def __init__(self, params: Optional[WhaleParams] = None, min_composite_score: float = 50.0):
        super().__init__(params)
        self.min_composite_score = min_composite_score
        
        # Load fundamental signals (these are calculated annually, usually in Feb)
        self.fundamental_generator = SignalGenerator()

    def generate_signals(self, df: pd.DataFrame) -> pd.DataFrame:
        """
        1. Run the pure Whale strategy to get technical signals.
        2. Run the fundamental generator to get annual scores.
        3. Drop any BUY signals where the prior annual score was too low.
        """
        # Get base technical signals
        out = super().generate_signals(df)
        
        print("\n  [Hybrid] Running fundamental scoring to filter whale signals...")
        
        # Determine which fiscal years we need based on the price data provided
        min_year = df.index.min().year
        max_year = df.index.max().year
        # We need data starting a bit earlier since signals apply forward
        fy_list = list(range(min_year - 1, max_year + 1))
        
        # Generate the annual fundamental signals
        annual_signals = self.fundamental_generator.generate_all_signals(df, fiscal_years=fy_list)
        
        # Build a timeline of fundamental scores
        # We map dates to the *latest available* composite score
        out["fundamental_score"] = 0.0
        
        if annual_signals:
            # Sort annual signals by execution date
            annual_signals.sort(key=lambda s: s["execution_date"])
            
            for i, ann_sig in enumerate(annual_signals):
                start_date = ann_sig["execution_date"]
                end_date = annual_signals[i+1]["execution_date"] if i + 1 < len(annual_signals) else out.index.max()
                
                # Apply this score forward until the next annual report
                mask = (out.index >= start_date) & (out.index < end_date)
                out.loc[mask, "fundamental_score"] = ann_sig["composite_score"]

        # Now filter the technical signals
        filtered_signals = []
        for date, row in out.iterrows():
            sig = row["signal"]
            reason = row["reason"]
            score = row["fundamental_score"]
            
            if sig == "BUY":
                if score >= self.min_composite_score:
                    reason += f"  (+ Fundamentally Strong: Score {score:.1f})"
                else:
                    sig = "HOLD"
                    reason = f"🛑 Skipped Whale BUY: Fundamentally Weak (Score {score:.1f} < {self.min_composite_score})"
                    
            filtered_signals.append({
                "signal": sig,
                "reason": reason,
                "fundamental_score": score
            })

        out["signal"] = [s["signal"] for s in filtered_signals]
        out["reason"] = [s["reason"] for s in filtered_signals]
        
        return out
