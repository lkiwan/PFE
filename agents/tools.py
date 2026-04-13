"""Real-time stock advisory context generator for AI agent.

Wires together all pipeline components:
- Data Merger: Complete stock data (100% quality)
- Data Normalizer: Clean mixed-unit data
- 5 Valuation Models: DCF, DDM, Graham, Monte Carlo, Relative
- Scoring Engine: 5-factor fundamental scores
- Recommendation Engine: Intrinsic value + confidence
- Whale Strategy: Volume spike detection from daily CSVs
- News Sentiment: Keyword-based sentiment from scraped news
"""

import json
import logging
import sys
from pathlib import Path
from typing import Dict, Any, Optional
import pandas as pd
from datetime import datetime

# Setup paths
_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_ROOT))

# Import pipeline components
from core.data_merger import load_stock_data
from core.data_normalizer import normalize_stock_data
from models.dcf_model import DCFModel
from models.ddm_model import DDMModel
from models.graham_model import GrahamModel
from models.monte_carlo import MonteCarloModel
from models.relative_valuation import RelativeValuationModel
from strategies.scoring_engine import ScoringEngine
from strategies.recommendation_engine import RecommendationEngine
from strategies.whale_strategy import WhaleStrategy, WhaleParams
from strategies.news_sentiment import NewsSentimentAnalyzer
from utils.financial_constants import (
    RISK_FREE_RATE, EQUITY_RISK_PREMIUM, IAM_BETA,
    CORPORATE_TAX_RATE, TERMINAL_GROWTH_RATE, NUM_SHARES
)


# =============================================================================
# Format converter: flat merged JSON → nested structure for models/scoring
# =============================================================================

def convert_flat_to_nested(flat: Dict[str, Any]) -> Dict[str, Any]:
    """
    Convert the flat merged JSON format into the nested format
    that the valuation models, scoring engine, and normalizer expect.

    Flat (from data_merger):
        {"price": 96, "hist_revenue": {"2021": 35790}, "pe_ratio": 15.7, ...}

    Nested (what models expect):
        {"financials": {"net_sales": {"2021": 35790}, ...},
         "valuation": {"pe_ratio": 15.7, ...},
         "price_performance": {"last_price": 96}, ...}
    """
    nested: Dict[str, Any] = {
        "identity": {
            "symbol": flat.get("symbol", ""),
            "name": flat.get("symbol", ""),
        },
        "financials": {},
        "valuation": {},
        "price_performance": {},
    }

    # --- Price / market data → price_performance ---
    pp = nested["price_performance"]
    pp["last_price"] = flat.get("price")
    pp["high_52w"] = flat.get("high_52w")
    pp["low_52w"] = flat.get("low_52w")
    pp["volume"] = flat.get("volume")

    # --- Valuation scalars ---
    val = nested["valuation"]
    val["pe_ratio"] = flat.get("pe_ratio")
    val["price_to_book"] = flat.get("price_to_book")
    val["dividend_yield"] = flat.get("dividend_yield")
    val["market_cap"] = flat.get("market_cap")
    val["consensus"] = flat.get("consensus")
    val["target_price"] = flat.get("target_price")
    val["num_analysts"] = flat.get("num_analysts")

    # EV/EBITDA: use latest year from hist as the current scalar
    hist_ev_ebitda = flat.get("hist_ev_ebitda", {})
    if hist_ev_ebitda:
        latest_year = max(hist_ev_ebitda.keys())
        val["ev_ebitda"] = hist_ev_ebitda[latest_year]
    val["ev_ebitda_hist"] = hist_ev_ebitda

    # Dividend per share history → valuation section
    val["dividend_per_share_hist"] = flat.get("hist_dividend_per_share", {})

    # --- Financials: map flat hist_* → nested financials ---
    fin = nested["financials"]

    # Monetary fields that should be in millions MAD.
    # MarketScreener V3 scrapes some pages in full MAD (e.g. 18,800,000,000)
    # and others already in millions (e.g. 35,790). We detect and normalize.
    monetary_field_map = {
        "hist_revenue":     "net_sales",
        "hist_net_income":  "net_income",
        "hist_ebitda":      "ebitda",
        "hist_fcf":         "free_cash_flow",
        "hist_ocf":         "operating_cash_flow",
        "hist_capex":       "capex",
        "hist_debt":        "total_debt",
        "hist_cash":        "cash_and_equivalents",
        "hist_equity":      "shareholders_equity",
    }

    # Non-monetary fields (percentages, ratios, per-share) — keep as-is
    nonmon_field_map = {
        "hist_eps":           "eps",
        "hist_net_margin":    "net_margin",
        "hist_ebit_margin":   "ebit_margin",
        "hist_ebitda_margin": "ebitda_margin",
        "hist_gross_margin":  "gross_margin",
        "hist_roe":           "roe",
        "hist_roce":          "roce",
        "hist_eps_growth":    "eps_growth",
    }

    def _to_millions(series: dict) -> dict:
        """Normalize a dict of {year: value} so all values are in millions MAD.
        Values > 500,000 are assumed to be in full MAD and get divided by 1M.
        Values <= 500,000 are assumed to already be in millions."""
        out = {}
        for year, val in series.items():
            if val is None:
                continue
            if abs(val) > 500_000:
                out[year] = val / 1_000_000
            else:
                out[year] = val
        return out

    for flat_key, nested_key in monetary_field_map.items():
        data = flat.get(flat_key, {})
        if data:
            fin[nested_key] = _to_millions(data)

    for flat_key, nested_key in nonmon_field_map.items():
        data = flat.get(flat_key, {})
        if data:
            fin[nested_key] = dict(data)

    # Also copy revenues as "revenues" alias (some models use it)
    if "net_sales" in fin:
        fin["revenues"] = fin["net_sales"]

    # Market cap to millions
    if val.get("market_cap") and val["market_cap"] > 500_000:
        val["market_cap"] = val["market_cap"] / 1_000_000

    # --- Derive some fields models may need ---

    # Net debt = total_debt - cash
    if fin.get("total_debt") and fin.get("cash_and_equivalents"):
        fin["net_debt"] = {}
        for year in fin["total_debt"]:
            d = fin["total_debt"].get(year)
            c = fin["cash_and_equivalents"].get(year, 0)
            if d is not None:
                fin["net_debt"][year] = d - (c or 0)

    # Debt to equity ratio
    if fin.get("total_debt") and fin.get("shareholders_equity"):
        fin["debt_to_equity"] = {}
        for year in fin["total_debt"]:
            d = fin["total_debt"].get(year)
            e = fin["shareholders_equity"].get(year)
            if d is not None and e is not None and e != 0:
                fin["debt_to_equity"][year] = d / e

    # Store current_price at top level for easy access
    nested["current_price"] = flat.get("price")

    return nested


# =============================================================================
# Data loaders
# =============================================================================

def load_price_data(symbol: str) -> Optional[pd.DataFrame]:
    """Load daily OHLCV data from Bourse Casa CSV."""
    try:
        csv_path = _ROOT / "data" / "historical" / f"{symbol}_bourse_casa_full.csv"
        if not csv_path.exists():
            return None

        # Try multiple encodings (Bourse Casa CSV may be UTF-8-BOM or Latin-1)
        for enc in ("utf-8-sig", "utf-8", "latin-1"):
            try:
                df = pd.read_csv(csv_path, encoding=enc)
                break
            except UnicodeDecodeError:
                continue
        else:
            df = pd.read_csv(csv_path, encoding="utf-8", errors="replace")

        # Normalize column names: strip whitespace, lowercase for matching
        raw_cols = list(df.columns)
        col_map = {}
        for col in raw_cols:
            cl = col.strip().lower()
            # Date column
            if cl in ('séance', 'seance', 'date', 's\xe9ance') or 'ance' in cl:
                col_map[col] = 'Date'
            # Close
            elif 'dernier' in cl or cl == 'close' or 'courscourant' in cl:
                col_map[col] = 'Close'
            # High
            elif '+haut' in cl or cl == 'high' or 'highprice' in cl:
                col_map[col] = 'High'
            # Low
            elif '+bas' in cl or cl == 'low' or 'lowprice' in cl:
                col_map[col] = 'Low'
            # Open
            elif 'ouverture' in cl or cl == 'open' or 'openprice' in cl:
                col_map[col] = 'Open'
            # Volume (number of shares traded)
            elif 'nombre de titres' in cl or 'titres' in cl:
                col_map[col] = 'Volume'
            elif cl == 'volume' or 'cumultitres' in cl:
                col_map[col] = 'Volume'

        df.rename(columns=col_map, inplace=True)

        if 'Date' not in df.columns:
            return None

        df['Date'] = pd.to_datetime(df['Date'], errors='coerce')
        df = df.dropna(subset=['Date'])
        df = df.sort_values('Date').reset_index(drop=True)

        # Ensure numeric columns
        for col in ('Close', 'High', 'Low', 'Open', 'Volume'):
            if col in df.columns:
                df[col] = pd.to_numeric(df[col], errors='coerce')

        return df
    except Exception as e:
        logging.warning(f"Could not load price data for {symbol}: {e}")
        return None


def load_news_data(symbol: str = None) -> Optional[pd.DataFrame]:
    """Load scraped news articles, optionally filtered by symbol."""
    try:
        news_path = _ROOT / "testing" / "news_articles.csv"
        if not news_path.exists():
            return None
        df = pd.read_csv(news_path)
        if symbol and 'Ticker' in df.columns:
            filtered = df[df['Ticker'].str.upper() == symbol.upper()]
            if len(filtered) > 0:
                return filtered
        return df if len(df) > 0 else None
    except Exception as e:
        logging.warning(f"Could not load news data: {e}")
        return None


# =============================================================================
# Main context generator
# =============================================================================

def get_stock_advisory_context(symbol: str = "IAM") -> str:
    """
    Generate full advisory context for any stock.

    Aggregates:
    1. Real stock data (from merger - 100% quality)
    2. Normalized financials
    3. 5 valuation models → intrinsic value
    4. 5-factor scores → composite health
    5. Whale activity from daily CSV
    6. News sentiment from scraped headlines
    """
    try:
        # 1. Load merged data and convert to nested format
        logging.info(f"[1/7] Loading stock data for {symbol}...")
        raw_flat = load_stock_data(symbol, verbose=False)

        logging.info("[2/7] Converting and normalizing financial data...")
        nested_data = convert_flat_to_nested(raw_flat)
        stock_data = normalize_stock_data(nested_data)

        # Get current price
        current_price = (
            stock_data.get("current_price")
            or stock_data.get("price_performance", {}).get("last_price", 0)
        )

        if not current_price or current_price <= 0:
            current_price = raw_flat.get("price", 0)

        # 2. Run valuation models
        logging.info("[3/7] Running 5 valuation models...")
        constants = {
            "risk_free_rate": RISK_FREE_RATE,
            "equity_risk_premium": EQUITY_RISK_PREMIUM,
            "beta": IAM_BETA,
            "tax_rate": CORPORATE_TAX_RATE,
            "terminal_growth": TERMINAL_GROWTH_RATE,
            "num_shares": NUM_SHARES,
        }

        valuation_results = []
        models = [
            DCFModel(stock_data, constants),
            DDMModel(stock_data, constants),
            GrahamModel(stock_data, constants),
            MonteCarloModel(stock_data, constants),
            RelativeValuationModel(stock_data, constants),
        ]

        for model in models:
            try:
                result = model.calculate()
                if result.intrinsic_value > 0:
                    valuation_results.append(result)
            except Exception as e:
                logging.warning(f"Model {model.__class__.__name__} failed: {e}")

        # 3. Run scoring engine
        logging.info("[4/7] Calculating 5-factor health scores...")
        scorer = ScoringEngine(stock_data)
        factor_scores = scorer.score()

        # 4. Run recommendation engine
        logging.info("[5/7] Generating recommendation...")
        recommender = RecommendationEngine(valuation_results, factor_scores, current_price)
        recommendation = recommender.recommend()

        # 5. Whale activity detection
        logging.info("[6/7] Detecting whale activity...")
        whale_data = {}
        price_df = load_price_data(symbol)
        if price_df is not None and len(price_df) > 50:
            try:
                # WhaleStrategy expects lowercase columns: close, open, high, low, volume
                whale_df = price_df.rename(columns={
                    'Close': 'close', 'Open': 'open', 'High': 'high',
                    'Low': 'low', 'Volume': 'volume', 'Date': 'date',
                })

                whale = WhaleStrategy(WhaleParams())
                signals_df = whale.generate_signals(whale_df)

                if len(signals_df) > 0:
                    latest = signals_df.iloc[-1]
                    whale_active = latest.get('signal', 'HOLD') == 'BUY'

                    if 'close' in whale_df.columns and len(whale_df) >= 50:
                        recent_price = whale_df['close'].iloc[-1]
                        sma_50 = whale_df['close'].rolling(50).mean().iloc[-1]
                        trend = "Uptrend (Price > SMA)" if recent_price > sma_50 else "Downtrend (Price < SMA)"
                    else:
                        trend = "Insufficient data"

                    whale_data = {
                        "trend_50_day_sma": trend,
                        "whale_activity_today": whale_active,
                        "volume_vs_average": f"{latest.get('volume_ratio', 1.0):.1f}x Normal",
                    }
            except Exception as e:
                logging.warning(f"Whale detection failed: {e}")

        if not whale_data:
            whale_data = {
                "trend_50_day_sma": "Data unavailable",
                "whale_activity_today": False,
                "volume_vs_average": "Unknown",
            }

        # 6. News sentiment
        logging.info("[7/7] Analyzing news sentiment...")
        sentiment_data = {}
        news_df = load_news_data(symbol)
        if news_df is not None and len(news_df) > 0:
            try:
                analyzer = NewsSentimentAnalyzer()
                sentiment = analyzer.analyze_sentiment(news_df)

                headline = "No recent news"
                if 'Title' in news_df.columns:
                    headline = str(news_df.iloc[0].get('Title', ''))[:100]

                sentiment_data = {
                    "sentiment": sentiment.get("overall_sentiment", "NEUTRAL"),
                    "score": sentiment.get("sentiment_score", 50),
                    "total_articles": sentiment.get("total_articles", 0),
                    "latest_headline": headline,
                }
            except Exception as e:
                logging.warning(f"Sentiment analysis failed: {e}")

        if not sentiment_data:
            sentiment_data = {
                "sentiment": "NEUTRAL",
                "score": 50,
                "total_articles": 0,
                "latest_headline": "No news data available",
            }

        # 7. Build final payload
        intrinsic = recommendation.get("intrinsic_value", {})
        risk = recommendation.get("risk_assessment", {})

        payload = {
            "stock": {
                "ticker": symbol,
                "name": raw_flat.get("symbol", symbol),
                "current_price": round(current_price, 2),
            },
            "technical_and_whale_data": whale_data,
            "fundamental_valuation": {
                "calculated_intrinsic_value": intrinsic.get("weighted_average", current_price),
                "low_estimate": intrinsic.get("low_estimate"),
                "high_estimate": intrinsic.get("high_estimate"),
                "upside_percentage": f"{intrinsic.get('upside_pct', 0):+.1f}%",
                "model_confidence": f"{recommendation.get('confidence', 0):.0f}%",
                "recommendation": recommendation.get("recommendation", "HOLD"),
                "models_used": len(valuation_results),
            },
            "health_scores_out_of_100": {
                "composite_overall": factor_scores.get("composite", 50),
                "value_score": factor_scores.get("value", 50),
                "quality_score": factor_scores.get("quality", 50),
                "growth_score": factor_scores.get("growth", 50),
                "safety_score": factor_scores.get("safety", 50),
                "dividend_score": factor_scores.get("dividend", 50),
            },
            "risk_assessment": {
                "risk_level": risk.get("level", "UNKNOWN"),
                "key_risks_identified": risk.get("key_risks", []),
                "safety_score": risk.get("safety_score", 0),
            },
            "recent_news_sentiment": sentiment_data,
        }

        logging.info(f"Context generation complete for {symbol}!")
        return json.dumps(payload, indent=2)

    except Exception as e:
        logging.error(f"Failed to generate context for {symbol}: {e}", exc_info=True)
        return json.dumps({
            "error": f"Failed to retrieve stock context: {str(e)}",
            "stock": {"ticker": symbol, "current_price": 0},
        })


# Backward compatibility alias
def get_iam_stock_advisory_context() -> str:
    """Backward-compatible wrapper — calls get_stock_advisory_context('IAM')."""
    return get_stock_advisory_context("IAM")
