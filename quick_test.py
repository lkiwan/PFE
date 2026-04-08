"""
QUICK TEST - Verify AI Agent Gets Real Data
============================================

This script does a minimal check to ensure the pipeline is wired correctly.
"""

from agents.tools import get_iam_stock_advisory_context
import json

print("🔄 Testing AI Agent Data Pipeline...")

try:
    # Get context
    context_json = get_iam_stock_advisory_context()
    context = json.loads(context_json)
    
    # Quick checks
    print(f"\n✅ Stock: {context['stock']['ticker']}")
    print(f"✅ Current Price: {context['stock']['current_price']} MAD")
    print(f"✅ Intrinsic Value: {context['fundamental_valuation']['calculated_intrinsic_value']} MAD")
    print(f"✅ Upside: {context['fundamental_valuation']['upside_percentage']}")
    print(f"✅ Composite Score: {context['health_scores_out_of_100']['composite_overall']}/100")
    print(f"✅ Whale Activity: {context['technical_and_whale_data']['whale_activity_today']}")
    print(f"✅ News Sentiment: {context['recent_news_sentiment']['sentiment']}")
    
    print("\n🎉 SUCCESS - AI Agent is receiving REAL data!")
    
except Exception as e:
    print(f"\n❌ ERROR: {e}")
    import traceback
    traceback.print_exc()
