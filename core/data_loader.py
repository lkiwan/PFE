"""Load scraped stock data from JSON output."""

import json
import os
from typing import Optional


def load_stock_data(json_path: str = "testing/stock_data.json") -> dict:
    """Load the first stock from the scraper JSON output.

    Tries multiple known output paths if the given one doesn't exist.
    Returns the stock dict (identity, price_performance, valuation, financials, etc.)
    """
    search_paths = [
        json_path,
        "testing/testing/stock_data.json",
        "testing/stock_data.json",
    ]

    for path in search_paths:
        if os.path.exists(path):
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)

            stocks = data.get("stocks", [])
            if stocks:
                return stocks[0]

            raise ValueError(f"No stocks found in {path}")

    raise FileNotFoundError(
        f"Stock data JSON not found. Searched: {search_paths}"
    )


def load_all_stocks(json_path: str = "testing/stock_data.json") -> list:
    """Load all stocks from the scraper JSON output."""
    search_paths = [
        json_path,
        "testing/testing/stock_data.json",
        "testing/stock_data.json",
    ]

    for path in search_paths:
        if os.path.exists(path):
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
            return data.get("stocks", [])

    raise FileNotFoundError(
        f"Stock data JSON not found. Searched: {search_paths}"
    )
