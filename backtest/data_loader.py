"""
Backtest Data Loader
====================
Loads IAM historical OHLCV price data from the two CSV files
and returns a clean, sorted pandas DataFrame.

Handles:
- BOM (\\ufeff) in the CSV encoding
- French number format: "92,15" → 92.15
- Volume format: "2,01M" → 2_010_000, "164,31K" → 164_310
- Merges P.1 and P.2 files, deduplicates, sorts ascending by date
"""

import re
import os
import pandas as pd
from pathlib import Path


# ─── paths ────────────────────────────────────────────────────────────────────
_ROOT = Path(__file__).resolve().parent.parent
_IAM_DIR = _ROOT / "IAM"
_CSV_P1 = _IAM_DIR / "IAM - Données Historiques dayli P.1.csv"
_CSV_P2 = _IAM_DIR / "IAM - Données Historiques dayli P.2.csv"


# ─── helpers ──────────────────────────────────────────────────────────────────

def _parse_french_number(s: str) -> float:
    """Convert French-formatted number string to float.

    Examples:
        "92,15"   → 92.15
        "1 234,56" → 1234.56
        ""        → NaN
    """
    if not isinstance(s, str):
        return float("nan")
    s = s.strip().replace("\u202f", "").replace("\xa0", "").replace(" ", "")
    if not s or s in ("-", "—", "N/A"):
        return float("nan")
    s = s.replace(",", ".")
    # If more than one dot, only the last is decimal
    parts = s.split(".")
    if len(parts) > 2:
        s = "".join(parts[:-1]) + "." + parts[-1]
    try:
        return float(s)
    except ValueError:
        return float("nan")


def _parse_volume(s: str) -> float:
    """Convert volume strings like '2,01M' or '164,31K' to a float.

    Examples:
        "2,01M"   → 2_010_000
        "164,31K" → 164_310
        "26"      → 26
    """
    if not isinstance(s, str):
        return float("nan")
    s = s.strip()
    if not s or s in ("-", "—"):
        return float("nan")
    multiplier = 1.0
    if s.endswith("M"):
        multiplier = 1_000_000
        s = s[:-1]
    elif s.endswith("K"):
        multiplier = 1_000
        s = s[:-1]
    return _parse_french_number(s) * multiplier


def _parse_pct(s: str) -> float:
    """Convert '0,75%' → 0.75 (as a percentage value, not a ratio)."""
    if not isinstance(s, str):
        return float("nan")
    s = s.strip().rstrip("%")
    return _parse_french_number(s)


def _parse_date(s: str) -> pd.Timestamp:
    """Parse DD/MM/YYYY date strings."""
    try:
        return pd.to_datetime(s.strip(), format="%d/%m/%Y")
    except Exception:
        return pd.NaT


# ─── main loader ──────────────────────────────────────────────────────────────

def _load_single_csv(path: Path) -> pd.DataFrame:
    """Load one CSV file and return a raw DataFrame with stripped columns."""
    raw = pd.read_csv(path, encoding="utf-8-sig", dtype=str)
    raw.columns = [c.strip() for c in raw.columns]
    return raw


def load_price_data() -> pd.DataFrame:
    """Load, merge, clean and return IAM daily price data.

    Returns
    -------
    pd.DataFrame with columns:
        date       : pd.Timestamp (index)
        open       : float  — opening price (MAD)
        high       : float  — daily high (MAD)
        low        : float  — daily low (MAD)
        close      : float  — closing price / 'Dernier' (MAD)
        volume     : float  — traded volume (shares)
        change_pct : float  — daily % change
    Sorted ascending by date, duplicates removed.
    """
    frames = []
    for path in [_CSV_P1, _CSV_P2]:
        if not path.exists():
            print(f"[WARN] CSV not found: {path}")
            continue
        frames.append(_load_single_csv(path))

    if not frames:
        raise FileNotFoundError(
            f"No IAM CSV files found in {_IAM_DIR}. "
            "Expected 'IAM - Données Historiques dayli P.1.csv' and P.2."
        )

    raw = pd.concat(frames, ignore_index=True)

    # ── column mapping ───────────────────────────────────────────────────────
    # Columns: Date, Dernier, Ouv., Plus Haut, Plus Bas, Vol., Variation %
    col_map = {}
    for c in raw.columns:
        lc = c.lower()
        if "date" in lc:
            col_map[c] = "date_raw"
        elif "dernier" in lc:
            col_map[c] = "close_raw"
        elif "ouv" in lc:
            col_map[c] = "open_raw"
        elif "haut" in lc:
            col_map[c] = "high_raw"
        elif "bas" in lc:
            col_map[c] = "low_raw"
        elif "vol" in lc:
            col_map[c] = "volume_raw"
        elif "vari" in lc:
            col_map[c] = "change_raw"
    raw = raw.rename(columns=col_map)

    # ── parse ────────────────────────────────────────────────────────────────
    df = pd.DataFrame()
    df["date"]       = raw["date_raw"].apply(_parse_date)
    df["close"]      = raw["close_raw"].apply(_parse_french_number)
    df["open"]       = raw["open_raw"].apply(_parse_french_number) if "open_raw" in raw else df["close"]
    df["high"]       = raw["high_raw"].apply(_parse_french_number)  if "high_raw" in raw else df["close"]
    df["low"]        = raw["low_raw"].apply(_parse_french_number)   if "low_raw" in raw else df["close"]
    df["volume"]     = raw["volume_raw"].apply(_parse_volume)       if "volume_raw" in raw else float("nan")
    df["change_pct"] = raw["change_raw"].apply(_parse_pct)          if "change_raw" in raw else float("nan")

    # ── clean ────────────────────────────────────────────────────────────────
    df = df.dropna(subset=["date", "close"])
    df = df.drop_duplicates(subset=["date"])
    df = df.sort_values("date").reset_index(drop=True)
    df = df.set_index("date")

    print(f"[DataLoader] Loaded {len(df):,} trading days  "
          f"({df.index[0].date()} → {df.index[-1].date()})")
    return df


def get_price_on_or_after(df: pd.DataFrame, target_date: pd.Timestamp) -> tuple:
    """Return (date, price) of the first trading day on or after target_date."""
    future = df.loc[df.index >= target_date]
    if future.empty:
        return None, None
    row = future.iloc[0]
    return future.index[0], float(row["open"] if not pd.isna(row["open"]) else row["close"])


def get_price_on_or_before(df: pd.DataFrame, target_date: pd.Timestamp) -> tuple:
    """Return (date, price) of the last trading day on or before target_date."""
    past = df.loc[df.index <= target_date]
    if past.empty:
        return None, None
    row = past.iloc[-1]
    return past.index[-1], float(row["close"])
