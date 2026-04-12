"""Configuration for MarketScreener scraper."""

# Base URLs
BASE_URL = "https://www.marketscreener.com/quote/stock"

# Stock configurations for Moroccan stocks
STOCKS = {
    "IAM": {
        "url_code": "ITISSALAT-AL-MAGHRIB-IAM--1408717",
        "full_name": "Itissalat Al-Maghrib (IAM) S.A.",
        "ticker": "IAM",
        "exchange": "Casablanca S.E.",
        "currency": "MAD"
    }
}

# Sub-pages to scrape
PAGES = {
    "main": "",
    "finances": "/finances/",
    "consensus": "/consensus/",
    "valuation": "/valuation/",
    "calendar": "/calendar/",
    "company": "/company/",
    "sector": "/sector/"
}

# HTTP Request settings
REQUEST_CONFIG = {
    "timeout": 30,
    "max_retries": 3,
    "retry_delay": 2,
    "min_delay": 2,
    "max_delay": 5
}

# Default headers
DEFAULT_HEADERS = {
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.5",
    "Accept-Encoding": "gzip, deflate, br",
    "Connection": "keep-alive",
    "Upgrade-Insecure-Requests": "1"
}

# Output settings
OUTPUT_DIR = "testing/output"
