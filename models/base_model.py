"""Abstract base class for all valuation models."""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Optional, Dict, Any


@dataclass
class ValuationResult:
    """Output of a single valuation model."""
    model_name: str
    intrinsic_value: float                          # Per-share fair value in MAD
    intrinsic_value_low: Optional[float] = None     # Bear-case estimate
    intrinsic_value_high: Optional[float] = None    # Bull-case estimate
    upside_pct: float = 0.0                         # vs current market price
    confidence: float = 0.0                         # 0-100 scale
    methodology: str = ""                           # Brief description
    details: Dict[str, Any] = field(default_factory=dict)


class BaseValuationModel(ABC):
    """Base class all valuation models inherit from."""

    def __init__(self, stock_data: dict, constants: dict):
        self.data = stock_data
        self.constants = constants

    @abstractmethod
    def calculate(self) -> ValuationResult:
        """Run the valuation and return a result."""
        pass

    def _current_price(self) -> float:
        return self.data.get("current_price") or self.data["price_performance"]["last_price"]

    def _get_financial(self, field: str, year: str = None) -> Optional[float]:
        """Get a financial metric, optionally for a specific year."""
        fin = self.data.get("financials", {})
        field_data = fin.get(field)
        if field_data is None:
            return None
        if isinstance(field_data, dict):
            if year:
                return field_data.get(year)
            # Return most recent non-None value
            for y in sorted(field_data.keys(), reverse=True):
                if field_data[y] is not None:
                    return field_data[y]
            return None
        return field_data

    def _get_valuation(self, field: str) -> Optional[float]:
        """Get a valuation metric."""
        return self.data.get("valuation", {}).get(field)

    def _get_hist_values(self, section: str, field: str,
                         years: list = None) -> Dict[str, float]:
        """Get historical values for a metric, filtering to specified years."""
        data = self.data.get(section, {}).get(field, {})
        if not isinstance(data, dict):
            return {}
        if years:
            return {y: v for y, v in data.items() if y in years and v is not None}
        return {y: v for y, v in data.items() if v is not None}

    def _compute_upside(self, fair_value: float) -> float:
        """Compute upside percentage vs current price."""
        price = self._current_price()
        if price and price > 0:
            return ((fair_value - price) / price) * 100
        return 0.0
