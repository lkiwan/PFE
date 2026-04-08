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


def load_price_data(symbol: str) -> Optional[pd.DataFrame]:
    """Load daily OHLCV data from Bourse Casa CSV."""
    try:
        csv_path = _ROOT / "data" / "historical" / f"{symbol}_bourse_casa_full.csv"
        if not csv_path.exists():
            # Fallback to old IAM CSVs
            csv_path_1 = _ROOT / "IAM" / "IAM - Données Historiques dayli P.1.csv"
            csv_path_2 = _ROOT / "IAM" / "IAM - Données Historiques dayli P.2.csv"
            
            if csv_path_1.exists() and csv_path_2.exists():
                df1 = pd.read_csv(csv_path_1)
                df2 = pd.read_csv(csv_path_2)
                df = pd.concat([df1, df2], ignore_index=True)
            else:
                return None
        else:
            df = pd.read_csv(csv_path)
        
        # Normalize column names (Bourse Casa vs Investing.com format)
        df.columns = [c.strip().lower() for c in df.columns]
        
        # Map column variations
        if 'date' in df.columns:
            df.rename(columns={'date': 'Date'}, inplace=True)
        if 'close' in df.columns:
            df.rename(columns={
                'close': 'Close',
                'open': 'Open',
                'high': 'High',
                'low': 'Low',
                'volume': 'Volume'
            }, inplace=True)
        elif 'dernier' in df.columns:  # Investing.com French format
            df.rename(columns={
                'dernier': 'Close',
                'ouv.': 'Open',
                'plus haut': 'High',
                'plus bas': 'Low',
                'vol.': 'Volume'
            }, inplace=True)
        
        df['Date'] = pd.to_datetime(df['Date'], errors='coerce')
        df = df.dropna(subset=['Date'])
        df = df.sort_values('Date').reset_index(drop=True)
        
        return df
    except Exception as e:
        logging.warning(f"Could not load price data for {symbol}: {e}")
        return None


def load_news_data() -> Optional[pd.DataFrame]:
    """Load scraped news articles."""
    try:
        news_path = _ROOT / "testing" / "news_articles.csv"
        if news_path.exists():
            df = pd.read_csv(news_path)
            return df
        return None
    except Exception as e:
        logging.warning(f"Could not load news data: {e}")
        return None


def get_iam_stock_advisory_context() -> str:
    """
    PRODUCTION VERSION - Retrieves REAL calculated context for IAM.
    
    Aggregates:
    1. Real stock data (from merger - 100% quality)
    2. Normalized financials
    3. 5 valuation models → intrinsic value
    4. 5-factor scores → composite health
    5. Whale activity from daily CSV
    6. News sentiment from scraped headlines
    """
    try:
        symbol = "IAM"
        
        # 1. Load and normalize stock data
        logging.info(f"[1/7] Loading stock data for {symbol}...")
        raw_data = load_stock_data(symbol, verbose=False)
        
        logging.info("[2/7] Normalizing financial data...")
        stock_data = normalize_stock_data(raw_data)
        
        # Get current price
        current_price = stock_data.get("current_price") or stock_data.get("price_performance", {}).get("last_price", 0)
        
        # 2. Run valuation models
        logging.info("[3/7] Running 5 valuation models...")
        constants = {
            "risk_free_rate": RISK_FREE_RATE,
            "equity_risk_premium": EQUITY_RISK_PREMIUM,
            "beta": IAM_BETA,
            "tax_rate": CORPORATE_TAX_RATE,
            "terminal_growth": TERMINAL_GROWTH_RATE,
            "num_shares": NUM_SHARES
        }
        
        valuation_results = []
        models = [
            DCFModel(stock_data, constants),
            DDMModel(stock_data, constants),
            GrahamModel(stock_data, constants),
            MonteCarloModel(stock_data, constants),
            RelativeValuationModel(stock_data, constants)
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
                whale = WhaleStrategy(WhaleParams())
                signals_df = whale.generate_signals(price_df)
                
                # Get latest signal
                if len(signals_df) > 0:
                    latest = signals_df.iloc[-1]
                    whale_active = latest.get('signal', 'HOLD') == 'BUY'
                    
                    # Calculate 50-day SMA trend
                    if len(price_df) >= 50:
                        recent_price = price_df['Close'].iloc[-1]
                        sma_50 = price_df['Close'].rolling(50).mean().iloc[-1]
                        trend = "Uptrend (Price > SMA)" if recent_price > sma_50 else "Downtrend (Price < SMA)"
                    else:
                        trend = "Insufficient data"
                    
                    whale_data = {
                        "trend_50_day_sma": trend,
                        "whale_activity_today": whale_active,
                        "volume_vs_average": f"{latest.get('volume_ratio', 1.0):.1f}x Normal"
                    }
            except Exception as e:
                logging.warning(f"Whale detection failed: {e}")
        
        if not whale_data:
            whale_data = {
                "trend_50_day_sma": "Data unavailable",
                "whale_activity_today": False,
                "volume_vs_average": "Unknown"
            }
        
        # 6. News sentiment
        logging.info("[7/7] Analyzing news sentiment...")
        sentiment_data = {}
        news_df = load_news_data()
        if news_df is not None and len(news_df) > 0:
            try:
                analyzer = NewsSentimentAnalyzer()
                sentiment = analyzer.analyze_sentiment(news_df)
                
                sentiment_data = {
                    "sentiment": sentiment.get("overall_sentiment", "NEUTRAL"),
                    "score": sentiment.get("sentiment_score", 50),
                    "latest_headline": news_df.iloc[0].get('Title', 'No recent news')[:100]
                }
            except Exception as e:
                logging.warning(f"Sentiment analysis failed: {e}")
        
        if not sentiment_data:
            sentiment_data = {
                "sentiment": "NEUTRAL",
                "score": 50,
                "latest_headline": "No news data available"
            }
        
        # 7. Build final payload
        payload = {
            "stock": {
                "ticker": symbol,
                "name": stock_data.get("identity", {}).get("name", "ITISSALAT AL-MAGHRIB"),
                "current_price": round(current_price, 2)
            },
            "technical_and_whale_data": whale_data,
            "fundamental_valuation": {
                "calculated_intrinsic_value": recommendation["intrinsic_value"]["weighted_average"],
                "upside_percentage": f"{recommendation['intrinsic_value']['upside_pct']:+.1f}%",
                "model_confidence": f"{recommendation['confidence']:.0f}%"
            },
            "health_scores_out_of_100": {
                "composite_overall": factor_scores.get("composite", 50),
                "value_score": factor_scores.get("value", 50),
                "quality_score": factor_scores.get("quality", 50),
                "growth_score": factor_scores.get("growth", 50),
                "safety_score": factor_scores.get("safety", 50),
                "dividend_score": factor_scores.get("dividend", 50)
            },
            "risk_assessment": recommendation.get("risk_assessment", {
                "risk_level": "UNKNOWN",
                "key_risks_identified": []
            }),
            "recent_news_sentiment": sentiment_data
        }
        
        logging.info("✅ Context generation complete!")
        return json.dumps(payload, indent=2)
        
    except Exception as e:
        logging.error(f"Failed to generate context: {e}", exc_info=True)
        return json.dumps({
            "error": f"Failed to retrieve stock context: {str(e)}",
            "stock": {"ticker": "IAM", "current_price": 0}
        })
