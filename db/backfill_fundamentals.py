"""Backfill md.fundamentals from ATW_merged.json.

Run once. Subsequent rows come from core/data_merger.py (weekly).
Scalars extracted to columns; every hist_* dict + any other non-scalar
lives in hist_json (JSONB).

    python db/backfill_fundamentals.py [SYMBOL]
"""
import json
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_ROOT))

from db.writer import upsert_fundamentals


SCALAR_COLS = {
    "price", "market_cap", "pe_ratio", "price_to_book",
    "dividend_yield", "target_price", "consensus",
    "num_analysts", "high_52w", "low_52w",
}


def backfill(symbol: str = "ATW") -> int:
    path = _ROOT / "data" / "historical" / f"{symbol}_merged.json"
    if not path.exists():
        print(f"[!] {path} not found")
        return 0

    with open(path, "r", encoding="utf-8") as f:
        flat = json.load(f)

    scrape_ts = flat.get("scrape_timestamp")
    if not scrape_ts:
        print("[!] missing scrape_timestamp in merged JSON")
        return 0

    hist_json = {k: v for k, v in flat.items() if k not in SCALAR_COLS and k != "scrape_timestamp"}

    row = {
        "scrape_ts": scrape_ts,
        "price": flat.get("price"),
        "market_cap": flat.get("market_cap"),
        "pe_ratio": flat.get("pe_ratio"),
        "price_to_book": flat.get("price_to_book"),
        "dividend_yield": flat.get("dividend_yield"),
        "target_price": flat.get("target_price"),
        "consensus": flat.get("consensus"),
        "num_analysts": flat.get("num_analysts"),
        "high_52w": flat.get("high_52w"),
        "low_52w": flat.get("low_52w"),
        "hist_json": hist_json,
    }

    n = upsert_fundamentals(symbol, row)
    print(f"[OK] {symbol}: wrote {n} row to md.fundamentals (scrape_ts={scrape_ts})")
    return n


if __name__ == "__main__":
    sym = sys.argv[1] if len(sys.argv) > 1 else "ATW"
    backfill(sym)
