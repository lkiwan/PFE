"""Backfill md.macro_morocco from ATW_macro_morocco.csv.

Run once. Subsequent rows come from atw_macro_collector.py.

    python db/backfill_macro.py
"""
import sys
from pathlib import Path

import pandas as pd

_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_ROOT))

from db.writer import upsert_macro

BATCH = 1000


def backfill() -> int:
    csv_path = _ROOT / "data" / "historical" / "ATW_macro_morocco.csv"
    if not csv_path.exists():
        print(f"[!] {csv_path} not found")
        return 0

    df = pd.read_csv(csv_path)
    df["date"] = pd.to_datetime(df["date"], errors="coerce").dt.date
    df = df.dropna(subset=["date"])

    numeric_cols = [c for c in df.columns if c not in ("date", "frequency_tag")]
    for c in numeric_cols:
        df[c] = pd.to_numeric(df[c], errors="coerce")

    rows = df.where(df.notna(), None).to_dict(orient="records")

    total = 0
    for i in range(0, len(rows), BATCH):
        chunk = rows[i:i + BATCH]
        total += upsert_macro(chunk)
        print(f"  ... {total}/{len(rows)}")
    print(f"[OK] wrote {total} rows to md.macro_morocco")
    return total


if __name__ == "__main__":
    backfill()
