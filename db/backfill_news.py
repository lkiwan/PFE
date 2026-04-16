"""Backfill md.news_articles from ATW_news.csv.

Run once. Subsequent incremental rows come from atw_news_scraper.py.

    python db/backfill_news.py [SYMBOL]
"""
import sys
from pathlib import Path

import pandas as pd

_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_ROOT))

from db.writer import upsert_news


def backfill(symbol: str = "ATW") -> int:
    csv_path = _ROOT / "data" / "historical" / f"{symbol}_news.csv"
    if not csv_path.exists():
        print(f"[!] {csv_path} not found")
        return 0

    df = pd.read_csv(csv_path)
    df = df.rename(columns={"date": "publish_date"})

    df["publish_date"] = pd.to_datetime(df["publish_date"], errors="coerce", utc=True)
    df["publish_date"] = df["publish_date"].astype(object).where(df["publish_date"].notna(), None)
    df["is_atw_core"] = df["is_atw_core"].fillna(0).astype(int).astype(bool)
    df["signal_score"] = pd.to_numeric(df["signal_score"], errors="coerce").fillna(0).astype(int)

    df = df.dropna(subset=["url", "title"])
    df = df.drop_duplicates(subset=["url"])

    cols = ["publish_date", "title", "source", "url",
            "full_content", "query_source", "signal_score", "is_atw_core"]
    df = df[[c for c in cols if c in df.columns]]
    rows = df.where(df.notna(), None).to_dict(orient="records")

    n = upsert_news(symbol, rows)
    print(f"[OK] {symbol}: wrote {n} rows to md.news_articles")
    return n


if __name__ == "__main__":
    sym = sys.argv[1] if len(sys.argv) > 1 else "ATW"
    backfill(sym)
