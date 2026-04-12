"""
Backtest Data Loader
====================
Loads historical OHLCV price data from Bourse Casa CSV files
and returns a clean, sorted pandas DataFrame.
"""

import pandas as pd
from pathlib import Path


# ─── paths ────────────────────────────────────────────────────────────────────
_ROOT = Path(__file__).resolve().parent.parent
_DATA_DIR = _ROOT / "data" / "historical"


# ─── main loader ──────────────────────────────────────────────────────────────

def load_price_data(symbol: str = "IAM") -> pd.DataFrame:
    """Load daily OHLCV data from Bourse Casa CSV.

    Returns
    -------
    pd.DataFrame with columns:
        date       : pd.Timestamp (index)
        open       : float
        high       : float
        low        : float
        close      : float
        volume     : float
    Sorted ascending by date, duplicates removed.
    """
    csv_path = _DATA_DIR / f"{symbol}_bourse_casa_full.csv"
    if not csv_path.exists():
        raise FileNotFoundError(f"No CSV found: {csv_path}")

    raw = pd.read_csv(csv_path, encoding="utf-8-sig")
    raw.columns = [c.strip().lower() for c in raw.columns]

    # Map Bourse Casa column names
    col_map = {}
    for c in raw.columns:
        if c in ("séance", "seance", "date"):
            col_map[c] = "date"
        elif c in ("dernier cours", "close", "courscourant"):
            col_map[c] = "close"
        elif c in ("cours d'ouverture", "open", "coursouverture"):
            col_map[c] = "open"
        elif c in ("+haut du jour", "high", "highprice"):
            col_map[c] = "high"
        elif c in ("+bas du jour", "low", "lowprice"):
            col_map[c] = "low"
        elif c in ("nombre de titres échangés", "volume", "cumultitresechanges"):
            col_map[c] = "volume"
    raw = raw.rename(columns=col_map)

    df = pd.DataFrame()
    df["date"] = pd.to_datetime(raw["date"], errors="coerce")
    for col in ("open", "high", "low", "close", "volume"):
        if col in raw.columns:
            df[col] = pd.to_numeric(raw[col], errors="coerce")
        else:
            df[col] = float("nan")

    df = df.dropna(subset=["date", "close"])
    df = df.drop_duplicates(subset=["date"])
    df = df.sort_values("date").reset_index(drop=True)
    df = df.set_index("date")

    # Rename to match backtest expectations (capitalized)
    df.columns = [c.capitalize() for c in df.columns]

    print(f"[DataLoader] Loaded {len(df):,} trading days "
          f"({df.index[0].date()} -> {df.index[-1].date()})")
    return df


def get_price_on_or_after(df: pd.DataFrame, target_date: pd.Timestamp) -> tuple:
    """Return (date, price) of the first trading day on or after target_date."""
    future = df.loc[df.index >= target_date]
    if future.empty:
        return None, None
    row = future.iloc[0]
    return future.index[0], float(row["Open"] if not pd.isna(row["Open"]) else row["Close"])


def get_price_on_or_before(df: pd.DataFrame, target_date: pd.Timestamp) -> tuple:
    """Return (date, price) of the last trading day on or before target_date."""
    past = df.loc[df.index <= target_date]
    if past.empty:
        return None, None
    row = past.iloc[-1]
    return past.index[-1], float(row["Close"])
