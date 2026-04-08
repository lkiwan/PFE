"""Test the wired pipeline to verify all components work together."""

import sys
import logging
from pathlib import Path

_ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(_ROOT))

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(levelname)s: %(message)s'
)

from agents.tools import get_iam_stock_advisory_context

def main():
    print("="*70)
    print("TESTING WIRED PIPELINE - REAL DATA INTEGRATION")
    print("="*70)
    
    try:
        context_json = get_iam_stock_advisory_context()
        
        print("\n" + "="*70)
        print("✅ SUCCESS - Pipeline generated context:")
        print("="*70)
        print(context_json)
        
        # Parse and validate
        import json
        context = json.loads(context_json)
        
        print("\n" + "="*70)
        print("VALIDATION:")
        print("="*70)
        
        checks = [
            ("Stock ticker", context.get("stock", {}).get("ticker") == "IAM"),
            ("Current price > 0", context.get("stock", {}).get("current_price", 0) > 0),
            ("Intrinsic value calculated", context.get("fundamental_valuation", {}).get("calculated_intrinsic_value", 0) > 0),
            ("Composite score present", "composite_overall" in context.get("health_scores_out_of_100", {})),
            ("Whale data present", "whale_activity_today" in context.get("technical_and_whale_data", {})),
            ("Sentiment data present", "sentiment" in context.get("recent_news_sentiment", {})),
        ]
        
        for check_name, result in checks:
            status = "✅" if result else "❌"
            print(f"  {status} {check_name}")
        
        all_passed = all(result for _, result in checks)
        
        if all_passed:
            print("\n🎉 ALL CHECKS PASSED - Pipeline is fully wired!")
        else:
            print("\n⚠️  Some checks failed - review above")
        
        return 0 if all_passed else 1
        
    except Exception as e:
        print(f"\n❌ PIPELINE FAILED: {e}")
        import traceback
        traceback.print_exc()
        return 1

if __name__ == "__main__":
    exit(main())
