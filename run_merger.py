#!/usr/bin/env python
import sys
import os
import json
from pathlib import Path

# Add the core directory to the path
sys.path.insert(0, str(Path(__file__).parent))

from core.data_merger import load_stock_data

# Compile check
try:
    import py_compile
    py_compile.compile('core/data_merger.py', doraise=True)
    print("✓ Compilation successful")
except py_compile.PyCompileError as e:
    print(f"✗ Compilation error: {e}")
    sys.exit(1)

# Run IAM and CIH
for symbol in ['IAM', 'CIH']:
    try:
        print(f"\n📊 Processing {symbol}...")
        data = load_stock_data(symbol, verbose=True)
        
        # Save merged output
        output_file = Path('data/historical') / f"{symbol}_merged.json"
        with open(output_file, 'w') as f:
            json.dump(data, f, indent=2)
        print(f"✓ Saved to: {output_file}")
    except Exception as e:
        print(f"✗ Error processing {symbol}: {e}")
        import traceback
        traceback.print_exc()

# Now read and report the specific fields
print("\n" + "="*80)
print("MERGED DATA REPORT")
print("="*80)

fields_to_report = ['price', 'market_cap', 'volume', 'high_52w', 'low_52w', 'price_to_book', 'consensus', 'num_analysts']

for symbol in ['IAM', 'CIH']:
    merged_file = Path('data/historical') / f"{symbol}_merged.json"
    
    if not merged_file.exists():
        print(f"\n❌ {symbol}_merged.json not found")
        continue
    
    with open(merged_file, 'r') as f:
        data = json.load(f)
    
    print(f"\n📋 {symbol}:")
    print("-" * 60)
    
    for field in fields_to_report:
        value = data.get(field)
        print(f"  {field:20s}: {value}")
