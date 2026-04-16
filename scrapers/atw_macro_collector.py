"""
ATW macroeconomic and market-context collector.

Builds a daily macro dataset for ATW (Attijariwafa Bank) by combining:
- FRED series (fredapi, requires FRED_API_KEY in environment)
- World Bank indicators (REST API)
- IMF DataMapper indicators (REST API)
- yfinance daily market series

Output:
    data/historical/ATW_macro_morocco.csv
"""

from __future__ import annotations

import argparse
import logging
import os
import re
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import requests
import certifi

try:
    import yfinance as yf
except ImportError as exc:
    raise RuntimeError("Missing dependency: yfinance. Install with `pip install yfinance`.") from exc

try:
    from dotenv import load_dotenv
except ImportError:
    load_dotenv = None

import sys
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from db.writer import upsert_macro


logger = logging.getLogger("atw_macro_collector")


def _upsert_macro_df(df: pd.DataFrame) -> None:
    """Mirror macro CSV rows to md.macro_morocco. Fail-open."""
    if df.empty:
        return
    macro_cols = [
        "frequency_tag", "bank_roe", "gdp_growth_pct",
        "external_debt_pct_gdp", "current_account_pct_gdp",
        "public_debt_pct_gdp", "gdp_per_capita_usd",
        "inflation_cpi_pct", "residential_property_idx",
        "gdp_ci", "gdp_sn", "gdp_cm", "gdp_tn",
    ]
    dfc = df.copy()
    for c in macro_cols:
        if c not in dfc.columns:
            dfc[c] = None
    dfc["date"] = pd.to_datetime(dfc["date"], errors="coerce").dt.date
    dfc = dfc.dropna(subset=["date"])
    rows = dfc[["date"] + macro_cols].where(dfc.notna(), None).to_dict(orient="records")
    BATCH = 1000
    total = 0
    for i in range(0, len(rows), BATCH):
        total += upsert_macro(rows[i:i + BATCH])
    logger.info("DB: wrote %d rows to md.macro_morocco", total)

_ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = _ROOT / "data" / "historical"
DEFAULT_OUTPUT = DATA_DIR / "ATW_macro_morocco.csv"
FRED_OBSERVATION_START = "2010-01-01"

if load_dotenv is not None:
    load_dotenv(_ROOT / ".env")

# Force valid CA bundle (Windows env may point to broken PostgreSQL cert path).
os.environ["REQUESTS_CA_BUNDLE"] = certifi.where()
os.environ["CURL_CA_BUNDLE"] = certifi.where()
os.environ["SSL_CERT_FILE"] = certifi.where()


OUTPUT_COLUMNS = [
    "date",
    "frequency_tag",
    "bam_policy_rate",
    "interbank_rate",
    "money_supply_m1",
    "bank_roe",
    "gdp_volume_idx",
    "gdp_growth_pct",
    "external_debt_pct_gdp",
    "current_account_pct_gdp",
    "public_debt_pct_gdp",
    "gdp_per_capita_usd",
    "inflation_cpi_pct",
    "residential_property_idx",
    "unemployment_pct",
    "eur_mad",
    "usd_mad",
    "brent_usd",
    "wheat_usd",
    "gold_usd",
    "vix",
    "sp500_close",
    "eem_close",
    "us10y_yield",
    "masi_close",
    "madex_close",
    "gdp_ci",
    "gdp_sn",
    "gdp_cm",
    "gdp_tn",
    "real_rate",
    "macro_momentum",
    "fx_pressure_eur",
    "property_credit_risk",
    "global_risk_flag",
]


PHASE1_COLUMNS = [
    "bam_policy_rate",
    "inflation_cpi_pct",
    "eur_mad",
    "usd_mad",
    "brent_usd",
    "vix",
    "eem_close",
    "residential_property_idx",
]


@dataclass(frozen=True)
class FredSpec:
    output_col: str
    series_id: str


FRED_SPECS = [
    FredSpec("bam_policy_rate", "INTDSRMAM193N"),
    FredSpec("interbank_rate", "IRSTCI01MAM156N"),
    FredSpec("money_supply_m1", "MANMM101MAM189S"),
    FredSpec("bank_roe", "DDEI06MAA156NWDB"),
    FredSpec("gdp_volume_idx", "NGDPRMAMISMEI"),
    FredSpec("external_debt_pct_gdp", "MARDGDPGDPPT"),
    FredSpec("gdp_per_capita_usd", "PCAGDPMAA646NWDB"),
    FredSpec("inflation_cpi_pct_fred", "FPCPITOTLZGMAR"),
    FredSpec("residential_property_idx", "QMAR628BIS"),
    FredSpec("unemployment_pct_fred", "SLUEM15TTTMAM"),
]


WORLD_BANK_MA = {
    "gdp_growth_pct": "NY.GDP.MKTP.KD.ZG",
    "current_account_pct_gdp": "BN.CAB.XOKA.GD.ZS",
    "public_debt_pct_gdp": "GC.DOD.TOTL.GD.ZS",
    "inflation_cpi_pct_wb": "FP.CPI.TOTL.ZG",
    "unemployment_pct_wb": "SL.UEM.TOTL.ZG",
}


WORLD_BANK_REGIONAL = {
    "gdp_ci": ("CI", "NY.GDP.MKTP.KD.ZG"),
    "gdp_sn": ("SN", "NY.GDP.MKTP.KD.ZG"),
    "gdp_cm": ("CM", "NY.GDP.MKTP.KD.ZG"),
    "gdp_tn": ("TN", "NY.GDP.MKTP.KD.ZG"),
}


YF_CANDIDATES = {
    "eur_mad": ["EURMAD=X"],
    "usd_mad": ["USDMAD=X"],
    "brent_usd": ["BZ=F"],
    "wheat_usd": ["WEAT"],
    "gold_usd": ["GC=F"],
    "vix": ["^VIX"],
    "sp500_close": ["^GSPC"],
    "eem_close": ["EEM"],
    "us10y_yield": ["^TNX"],
    "masi_close": ["^MASI", "MASI.CS", "MASI"],
    "madex_close": ["^MADEX", "MADEX.CS", "MADEX"],
}


def _to_datetime_index(series: pd.Series) -> pd.Series:
    if series is None or series.empty:
        return pd.Series(dtype=float)
    s = series.copy()
    s.index = pd.to_datetime(s.index, errors="coerce")
    s = s[~s.index.isna()]
    s = s[~s.index.duplicated(keep="last")]
    s = s.sort_index()
    return pd.to_numeric(s, errors="coerce")


def _parse_year_or_date(value: Any) -> pd.Timestamp | None:
    if value is None:
        return None
    text = str(value).strip()
    if re.fullmatch(r"\d{4}", text):
        return pd.Timestamp(f"{text}-12-31")
    dt = pd.to_datetime(text, errors="coerce")
    if pd.isna(dt):
        return None
    return pd.Timestamp(dt)


def _fred_client() -> Any:
    api_key = os.getenv("FRED_API_KEY")
    if not api_key:
        raise RuntimeError("FRED_API_KEY is missing in environment (.env).")
    try:
        from fredapi import Fred
    except ImportError as exc:
        raise RuntimeError("Missing dependency: fredapi. Install with `pip install fredapi`.") from exc
    return Fred(api_key=api_key)


def fetch_fred_series(series_id: str, start: str = FRED_OBSERVATION_START) -> pd.Series:
    fred = _fred_client()
    s = fred.get_series(series_id, observation_start=start)
    return _to_datetime_index(pd.Series(s))


def fetch_world_bank_indicator(country_iso2: str, indicator: str, mrv: int = 20) -> pd.Series:
    url = f"https://api.worldbank.org/v2/country/{country_iso2}/indicator/{indicator}"
    resp = requests.get(url, params={"format": "json", "mrv": mrv}, timeout=30)
    resp.raise_for_status()
    payload = resp.json()
    if not isinstance(payload, list) or len(payload) < 2:
        raise ValueError(f"Unexpected World Bank payload for {country_iso2}:{indicator}")
    rows = payload[1] or []
    values: dict[pd.Timestamp, float] = {}
    for row in rows:
        dt = _parse_year_or_date(row.get("date"))
        val = row.get("value")
        if dt is None or val is None:
            continue
        values[dt] = float(val)
    return _to_datetime_index(pd.Series(values))


def _extract_year_map(node: Any) -> dict[str, Any] | None:
    if isinstance(node, dict):
        keys = list(node.keys())
        if keys and all(re.fullmatch(r"\d{4}", str(k)) for k in keys):
            return node
        for val in node.values():
            found = _extract_year_map(val)
            if found is not None:
                return found
    elif isinstance(node, list):
        for item in node:
            found = _extract_year_map(item)
            if found is not None:
                return found
    return None


def fetch_imf_datamapper_series(indicator: str, country_iso3: str = "MAR") -> pd.Series:
    url = f"https://www.imf.org/external/datamapper/api/v1/{indicator}/{country_iso3}"
    resp = requests.get(url, timeout=30)
    resp.raise_for_status()
    payload = resp.json()
    year_map = _extract_year_map(payload)
    if not year_map:
        raise ValueError(f"Unexpected IMF payload for {indicator}/{country_iso3}")
    values: dict[pd.Timestamp, float] = {}
    for y, v in year_map.items():
        dt = _parse_year_or_date(y)
        if dt is None or v is None:
            continue
        values[dt] = float(v)
    return _to_datetime_index(pd.Series(values))


def fetch_yf_close(ticker: str, period: str = "10y", interval: str = "1d") -> pd.Series:
    df = yf.download(
        tickers=ticker,
        period=period,
        interval=interval,
        auto_adjust=False,
        progress=False,
        threads=False,
    )
    if df is None or df.empty:
        return pd.Series(dtype=float)
    if isinstance(df.columns, pd.MultiIndex):
        if "Close" not in df.columns.get_level_values(0):
            return pd.Series(dtype=float)
        close = df["Close"].iloc[:, 0]
    else:
        if "Close" not in df.columns:
            return pd.Series(dtype=float)
        close = df["Close"]
    close.index = pd.to_datetime(close.index, errors="coerce").tz_localize(None)
    return _to_datetime_index(close)


def fetch_first_available_yf(candidates: list[str]) -> tuple[pd.Series, str | None]:
    for ticker in candidates:
        try:
            s = fetch_yf_close(ticker)
        except (requests.RequestException, OSError, ValueError) as exc:
            logger.warning("yfinance %s failed: %s", ticker, exc)
            continue
        if not s.empty:
            return s, ticker
    return pd.Series(dtype=float), None


def collect_series() -> dict[str, pd.Series]:
    series_map: dict[str, pd.Series] = {}

    # FRED
    for spec in FRED_SPECS:
        try:
            series_map[spec.output_col] = fetch_fred_series(spec.series_id)
            logger.info("FRED %s -> %s (%d pts)", spec.series_id, spec.output_col, len(series_map[spec.output_col]))
        except (requests.RequestException, RuntimeError, ValueError) as exc:
            logger.warning("FRED %s failed: %s", spec.series_id, exc)
            series_map[spec.output_col] = pd.Series(dtype=float)

    # World Bank (Morocco)
    for output_col, indicator in WORLD_BANK_MA.items():
        try:
            series_map[output_col] = fetch_world_bank_indicator("MA", indicator, mrv=20)
            logger.info("WB MA %s -> %s (%d pts)", indicator, output_col, len(series_map[output_col]))
        except (requests.RequestException, ValueError, OSError) as exc:
            logger.warning("WB MA %s failed: %s", indicator, exc)
            series_map[output_col] = pd.Series(dtype=float)

    # World Bank (regional ATW footprint)
    for output_col, (country, indicator) in WORLD_BANK_REGIONAL.items():
        try:
            series_map[output_col] = fetch_world_bank_indicator(country, indicator, mrv=20)
            logger.info("WB %s %s -> %s (%d pts)", country, indicator, output_col, len(series_map[output_col]))
        except (requests.RequestException, ValueError, OSError) as exc:
            logger.warning("WB %s %s failed: %s", country, indicator, exc)
            series_map[output_col] = pd.Series(dtype=float)

    # IMF
    try:
        series_map["inflation_cpi_pct_imf"] = fetch_imf_datamapper_series("PCPIPCH", "MAR")
        logger.info("IMF PCPIPCH -> inflation_cpi_pct_imf (%d pts)", len(series_map["inflation_cpi_pct_imf"]))
    except (requests.RequestException, ValueError, OSError) as exc:
        logger.warning("IMF PCPIPCH failed: %s", exc)
        series_map["inflation_cpi_pct_imf"] = pd.Series(dtype=float)

    # yfinance
    for output_col, candidates in YF_CANDIDATES.items():
        series, used = fetch_first_available_yf(candidates)
        if used:
            logger.info("yfinance %s -> %s (%d pts)", used, output_col, len(series))
        else:
            logger.warning("yfinance failed for %s (candidates: %s)", output_col, ",".join(candidates))
        series_map[output_col] = series

    return series_map


def _to_daily_ffill(series: pd.Series, full_index: pd.DatetimeIndex) -> pd.Series:
    s = _to_datetime_index(series)
    if s.empty:
        return pd.Series(index=full_index, dtype=float)
    s_daily = s.resample("D").ffill()
    s_daily = s_daily.reindex(full_index).ffill()
    return s_daily


def _prune_sparse_columns(
    df: pd.DataFrame,
    max_missing_ratio: float,
    preserve: set[str] | None = None,
) -> tuple[pd.DataFrame, list[str]]:
    preserve_set = preserve or set()
    dropped: list[str] = []
    keep: list[str] = []

    for col in df.columns:
        if col in preserve_set:
            keep.append(col)
            continue
        missing_ratio = float(df[col].isna().mean())
        if missing_ratio > max_missing_ratio:
            dropped.append(col)
            continue
        keep.append(col)

    return df[keep].copy(), dropped


def build_daily_frame(
    series_map: dict[str, pd.Series],
    start_date: str,
    end_date: str | None,
    max_missing_ratio: float,
) -> pd.DataFrame:
    start = pd.Timestamp(start_date)
    end = pd.Timestamp(end_date) if end_date else pd.Timestamp(date.today())
    full_index = pd.date_range(start=start, end=end, freq="D")
    df = pd.DataFrame(index=full_index)

    # Base series
    direct_cols = [
        "bam_policy_rate",
        "interbank_rate",
        "money_supply_m1",
        "bank_roe",
        "gdp_volume_idx",
        "gdp_growth_pct",
        "external_debt_pct_gdp",
        "current_account_pct_gdp",
        "public_debt_pct_gdp",
        "gdp_per_capita_usd",
        "residential_property_idx",
        "eur_mad",
        "usd_mad",
        "brent_usd",
        "wheat_usd",
        "gold_usd",
        "vix",
        "sp500_close",
        "eem_close",
        "us10y_yield",
        "masi_close",
        "madex_close",
        "gdp_ci",
        "gdp_sn",
        "gdp_cm",
        "gdp_tn",
    ]
    for col in direct_cols:
        df[col] = _to_daily_ffill(series_map.get(col, pd.Series(dtype=float)), full_index)

    # Inflation precedence: FRED -> World Bank -> IMF
    infl_fred = _to_daily_ffill(series_map.get("inflation_cpi_pct_fred", pd.Series(dtype=float)), full_index)
    infl_wb = _to_daily_ffill(series_map.get("inflation_cpi_pct_wb", pd.Series(dtype=float)), full_index)
    infl_imf = _to_daily_ffill(series_map.get("inflation_cpi_pct_imf", pd.Series(dtype=float)), full_index)
    df["inflation_cpi_pct"] = infl_fred.combine_first(infl_wb).combine_first(infl_imf)

    # Unemployment precedence: FRED -> World Bank
    unemp_fred = _to_daily_ffill(series_map.get("unemployment_pct_fred", pd.Series(dtype=float)), full_index)
    unemp_wb = _to_daily_ffill(series_map.get("unemployment_pct_wb", pd.Series(dtype=float)), full_index)
    df["unemployment_pct"] = unemp_fred.combine_first(unemp_wb)

    # Required metadata + derived features
    df["frequency_tag"] = "daily_ffill"
    if df["bam_policy_rate"].notna().any() and df["inflation_cpi_pct"].notna().any():
        df["real_rate"] = df["bam_policy_rate"] - df["inflation_cpi_pct"]
    else:
        df["real_rate"] = pd.Series(index=full_index, dtype=float)

    if df["gdp_growth_pct"].notna().any():
        df["macro_momentum"] = df["gdp_growth_pct"].diff(4)
    else:
        df["macro_momentum"] = pd.Series(index=full_index, dtype=float)

    if df["eur_mad"].notna().any():
        df["fx_pressure_eur"] = df["eur_mad"].pct_change(20)
    else:
        df["fx_pressure_eur"] = pd.Series(index=full_index, dtype=float)

    if df["residential_property_idx"].notna().any():
        df["property_credit_risk"] = df["residential_property_idx"].pct_change(4)
    else:
        df["property_credit_risk"] = pd.Series(index=full_index, dtype=float)

    risk_flag = np.where(df["vix"].notna(), (df["vix"] > 25).astype(int), pd.NA)
    df["global_risk_flag"] = pd.Series(risk_flag, index=full_index, dtype="Int64")

    out = df.reset_index().rename(columns={"index": "date"})
    out["date"] = out["date"].dt.date.astype(str)
    out = out[OUTPUT_COLUMNS]
    out, dropped = _prune_sparse_columns(
        out,
        max_missing_ratio=max_missing_ratio,
        preserve={"date", "frequency_tag"},
    )
    if dropped:
        logger.info("Dropped sparse columns (missing ratio > %.2f): %s", max_missing_ratio, ",".join(dropped))
    return out


def write_output(df: pd.DataFrame, out_path: Path, full_refresh: bool) -> pd.DataFrame:
    out_path.parent.mkdir(parents=True, exist_ok=True)
    target_columns = list(df.columns)

    if out_path.exists() and not full_refresh:
        existing = pd.read_csv(out_path)
        combined = pd.concat([existing, df], ignore_index=True, sort=False)
        combined["date"] = pd.to_datetime(combined["date"], errors="coerce")
        combined = combined.dropna(subset=["date"])
        combined = combined.sort_values("date")
        combined = combined.drop_duplicates(subset=["date"], keep="last")
        combined["date"] = combined["date"].dt.date.astype(str)
        for col in target_columns:
            if col not in combined.columns:
                combined[col] = np.nan
        combined = combined[target_columns]
    else:
        combined = df.copy()

    combined.to_csv(out_path, index=False)
    _upsert_macro_df(combined)
    return combined


def log_summary(df: pd.DataFrame) -> None:
    if df.empty:
        logger.warning("Output dataframe is empty.")
        return
    logger.info("Rows: %d | Date range: %s -> %s", len(df), df["date"].iloc[0], df["date"].iloc[-1])
    for col in PHASE1_COLUMNS:
        non_null = int(df[col].notna().sum()) if col in df.columns else 0
        logger.info("Phase-1 coverage %-24s : %d non-null", col, non_null)


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Collect ATW macro/market context dataset.")
    p.add_argument("--out", type=Path, default=DEFAULT_OUTPUT, help="Output CSV path.")
    p.add_argument("--start-date", type=str, default=FRED_OBSERVATION_START, help="Start date YYYY-MM-DD.")
    p.add_argument("--end-date", type=str, default=None, help="End date YYYY-MM-DD (default: today).")
    p.add_argument(
        "--max-missing-ratio",
        type=float,
        default=0.0,
        help="Drop feature columns with missing ratio above this threshold (0.0 to 1.0). Default 0.0 keeps only fully available columns.",
    )
    p.add_argument("--full-refresh", action="store_true", help="Rewrite output file from scratch.")
    p.add_argument("--log-level", type=str, default="INFO", choices=["DEBUG", "INFO", "WARNING", "ERROR"])
    return p.parse_args()


def main() -> int:
    args = parse_args()
    logging.basicConfig(level=getattr(logging, args.log_level), format="%(asctime)s %(levelname)s %(message)s")
    if not 0.0 <= args.max_missing_ratio <= 1.0:
        raise ValueError("--max-missing-ratio must be between 0.0 and 1.0")

    logger.info("Collecting ATW macro series...")
    series_map = collect_series()

    logger.info("Building daily merged dataset...")
    daily_df = build_daily_frame(
        series_map,
        start_date=args.start_date,
        end_date=args.end_date,
        max_missing_ratio=args.max_missing_ratio,
    )

    logger.info("Writing output to %s", args.out)
    final_df = write_output(daily_df, args.out, full_refresh=args.full_refresh)

    log_summary(final_df)
    logger.info("Done.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
