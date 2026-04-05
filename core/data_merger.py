"""
Hybrid Data Loader - Uses Best Available Source
================================================
Combines data from:
1. V2 Scraper (reliable historical financials)
2. Old stock_data.json (has valuation ratios the V2 scraper misses)

This gives you COMPLETE, CLEAN data for AI predictions.

Usage:
    from data_merger import load_stock_data
    data = load_stock_data("IAM")
"""

import json
from pathlib import Path
from typing import Dict, Any, Optional
from datetime import datetime

# Paths
_ROOT = Path(__file__).resolve().parent.parent
OLD_DATA = _ROOT / "testing" / "testing" / "stock_data.json"
V2_DATA_DIR = _ROOT / "data" / "historical"

def load_old_data(symbol: str) -> Optional[Dict[str, Any]]:
    """Load data from the old stock_data.json."""
    try:
        with open(OLD_DATA, 'r') as f:
            data = json.load(f)
        
        for stock in data.get('stocks', []):
            if stock['identity']['ticker'] == symbol:
                return stock
        return None
    except FileNotFoundError:
        return None

def load_v2_data(symbol: str) -> Optional[Dict[str, Any]]:
    """Load data from V2 scraper output."""
    v2_file = V2_DATA_DIR / f"{symbol}_marketscreener_v2.json"
    try:
        with open(v2_file, 'r') as f:
            return json.load(f)
    except FileNotFoundError:
        return None

def merge_stock_data(symbol: str) -> Dict[str, Any]:
    """
    Merge data from both sources, taking the best from each.
    
    Priority:
    - Price: V2 (more recent)
    - Market Cap, P/E, Div Yield: Old data (V2 struggles with these)
    - Historical Financials: V2 (more complete)
    """
    old = load_old_data(symbol)
    v2 = load_v2_data(symbol)
    
    if not v2 and not old:
        raise FileNotFoundError(f"No data found for {symbol}")
    
    # Start with V2 data (has better historical)
    merged = v2.copy() if v2 else {"symbol": symbol}
    
    # Fill in missing fields from old data
    if old:
        valuation = old.get('valuation', {})
        price_perf = old.get('price_performance', {})
        
        # Only use old data if V2 doesn't have it
        if not merged.get('market_cap') and valuation.get('market_cap'):
            merged['market_cap'] = valuation['market_cap']
        
        if not merged.get('pe_ratio') and valuation.get('pe_ratio'):
            merged['pe_ratio'] = valuation['pe_ratio']
        
        if not merged.get('dividend_yield') and valuation.get('dividend_yield'):
            merged['dividend_yield'] = valuation['dividend_yield']
        
        if not merged.get('high_52w') and price_perf.get('high_52w'):
            merged['high_52w'] = price_perf['high_52w']
        
        if not merged.get('low_52w') and price_perf.get('low_52w'):
            merged['low_52w'] = price_perf['low_52w']
        
        # Consensus from old data
        consensus_data = old.get('consensus', {})
        if not merged.get('consensus') and consensus_data.get('consensus'):
            merged['consensus'] = consensus_data['consensus']
        
        if not merged.get('target_price') and consensus_data.get('target_price_avg'):
            merged['target_price'] = consensus_data['target_price_avg']
    
    # Add metadata
    merged['data_source'] = {
        'v2_scraper': bool(v2),
        'old_data': bool(old),
        'merged_at': datetime.utcnow().isoformat() + "Z"
    }
    
    return merged

def get_data_quality(data: Dict[str, Any]) -> Dict[str, Any]:
    """Calculate data quality metrics."""
    required_fields = [
        'price', 'market_cap', 'pe_ratio', 'dividend_yield',
        'hist_revenue', 'hist_net_income', 'hist_eps'
    ]
    
    filled = sum(1 for field in required_fields if data.get(field))
    quality_pct = (filled / len(required_fields)) * 100
    
    # Check historical data completeness
    hist_years = {
        'revenue': len(data.get('hist_revenue', {})),
        'net_income': len(data.get('hist_net_income', {})),
        'eps': len(data.get('hist_eps', {})),
        'fcf': len(data.get('hist_fcf', {})),
    }
    
    return {
        'quality_pct': quality_pct,
        'filled_fields': filled,
        'total_fields': len(required_fields),
        'historical_years': hist_years,
        'is_sufficient': quality_pct >= 70 and all(y >= 3 for y in hist_years.values())
    }

def load_stock_data(symbol: str, verbose: bool = True) -> Dict[str, Any]:
    """
    Load and merge stock data from all sources.
    
    Args:
        symbol: Stock symbol (e.g., 'IAM')
        verbose: Print data quality summary
    
    Returns:
        Merged stock data dictionary
    """
    data = merge_stock_data(symbol)
    quality = get_data_quality(data)
    
    if verbose:
        print(f"\n📊 {symbol} Data Summary:")
        print(f"   Quality: {quality['quality_pct']:.0f}% ({quality['filled_fields']}/{quality['total_fields']} fields)")
        print(f"   Historical Data:")
        for metric, years in quality['historical_years'].items():
            print(f"      {metric}: {years} years")
        
        status = "✅ SUFFICIENT" if quality['is_sufficient'] else "⚠️  INSUFFICIENT"
        print(f"   Status: {status} for AI predictions")
        
        sources = data['data_source']
        if sources['v2_scraper'] and sources['old_data']:
            print(f"   Source: Hybrid (V2 + old data)")
        elif sources['v2_scraper']:
            print(f"   Source: V2 scraper only")
        else:
            print(f"   Source: Old data only")
    
    return data

# CLI interface
if __name__ == "__main__":
    import sys
    
    if len(sys.argv) < 2:
        print("Usage: python data_merger.py <SYMBOL>")
        print("Example: python data_merger.py IAM")
        sys.exit(1)
    
    symbol = sys.argv[1].upper()
    
    try:
        data = load_stock_data(symbol, verbose=True)
        
        # Save merged output
        output_file = V2_DATA_DIR / f"{symbol}_merged.json"
        with open(output_file, 'w') as f:
            json.dump(data, f, indent=2)
        
        print(f"\n💾 Saved to: {output_file}")
        
    except FileNotFoundError as e:
        print(f"❌ Error: {e}")
        sys.exit(1)
