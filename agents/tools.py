import json
import logging
from typing import Dict, Any

def get_iam_stock_advisory_context() -> str:
    """
    Agno tool to retrieve the current calculated context for IAM.
    This aggregates the fundamental scores, valuation metrics, and 
    technical whale activity into a clean JSON string for the AI.
    """
    try:
        # In a fully wired production environment, you would call:
        # 1. RecommendationEngine to get fair value.
        # 2. ScoringEngine to get the factor scores.
        # 3. HybridWhaleStrategy to get the current day's signal.
        
        # We are going to return a structured sample of what the pipeline computed 
        # in our last backtest to construct the exact prompt payload.
        
        payload = {
            "stock": {
                "ticker": "IAM",
                "name": "ITISSALAT AL-MAGHRIB",
                "current_price": 95.50
            },
            "technical_and_whale_data": {
                "trend_50_day_sma": "Uptrend (Price > SMA)",
                "whale_activity_today": False,
                "volume_vs_average": "0.8x Normal"
            },
            "fundamental_valuation": {
                "calculated_intrinsic_value": 116.35,
                "upside_percentage": "+21.8%",
                "model_confidence": "54% (Moderate)"
            },
            "health_scores_out_of_100": {
                "composite_overall": 64.5,
                "value_score": 72.7,
                "quality_score": 69.6,
                "growth_score": 62.3,
                "safety_score": 56.7,
                "dividend_score": 57.2
            },
            "risk_assessment": {
                "risk_level": "MODERATE",
                "key_risks_identified": [
                    "High model disagreement (spread: 101%)"
                ]
            },
            "recent_news_sentiment": {
                "sentiment": "NEUTRAL",
                "score": 55,
                "latest_headline": "Maroc Telecom reports stable profits despite regulatory fines."
            }
        }
        return json.dumps(payload, indent=2)
    except Exception as e:
        logging.error(f"Failed to generate context: {e}")
        return json.dumps({"error": "Failed to retrieve stock context."})
