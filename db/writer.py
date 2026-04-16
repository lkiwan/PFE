"""Shared DB writer for the PFE pipeline.

Every upsert helper is idempotent and fail-open: if Postgres is unreachable,
writers log a warning and return 0 — scrapers continue producing CSV/JSON.
CSV/JSON stays the source of truth; the DB mirrors it.

Usage:
    from db.writer import upsert_prices, upsert_news, ...
    upsert_prices("ATW", [{"trade_date": "...", "close": 703.0, ...}, ...])
"""
from __future__ import annotations

import json
import logging
import os
from functools import lru_cache
from typing import Any, Dict, Iterable, List, Optional

from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine

log = logging.getLogger(__name__)

DB_URL = os.getenv("DATABASE_URL", "postgresql://postgres:123456@localhost:5432/PFE")

_engine: Optional[Engine] = None


def get_engine() -> Optional[Engine]:
    """Lazy, cached engine. Returns None if connection fails."""
    global _engine
    if _engine is not None:
        return _engine
    try:
        _engine = create_engine(DB_URL, pool_pre_ping=True)
        with _engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        return _engine
    except Exception as e:
        log.warning(f"DB unreachable ({e}); upserts will be skipped.")
        _engine = None
        return None


@lru_cache(maxsize=64)
def get_instrument_id(ticker: str) -> Optional[int]:
    """Look up instrument_id for a ticker. Cached per-process."""
    eng = get_engine()
    if eng is None:
        return None
    try:
        with eng.connect() as conn:
            row = conn.execute(
                text("SELECT instrument_id FROM ref.instruments WHERE ticker = :t"),
                {"t": ticker.upper()},
            ).fetchone()
            return row[0] if row else None
    except Exception as e:
        log.warning(f"instrument lookup failed for {ticker}: {e}")
        return None


def _failopen(fn):
    """Decorator: on any exception, log and return 0 (rows written)."""
    def wrapper(*args, **kwargs):
        try:
            return fn(*args, **kwargs)
        except Exception as e:
            log.warning(f"{fn.__name__} failed: {e}")
            return 0
    wrapper.__name__ = fn.__name__
    return wrapper


def _resolve(ticker: str) -> Optional[int]:
    eng = get_engine()
    if eng is None:
        return None
    iid = get_instrument_id(ticker)
    if iid is None:
        log.warning(f"ticker {ticker} not in ref.instruments; skipping write.")
    return iid


# ---------------------------------------------------------------------------
# upserts
# ---------------------------------------------------------------------------


@_failopen
def upsert_prices(ticker: str, rows: Iterable[Dict[str, Any]]) -> int:
    iid = _resolve(ticker)
    if iid is None:
        return 0
    payload = [{**r, "instrument_id": iid} for r in rows]
    if not payload:
        return 0
    sql = text("""
        INSERT INTO md.historical_prices
            (instrument_id, trade_date, open, close, high, low,
             shares_traded, value_traded_mad, num_trades, market_cap, source)
        VALUES
            (:instrument_id, :trade_date, :open, :close, :high, :low,
             :shares_traded, :value_traded_mad, :num_trades, :market_cap,
             COALESCE(:source, 'bourse_casa'))
        ON CONFLICT (instrument_id, trade_date) DO UPDATE SET
            open = EXCLUDED.open,
            close = EXCLUDED.close,
            high = EXCLUDED.high,
            low = EXCLUDED.low,
            shares_traded = EXCLUDED.shares_traded,
            value_traded_mad = EXCLUDED.value_traded_mad,
            num_trades = EXCLUDED.num_trades,
            market_cap = EXCLUDED.market_cap,
            source = EXCLUDED.source,
            scraped_at = NOW();
    """)
    with get_engine().begin() as conn:
        conn.execute(sql, payload)
    return len(payload)


@_failopen
def upsert_intraday(ticker: str, rows: Iterable[Dict[str, Any]]) -> int:
    iid = _resolve(ticker)
    if iid is None:
        return 0
    payload = [{**r, "instrument_id": iid} for r in rows]
    if not payload:
        return 0
    sql = text("""
        INSERT INTO md.intraday_snapshots
            (instrument_id, snapshot_ts, cotation_ts, market_status,
             last_price, open, high, low, prev_close, variation_pct,
             shares_traded, value_traded_mad, num_trades, market_cap)
        VALUES
            (:instrument_id, :snapshot_ts, :cotation_ts, :market_status,
             :last_price, :open, :high, :low, :prev_close, :variation_pct,
             :shares_traded, :value_traded_mad, :num_trades, :market_cap)
        ON CONFLICT (instrument_id, snapshot_ts) DO UPDATE SET
            cotation_ts = EXCLUDED.cotation_ts,
            market_status = EXCLUDED.market_status,
            last_price = EXCLUDED.last_price,
            open = EXCLUDED.open,
            high = EXCLUDED.high,
            low = EXCLUDED.low,
            prev_close = EXCLUDED.prev_close,
            variation_pct = EXCLUDED.variation_pct,
            shares_traded = EXCLUDED.shares_traded,
            value_traded_mad = EXCLUDED.value_traded_mad,
            num_trades = EXCLUDED.num_trades,
            market_cap = EXCLUDED.market_cap;
    """)
    with get_engine().begin() as conn:
        conn.execute(sql, payload)
    return len(payload)


@_failopen
def upsert_orderbook(ticker: str, rows: Iterable[Dict[str, Any]]) -> int:
    iid = _resolve(ticker)
    if iid is None:
        return 0
    payload = [{**r, "instrument_id": iid} for r in rows]
    if not payload:
        return 0
    cols = [
        "bid1_orders", "bid1_qty", "bid1_price",
        "bid2_orders", "bid2_qty", "bid2_price",
        "bid3_orders", "bid3_qty", "bid3_price",
        "bid4_orders", "bid4_qty", "bid4_price",
        "bid5_orders", "bid5_qty", "bid5_price",
        "ask1_price", "ask1_qty", "ask1_orders",
        "ask2_price", "ask2_qty", "ask2_orders",
        "ask3_price", "ask3_qty", "ask3_orders",
        "ask4_price", "ask4_qty", "ask4_orders",
        "ask5_price", "ask5_qty", "ask5_orders",
    ]
    col_list = ", ".join(cols)
    val_list = ", ".join(f":{c}" for c in cols)
    upd_list = ", ".join(f"{c} = EXCLUDED.{c}" for c in cols)
    sql = text(f"""
        INSERT INTO md.orderbook_snapshots
            (instrument_id, snapshot_ts, {col_list})
        VALUES
            (:instrument_id, :snapshot_ts, {val_list})
        ON CONFLICT (instrument_id, snapshot_ts) DO UPDATE SET
            {upd_list};
    """)
    with get_engine().begin() as conn:
        conn.execute(sql, payload)
    return len(payload)


@_failopen
def upsert_news(ticker: str, rows: Iterable[Dict[str, Any]]) -> int:
    iid = _resolve(ticker)
    if iid is None:
        return 0
    payload = [{**r, "instrument_id": iid} for r in rows]
    if not payload:
        return 0
    sql = text("""
        INSERT INTO md.news_articles
            (instrument_id, publish_date, title, source, url,
             full_content, query_source, signal_score, is_atw_core)
        VALUES
            (:instrument_id, :publish_date, :title, :source, :url,
             :full_content, :query_source, :signal_score, :is_atw_core)
        ON CONFLICT (url) DO UPDATE SET
            publish_date = EXCLUDED.publish_date,
            title = EXCLUDED.title,
            source = EXCLUDED.source,
            full_content = COALESCE(EXCLUDED.full_content, md.news_articles.full_content),
            query_source = EXCLUDED.query_source,
            signal_score = EXCLUDED.signal_score,
            is_atw_core = EXCLUDED.is_atw_core,
            scraped_at = NOW();
    """)
    with get_engine().begin() as conn:
        conn.execute(sql, payload)
    return len(payload)


@_failopen
def upsert_technicals(ticker: str, row: Dict[str, Any]) -> int:
    iid = _resolve(ticker)
    if iid is None:
        return 0
    technicals_json = row.get("technicals_json")
    if not isinstance(technicals_json, str):
        technicals_json = json.dumps(technicals_json)
    sql = text("""
        INSERT INTO md.technicals
            (instrument_id, as_of_date, trend, last_close, technicals_json)
        VALUES
            (:instrument_id, :as_of_date, :trend, :last_close, CAST(:technicals_json AS JSONB))
        ON CONFLICT (instrument_id, as_of_date) DO UPDATE SET
            trend = EXCLUDED.trend,
            last_close = EXCLUDED.last_close,
            technicals_json = EXCLUDED.technicals_json,
            computed_at = NOW();
    """)
    with get_engine().begin() as conn:
        conn.execute(sql, {
            "instrument_id": iid,
            "as_of_date": row["as_of_date"],
            "trend": row.get("trend"),
            "last_close": row.get("last_close"),
            "technicals_json": technicals_json,
        })
    return 1


@_failopen
def upsert_fundamentals(ticker: str, row: Dict[str, Any]) -> int:
    iid = _resolve(ticker)
    if iid is None:
        return 0
    hist_json = row.get("hist_json")
    if not isinstance(hist_json, str):
        hist_json = json.dumps(hist_json)
    sql = text("""
        INSERT INTO md.fundamentals
            (instrument_id, scrape_ts, price, market_cap, pe_ratio,
             price_to_book, dividend_yield, target_price, consensus,
             num_analysts, high_52w, low_52w, hist_json)
        VALUES
            (:instrument_id, :scrape_ts, :price, :market_cap, :pe_ratio,
             :price_to_book, :dividend_yield, :target_price, :consensus,
             :num_analysts, :high_52w, :low_52w, CAST(:hist_json AS JSONB))
        ON CONFLICT (instrument_id, scrape_ts) DO UPDATE SET
            price = EXCLUDED.price,
            market_cap = EXCLUDED.market_cap,
            pe_ratio = EXCLUDED.pe_ratio,
            price_to_book = EXCLUDED.price_to_book,
            dividend_yield = EXCLUDED.dividend_yield,
            target_price = EXCLUDED.target_price,
            consensus = EXCLUDED.consensus,
            num_analysts = EXCLUDED.num_analysts,
            high_52w = EXCLUDED.high_52w,
            low_52w = EXCLUDED.low_52w,
            hist_json = EXCLUDED.hist_json;
    """)
    with get_engine().begin() as conn:
        conn.execute(sql, {
            "instrument_id": iid,
            "scrape_ts": row["scrape_ts"],
            "price": row.get("price"),
            "market_cap": row.get("market_cap"),
            "pe_ratio": row.get("pe_ratio"),
            "price_to_book": row.get("price_to_book"),
            "dividend_yield": row.get("dividend_yield"),
            "target_price": row.get("target_price"),
            "consensus": row.get("consensus"),
            "num_analysts": row.get("num_analysts"),
            "high_52w": row.get("high_52w"),
            "low_52w": row.get("low_52w"),
            "hist_json": hist_json,
        })
    return 1


@_failopen
def upsert_macro(rows: Iterable[Dict[str, Any]]) -> int:
    payload = list(rows)
    if not payload:
        return 0
    eng = get_engine()
    if eng is None:
        return 0
    cols = [
        "frequency_tag", "bank_roe", "gdp_growth_pct",
        "external_debt_pct_gdp", "current_account_pct_gdp",
        "public_debt_pct_gdp", "gdp_per_capita_usd",
        "inflation_cpi_pct", "residential_property_idx",
        "gdp_ci", "gdp_sn", "gdp_cm", "gdp_tn",
    ]
    col_list = ", ".join(cols)
    val_list = ", ".join(f":{c}" for c in cols)
    upd_list = ", ".join(f"{c} = EXCLUDED.{c}" for c in cols)
    sql = text(f"""
        INSERT INTO md.macro_morocco (date, {col_list})
        VALUES (:date, {val_list})
        ON CONFLICT (date) DO UPDATE SET
            {upd_list},
            loaded_at = NOW();
    """)
    with eng.begin() as conn:
        conn.execute(sql, payload)
    return len(payload)
