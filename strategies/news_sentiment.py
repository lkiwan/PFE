"""News sentiment analysis for stock advisory.

Analyzes scraped news headlines to extract:
- Overall sentiment (positive/negative/neutral)
- Key event detection (earnings, dividends, management, M&A, regulatory)
- News recency and activity level
- Sentiment score that feeds into the recommendation
"""

import re
from typing import Dict, List, Any, Optional
from datetime import datetime


# Sentiment word lists (finance-specific)
POSITIVE_WORDS = {
    # Growth & Performance
    "growth", "grows", "grew", "increase", "increases", "increased", "rise", "rises",
    "rose", "gain", "gains", "gained", "profit", "profits", "profitable", "profitability",
    "surge", "surges", "surged", "jump", "jumps", "jumped", "soar", "soars", "soared",
    "rally", "rallies", "rallied", "record", "high", "higher", "highest", "peak",
    "boom", "booming", "strong", "stronger", "strongest", "robust", "solid",
    "outperform", "outperforms", "outperformed", "beat", "beats", "exceeded",
    "improvement", "improved", "improves", "recovery", "recovers", "recovered",
    "expansion", "expands", "expanded", "accelerate", "accelerates",
    # Dividends & Shareholder value
    "dividend", "dividends", "payout", "buyback", "repurchase", "reward",
    # Analyst sentiment
    "upgrade", "upgrades", "upgraded", "buy", "overweight", "outperform",
    "target", "raise", "raises", "raised", "recommend", "positive", "optimistic",
    "bullish", "attractive", "opportunity", "upside",
    # Business
    "partnership", "deal", "contract", "launch", "launches", "launched",
    "innovation", "innovative", "winning", "award", "leader", "leadership",
    "milestone", "success", "successful", "approve", "approved", "approval",
}

NEGATIVE_WORDS = {
    # Decline & Loss
    "decline", "declines", "declined", "decrease", "decreases", "decreased",
    "fall", "falls", "fell", "drop", "drops", "dropped", "loss", "losses",
    "plunge", "plunges", "plunged", "crash", "crashes", "crashed", "tumble",
    "slump", "slumps", "slumped", "sink", "sinks", "sank", "slide", "slides",
    "low", "lower", "lowest", "weak", "weaker", "weakest", "poor", "negative",
    "underperform", "underperforms", "underperformed", "miss", "misses", "missed",
    "disappoint", "disappoints", "disappointed", "disappointing",
    # Risk & Problems
    "risk", "risks", "risky", "warning", "warns", "warned", "concern", "concerns",
    "worried", "threat", "threatens", "threatened", "crisis", "trouble", "troubled",
    "lawsuit", "litigation", "penalty", "fine", "fined", "fraud", "scandal",
    "investigation", "probe", "downgrade", "downgrades", "downgraded",
    # Financial distress
    "debt", "default", "bankruptcy", "restructuring", "layoff", "layoffs",
    "cut", "cuts", "reduction", "suspend", "suspends", "suspended",
    "bearish", "sell", "underweight", "reduce", "downside",
    # Regulatory
    "regulation", "regulatory", "sanction", "sanctions", "ban", "banned",
}

# Event categories and their keywords
EVENT_CATEGORIES = {
    "earnings": ["earnings", "results", "revenue", "profit", "income", "quarter", "annual",
                 "financial results", "fiscal", "eps", "ebitda"],
    "dividend": ["dividend", "payout", "distribution", "ex-dividend", "yield"],
    "management": ["ceo", "cfo", "chairman", "director", "appoint", "resign", "management",
                   "board", "executive", "leadership"],
    "merger_acquisition": ["merger", "acquisition", "acquire", "takeover", "bid", "deal",
                          "joint venture", "partnership", "stake", "shareholding"],
    "regulatory": ["regulation", "regulatory", "license", "compliance", "antitrust",
                   "government", "ministry", "authority", "approval", "permit"],
    "expansion": ["launch", "expand", "expansion", "new market", "5g", "fiber", "network",
                  "infrastructure", "investment", "deploy", "rollout"],
    "market": ["stock", "share", "market", "trading", "index", "bourse", "casablanca",
               "masi", "analyst", "rating", "target price"],
}


class NewsSentimentAnalyzer:
    """Analyze news articles for sentiment and events."""

    def __init__(self, news_data: dict = None):
        if news_data is None:
            news_data = {}
        self.articles = news_data.get("articles", [])
        self.total_count = news_data.get("total_count", 0)
    
    def analyze_sentiment(self, news_df) -> Dict[str, Any]:
        """Analyze sentiment from a pandas DataFrame of news articles.
        
        Expected columns: Title, Date (others are optional)
        """
        if news_df is None or len(news_df) == 0:
            return {
                "overall_sentiment": "NEUTRAL",
                "sentiment_score": 50,
                "total_articles": 0
            }
        
        # Convert DataFrame to article list
        articles = []
        for _, row in news_df.iterrows():
            articles.append({
                "title": row.get('Title', ''),
                "date": row.get('Date', ''),
                "snippet": row.get('Full_Content', '') or ''
            })
        
        # Set articles and run analysis
        self.articles = articles
        self.total_count = len(articles)
        result = self.analyze()
        
        return {
            "overall_sentiment": result["sentiment_label"],
            "sentiment_score": result["sentiment_score"],
            "total_articles": result["total_articles"],
            "positive_count": result["positive_count"],
            "negative_count": result["negative_count"],
            "events_detected": result["events_detected"]
        }

    def analyze(self) -> Dict[str, Any]:
        """Run full sentiment analysis on news articles."""
        if not self.articles:
            return {
                "sentiment_score": 50.0,  # Neutral when no data
                "sentiment_label": "NEUTRAL",
                "positive_count": 0,
                "negative_count": 0,
                "neutral_count": 0,
                "total_articles": 0,
                "events_detected": [],
                "top_headlines": [],
                "news_activity": "NONE",
                "details": {},
            }

        # Analyze each article
        article_sentiments = []
        all_events = []
        top_headlines = []

        for article in self.articles[:20]:
            title = article.get("title", "") or ""
            snippet = article.get("snippet", "") or ""
            text = f"{title} {snippet}".lower()

            # Sentiment scoring
            pos_count = sum(1 for w in POSITIVE_WORDS if w in text)
            neg_count = sum(1 for w in NEGATIVE_WORDS if w in text)

            if pos_count > neg_count:
                sentiment = "positive"
                score = min(100, 50 + (pos_count - neg_count) * 15)
            elif neg_count > pos_count:
                sentiment = "negative"
                score = max(0, 50 - (neg_count - pos_count) * 15)
            else:
                sentiment = "neutral"
                score = 50

            article_sentiments.append({
                "title": title,
                "sentiment": sentiment,
                "score": score,
                "positive_words": pos_count,
                "negative_words": neg_count,
            })

            # Event detection
            for category, keywords in EVENT_CATEGORIES.items():
                if any(kw in text for kw in keywords):
                    all_events.append({
                        "category": category,
                        "title": article.get("title"),
                        "date": article.get("date"),
                    })

            # Top headlines
            if title:
                top_headlines.append({
                    "title": article.get("title"),
                    "date": article.get("date"),
                    "sentiment": sentiment,
                })

        # Aggregate sentiment
        scores = [a["score"] for a in article_sentiments]
        avg_score = sum(scores) / len(scores) if scores else 50

        positive_count = sum(1 for a in article_sentiments if a["sentiment"] == "positive")
        negative_count = sum(1 for a in article_sentiments if a["sentiment"] == "negative")
        neutral_count = sum(1 for a in article_sentiments if a["sentiment"] == "neutral")

        # Sentiment label
        if avg_score >= 65:
            label = "POSITIVE"
        elif avg_score <= 35:
            label = "NEGATIVE"
        else:
            label = "NEUTRAL"

        # News activity level
        total = len(self.articles)
        if total >= 10:
            activity = "HIGH"
        elif total >= 5:
            activity = "MODERATE"
        elif total >= 1:
            activity = "LOW"
        else:
            activity = "NONE"

        # Unique event categories
        unique_events = list({e["category"] for e in all_events})

        return {
            "sentiment_score": round(avg_score, 1),
            "sentiment_label": label,
            "positive_count": positive_count,
            "negative_count": negative_count,
            "neutral_count": neutral_count,
            "total_articles": total,
            "events_detected": unique_events,
            "top_headlines": top_headlines[:5],
            "news_activity": activity,
            "details": {
                "article_sentiments": article_sentiments[:10],
                "all_events": all_events[:10],
            },
        }
