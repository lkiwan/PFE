"""Backfill md.historical_prices from ATW_bourse_casa_full.csv.

Run once. After this, daily rows come from atw_realtime_scraper.py finalize.

    python db/backfill_history.py [SYMBOL]
"""
import sys
from pathlib import Path

import pandas as pd

_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_ROOT))

from db.writer import upsert_prices


COL_MAP = {
    "Séance": "trade_date",
    "Ouverture": "open",
    "Dernier Cours": "close",
    "+haut du jour": "high",
    "+bas du jour": "low",
    "Nombre de titres échangés": "shares_traded",
    "Volume des échanges": "value_traded_mad",
    "Nombre de transactions": "num_trades",
    "Capitalisation": "market_cap",
}


def backfill(symbol: str = "ATW") -> int:
    csv_path = _ROOT / "data" / "historical" / f"{symbol}_bourse_casa_full.csv"
    if not csv_path.exists():
        print(f"[!] {csv_path} not found")
        return 0

    df = pd.read_csv(csv_path, encoding="utf-8-sig")
    df = df.rename(columns=COL_MAP)

    keep = list(COL_MAP.values())
    df = df[[c for c in keep if c in df.columns]]
    df["trade_date"] = pd.to_datetime(df["trade_date"], errors="coerce").dt.date
    df = df.dropna(subset=["trade_date"])

    for col in ("open", "close", "high", "low", "shares_traded",
                "value_traded_mad", "num_trades", "market_cap"):
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")

    df["source"] = "bourse_casa"

    rows = df.where(df.notna(), None).to_dict(orient="records")
    n = upsert_prices(symbol, rows)
    print(f"[OK] {symbol}: wrote {n} rows to md.historical_prices")
    return n


if __name__ == "__main__":
    sym = sys.argv[1] if len(sys.argv) > 1 else "ATW"
    backfill(sym)
