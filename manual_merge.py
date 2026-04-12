#!/usr/bin/env python3
"""Manual merge implementation without running full script"""
import json
import csv
from pathlib import Path
from datetime import datetime

def safe_float(value):
    if value in (None, ""):
        return None
    try:
        return float(str(value).replace(" ", "").replace(",", "."))
    except (ValueError, TypeError):
        return None

def get_latest_bourse_data(symbol, csv_path):
    """Extract latest price data from CSV"""
    try:
        with open(csv_path, "r", encoding="utf-8-sig", newline="") as f:
            reader = csv.DictReader(f)
            rows = list(reader)
        
        if not rows:
            return None
        
        # Get the first row (most recent due to reverse chronological order)
        latest_row = rows[0]
        fieldnames = list(reader.fieldnames or [])
        
        # Create case-insensitive header map
        header_map = {h.strip().lower(): h for h in fieldnames if h}
        
        def get_col(*names):
            for name in names:
                col = header_map.get(name.lower())
                if col:
                    return col
            return None
        
        close_col = get_col("Dernier Cours", "close", "courscourant")
        vol_col = get_col("Nombre de titres échangés", "volume", "cumultitresechanges")
        mcap_col = get_col("Capitalisation", "capitalisation", "market_cap")
        high_col = get_col("+haut du jour", "high", "highprice")
        low_col = get_col("+bas du jour", "low", "lowprice")
        
        result = {
            "price": safe_float(latest_row.get(close_col)) if close_col else None,
            "volume": int(safe_float(latest_row.get(vol_col))) if vol_col and safe_float(latest_row.get(vol_col)) else None,
            "market_cap": safe_float(latest_row.get(mcap_col)) if mcap_col else None,
        }
        
        return result
    except Exception as e:
        print(f"Error reading bourse data for {symbol}: {e}")
        return None

# Process IAM
print("=" * 80)
print("PROCESSING IAM")
print("=" * 80)

v3_file = Path("data/historical/IAM_marketscreener_v3.json")
bourse_file = Path("data/historical/IAM_bourse_casa_full.csv")

with open(v3_file) as f:
    iam_v3 = json.load(f)

print(f"V3 data loaded: {iam_v3['symbol']}")
print(f"  price: {iam_v3.get('price')}")
print(f"  market_cap: {iam_v3.get('market_cap')}")
print(f"  volume: {iam_v3.get('volume')}")
print(f"  high_52w: {iam_v3.get('high_52w')}")
print(f"  low_52w: {iam_v3.get('low_52w')}")
print(f"  price_to_book: {iam_v3.get('price_to_book')}")
print(f"  consensus: {iam_v3.get('consensus')}")
print(f"  num_analysts: {iam_v3.get('num_analysts')}")

bourse_data = get_latest_bourse_data("IAM", bourse_file)
print(f"\nBourse data:")
if bourse_data:
    print(f"  price: {bourse_data.get('price')}")
    print(f"  volume: {bourse_data.get('volume')}")
    print(f"  market_cap: {bourse_data.get('market_cap')}")

# Merge data
merged_iam = iam_v3.copy()
merged_iam['data_source'] = {
    'v3_scraper': True,
    'v2_scraper': False,
    'bourse_casa': bool(bourse_data),
    'old_data': False,
    'merged_at': datetime.utcnow().isoformat() + "Z"
}

if bourse_data:
    for field in ["price", "market_cap", "volume", "high_52w", "low_52w"]:
        if not merged_iam.get(field) and bourse_data.get(field) is not None:
            merged_iam[field] = bourse_data[field]

# Save
output_file = Path("data/historical/IAM_merged.json")
with open(output_file, 'w') as f:
    json.dump(merged_iam, f, indent=2)
print(f"\n✓ Saved IAM merged data to {output_file}")

# Process CIH
print("\n" + "=" * 80)
print("PROCESSING CIH")
print("=" * 80)

v3_file = Path("data/historical/CIH_marketscreener_v3.json")
bourse_file = Path("data/historical/CIH_bourse_casa_full.csv")

with open(v3_file) as f:
    cih_v3 = json.load(f)

print(f"V3 data loaded: {cih_v3['symbol']}")
print(f"  price: {cih_v3.get('price')}")
print(f"  market_cap: {cih_v3.get('market_cap')}")
print(f"  volume: {cih_v3.get('volume')}")
print(f"  high_52w: {cih_v3.get('high_52w')}")
print(f"  low_52w: {cih_v3.get('low_52w')}")
print(f"  price_to_book: {cih_v3.get('price_to_book')}")
print(f"  consensus: {cih_v3.get('consensus')}")
print(f"  num_analysts: {cih_v3.get('num_analysts')}")

bourse_data = get_latest_bourse_data("CIH", bourse_file)
print(f"\nBourse data:")
if bourse_data:
    print(f"  price: {bourse_data.get('price')}")
    print(f"  volume: {bourse_data.get('volume')}")
    print(f"  market_cap: {bourse_data.get('market_cap')}")

# Merge data
merged_cih = cih_v3.copy()
merged_cih['data_source'] = {
    'v3_scraper': True,
    'v2_scraper': False,
    'bourse_casa': bool(bourse_data),
    'old_data': False,
    'merged_at': datetime.utcnow().isoformat() + "Z"
}

if bourse_data:
    for field in ["price", "market_cap", "volume", "high_52w", "low_52w"]:
        if not merged_cih.get(field) and bourse_data.get(field) is not None:
            merged_cih[field] = bourse_data[field]

# Save
output_file = Path("data/historical/CIH_merged.json")
with open(output_file, 'w') as f:
    json.dump(merged_cih, f, indent=2)
print(f"\n✓ Saved CIH merged data to {output_file}")

# Report the requested fields
print("\n" + "=" * 80)
print("MERGED DATA REPORT - REQUESTED FIELDS")
print("=" * 80)

fields_to_report = ['price', 'market_cap', 'volume', 'high_52w', 'low_52w', 'price_to_book', 'consensus', 'num_analysts']

for symbol, data in [('IAM', merged_iam), ('CIH', merged_cih)]:
    print(f"\n📋 {symbol}:")
    print("-" * 60)
    for field in fields_to_report:
        value = data.get(field)
        print(f"  {field:20s}: {value}")
