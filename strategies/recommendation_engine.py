"""Recommendation engine — combines valuation models and factor scores
into a final BUY/HOLD/SELL advisory with confidence level."""

import statistics
from typing import List, Dict, Any

from models.base_model import ValuationResult
from utils.financial_constants import MODEL_WEIGHTS


class RecommendationEngine:
    """Combine multiple valuation results and factor scores into a recommendation."""

    def __init__(self, valuation_results: List[ValuationResult],
                 factor_scores: Dict[str, float],
                 current_price: float):
        self.results = valuation_results
        self.scores = factor_scores
        self.current_price = current_price

    def recommend(self) -> Dict[str, Any]:
        """Generate the final recommendation."""
        # 1. Weighted average intrinsic value
        weighted_value, model_details = self._aggregate_values()

        # 2. Compute upside/downside
        if self.current_price and self.current_price > 0:
            upside_pct = ((weighted_value - self.current_price) / self.current_price) * 100
        else:
            upside_pct = 0

        # 3. Value range
        all_lows = [r.intrinsic_value_low for r in self.results
                    if r.intrinsic_value_low and r.intrinsic_value_low > 0]
        all_highs = [r.intrinsic_value_high for r in self.results
                     if r.intrinsic_value_high and r.intrinsic_value_high > 0]
        low_estimate = statistics.median(all_lows) if all_lows else weighted_value * 0.8
        high_estimate = statistics.median(all_highs) if all_highs else weighted_value * 1.2

        # 4. Map to recommendation
        composite = self.scores.get("composite", 50)
        recommendation = self._map_recommendation(upside_pct, composite)

        # 5. Confidence
        confidence = self._compute_confidence()

        # 6. Risk assessment
        risk = self._assess_risk()

        return {
            "recommendation": recommendation,
            "confidence": round(confidence, 0),
            "current_price": self.current_price,
            "intrinsic_value": {
                "weighted_average": round(weighted_value, 2),
                "low_estimate": round(low_estimate, 2),
                "high_estimate": round(high_estimate, 2),
                "upside_pct": round(upside_pct, 1),
            },
            "factor_scores": self.scores,
            "model_details": model_details,
            "risk_assessment": risk,
        }

    def _aggregate_values(self):
        """Compute weighted average intrinsic value across models."""
        valid_results = [r for r in self.results if r.intrinsic_value > 0]
        if not valid_results:
            return self.current_price, {}

        total_weight = 0
        weighted_sum = 0
        model_details = {}

        for result in valid_results:
            # Get weight from config, default to equal weight
            name_key = result.model_name.lower().replace(" ", "_")
            weight = MODEL_WEIGHTS.get(name_key, 1.0 / len(valid_results))

            weighted_sum += result.intrinsic_value * weight
            total_weight += weight

            model_details[result.model_name] = {
                "intrinsic_value": result.intrinsic_value,
                "low": result.intrinsic_value_low,
                "high": result.intrinsic_value_high,
                "upside_pct": result.upside_pct,
                "confidence": result.confidence,
                "weight": weight,
                "methodology": result.methodology,
                "details": result.details,
            }

        fair_value = weighted_sum / total_weight if total_weight > 0 else self.current_price
        return fair_value, model_details

    def _map_recommendation(self, upside_pct: float, composite: float) -> str:
        """Map upside and composite score to a recommendation."""
        if upside_pct > 20 and composite >= 65:
            return "STRONG BUY"
        elif upside_pct > 10 and composite >= 55:
            return "BUY"
        elif upside_pct < -20 and composite < 35:
            return "STRONG SELL"
        elif upside_pct < -10 and composite < 45:
            return "SELL"
        else:
            return "HOLD"

    def _compute_confidence(self) -> float:
        """Confidence based on model agreement, data completeness, and range tightness."""
        valid = [r for r in self.results if r.intrinsic_value > 0]
        if not valid:
            return 0

        # 1. Model agreement: how close are the values?
        values = [r.intrinsic_value for r in valid]
        if len(values) >= 2:
            cv = statistics.stdev(values) / statistics.mean(values)
            agreement_score = max(0, 100 - cv * 200)  # Lower CV = higher score
        else:
            agreement_score = 50

        # 2. Average model confidence
        avg_model_conf = statistics.mean([r.confidence for r in valid])

        # 3. Number of models that produced results
        coverage_score = (len(valid) / len(self.results)) * 100

        # Weighted combination
        confidence = (
            agreement_score * 0.40 +
            avg_model_conf * 0.35 +
            coverage_score * 0.25
        )

        return max(10, min(95, confidence))

    def _assess_risk(self) -> Dict[str, Any]:
        """Assess investment risk based on factor scores."""
        composite = self.scores.get("composite", 50)
        safety = self.scores.get("safety", 50)

        # Risk level
        if safety >= 70 and composite >= 65:
            level = "LOW"
        elif safety >= 45 and composite >= 45:
            level = "MODERATE"
        else:
            level = "HIGH"

        # Identify key risks
        risks = []
        if self.scores.get("safety", 100) < 40:
            risks.append("Weak financial safety metrics (high leverage or low liquidity)")
        if self.scores.get("growth", 100) < 30:
            risks.append("Limited revenue and earnings growth prospects")
        if self.scores.get("value", 100) < 30:
            risks.append("Stock appears overvalued on multiple metrics")
        if self.scores.get("quality", 100) < 40:
            risks.append("Below-average profitability and earnings quality")

        # Check model disagreement
        valid = [r for r in self.results if r.intrinsic_value > 0]
        if len(valid) >= 2:
            values = [r.intrinsic_value for r in valid]
            spread = (max(values) - min(values)) / statistics.mean(values) * 100
            if spread > 80:
                risks.append(f"High model disagreement (spread: {spread:.0f}%)")

        if not risks:
            risks.append("No significant risks identified")

        return {
            "level": level,
            "key_risks": risks,
            "safety_score": self.scores.get("safety", 0),
        }
