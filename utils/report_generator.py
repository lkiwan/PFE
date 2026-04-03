"""Generate structured advisory reports in JSON and formatted text."""

import json
from datetime import datetime, timezone
from typing import Dict, Any


class ReportGenerator:
    """Produces the final advisory report."""

    def __init__(self, recommendation: Dict[str, Any], stock_data: dict):
        self.rec = recommendation
        self.data = stock_data

    def generate(self) -> Dict[str, Any]:
        """Generate the full report dict."""
        identity = self.data.get("identity", {})

        report = {
            "report_date": datetime.now(timezone.utc).strftime("%Y-%m-%d"),
            "stock": {
                "ticker": identity.get("ticker", "N/A"),
                "name": identity.get("full_name", "N/A"),
                "exchange": identity.get("exchange", "N/A"),
                "sector": identity.get("sector", "N/A"),
                "currency": identity.get("currency", "MAD"),
            },
            "current_price": self.rec.get("current_price"),
            "recommendation": self.rec.get("recommendation"),
            "confidence": self.rec.get("confidence"),
            "intrinsic_value": self.rec.get("intrinsic_value"),
            "factor_scores": self.rec.get("factor_scores"),
            "risk_assessment": self.rec.get("risk_assessment"),
            "model_details": self.rec.get("model_details"),
            "news_sentiment": self.rec.get("news_sentiment"),
            "key_metrics": self._extract_key_metrics(),
        }

        return report

    def generate_text(self) -> str:
        """Generate a human-readable text report."""
        report = self.generate()
        lines = []

        lines.append("=" * 70)
        lines.append("  STOCK ADVISORY REPORT")
        lines.append("=" * 70)
        lines.append("")

        # Stock info
        s = report["stock"]
        lines.append(f"  Stock:    {s['ticker']} - {s['name']}")
        lines.append(f"  Exchange: {s['exchange']}")
        lines.append(f"  Sector:   {s['sector']}")
        lines.append(f"  Date:     {report['report_date']}")
        lines.append("")

        # Recommendation
        rec = report["recommendation"]
        conf = report["confidence"]
        price = report["current_price"]
        iv = report["intrinsic_value"]

        lines.append("-" * 70)
        lines.append(f"  RECOMMENDATION:  {rec}")
        lines.append(f"  Confidence:      {conf}%")
        lines.append("-" * 70)
        lines.append("")
        lines.append(f"  Current Price:   {price:.2f} {s['currency']}")
        lines.append(f"  Fair Value:      {iv['weighted_average']:.2f} {s['currency']}")
        lines.append(f"  Range:           {iv['low_estimate']:.2f} - {iv['high_estimate']:.2f} {s['currency']}")
        lines.append(f"  Upside:          {iv['upside_pct']:+.1f}%")
        lines.append("")

        # Factor Scores
        lines.append("-" * 70)
        lines.append("  FACTOR SCORES (0-100)")
        lines.append("-" * 70)
        scores = report["factor_scores"]
        bar_width = 30
        for factor in ["value", "quality", "growth", "dividend", "safety"]:
            score = scores.get(factor, 0)
            filled = int(score / 100 * bar_width)
            bar = "#" * filled + "-" * (bar_width - filled)
            lines.append(f"  {factor.capitalize():12s} [{bar}] {score:.0f}")
        lines.append(f"  {'COMPOSITE':12s}                                {scores.get('composite', 0):.1f}")
        lines.append("")

        # Model Results
        lines.append("-" * 70)
        lines.append("  VALUATION MODELS")
        lines.append("-" * 70)
        for name, detail in report.get("model_details", {}).items():
            val = detail.get("intrinsic_value", 0)
            up = detail.get("upside_pct", 0)
            w = detail.get("weight", 0) * 100
            lines.append(f"  {name:25s}  {val:8.2f} MAD  ({up:+.1f}%)  [weight: {w:.0f}%]")
        lines.append("")

        # Risk Assessment
        risk = report.get("risk_assessment", {})
        lines.append("-" * 70)
        lines.append(f"  RISK LEVEL: {risk.get('level', 'N/A')}")
        lines.append("-" * 70)
        for r in risk.get("key_risks", []):
            lines.append(f"  - {r}")
        lines.append("")

        # News Sentiment
        news = report.get("news_sentiment")
        if news and news.get("total_articles", 0) > 0:
            lines.append("-" * 70)
            lines.append("  NEWS SENTIMENT")
            lines.append("-" * 70)
            lines.append(f"  Sentiment:       {news['sentiment_label']} (score: {news['sentiment_score']:.0f}/100)")
            lines.append(f"  Articles:        {news['total_articles']} (Pos: {news['positive_count']}, Neg: {news['negative_count']}, Neutral: {news['neutral_count']})")
            lines.append(f"  Activity:        {news['news_activity']}")
            if news.get("events_detected"):
                lines.append(f"  Events:          {', '.join(news['events_detected'])}")
            headlines = news.get("top_headlines", [])
            if headlines:
                lines.append("")
                lines.append("  Latest Headlines:")
                for h in headlines[:5]:
                    sent = h.get("sentiment", "neutral")[:3].upper()
                    date_str = f"  ({h['date']})" if h.get("date") else ""
                    title = h.get("title", "")[:70]
                    lines.append(f"    [{sent}] {title}{date_str}")
            lines.append("")

        # Key Metrics
        lines.append("-" * 70)
        lines.append("  KEY METRICS")
        lines.append("-" * 70)
        km = report.get("key_metrics", {})
        for k, v in km.items():
            label = k.replace("_", " ").title()
            if v is not None:
                if isinstance(v, float):
                    lines.append(f"  {label:25s}  {v:.2f}")
                else:
                    lines.append(f"  {label:25s}  {v}")
        lines.append("")
        lines.append("=" * 70)
        lines.append("  Generated by IAM Advisory System (PFE Project)")
        lines.append("=" * 70)

        return "\n".join(lines)

    def save_json(self, filepath: str = "advisory_report.json") -> None:
        """Save report as JSON file."""
        report = self.generate()
        with open(filepath, "w", encoding="utf-8") as f:
            json.dump(report, f, indent=2, ensure_ascii=False, default=str)

    def _extract_key_metrics(self) -> Dict[str, Any]:
        """Extract key financial metrics for the summary."""
        val = self.data.get("valuation", {})
        fin = self.data.get("financials", {})
        consensus = self.data.get("consensus", {})

        return {
            "pe_ratio": val.get("pe_ratio"),
            "ev_ebitda": val.get("ev_ebitda"),
            "price_to_book": val.get("price_to_book"),
            "dividend_yield": val.get("dividend_yield"),
            "ev_sales": val.get("ev_sales"),
            "ebitda_margin": self._latest(fin.get("ebitda_margin", {})),
            "net_margin": self._latest(fin.get("net_margin", {})),
            "roe": self._latest(fin.get("roe", {})),
            "roa": self._latest(fin.get("roa", {})),
            "debt_to_equity": self._latest(fin.get("debt_to_equity", {})),
            "current_ratio": self._latest(fin.get("current_ratio", {})),
            "analyst_consensus": consensus.get("consensus"),
        }

    def _latest(self, data: dict) -> Any:
        """Get the most recent value from a year-keyed dict."""
        if not isinstance(data, dict):
            return data
        for year in sorted(data.keys(), reverse=True):
            if data[year] is not None:
                return data[year]
        return None
