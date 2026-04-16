#!/usr/bin/env python3
"""
Standalone analysis of ATW_news.csv
This file can be run directly with: python inline_analysis.py
"""
import os
import sys

# Change to repo directory
os.chdir('C:\\Users\\arhou\\OneDrive\\Bureau\\PFE.0')
sys.path.insert(0, os.getcwd())

try:
    import pandas as pd
    from urllib.parse import urlparse
    from collections import defaultdict
except ImportError as e:
    print(f"Import error: {e}")
    print("Make sure pandas is installed")
    sys.exit(1)

def main():
    csv_path = "data/historical/ATW_news.csv"
    
    print("=" * 100)
    print("ATW NEWS SCRAPER CSV VERIFICATION & ANALYSIS")
    print("=" * 100)
    
    # Load CSV
    if not os.path.exists(csv_path):
        print(f"ERROR: File not found: {csv_path}")
        return 1
    
    df = pd.read_csv(csv_path)
    print(f"\n✓ CSV loaded successfully")
    print(f"  Location: {csv_path}")
    
    # 1. Row count
    row_count = len(df)
    print(f"\n[1] TOTAL ROW COUNT: {row_count}")
    
    # 2. Columns
    cols = list(df.columns)
    print(f"\n[2] COLUMNS ({len(cols)}): {cols}")
    
    # 3. Noise pattern counting
    noise_patterns = ['bebee', 'instagram', 'focus pme', 'egypt', 'egypte', 'égypte', 'cairo', 'le caire']
    noise_count = 0
    cols_to_check = ['title', 'source', 'url', 'snippet']
    cols_existing = [c for c in cols_to_check if c in cols]
    
    print(f"\n[3] NOISE PATTERN MATCHING")
    print(f"    Patterns: {', '.join(noise_patterns)}")
    print(f"    Checking columns: {cols_existing}")
    
    for idx, row in df.iterrows():
        row_text = ' '.join([str(row.get(c, '')).lower() for c in cols_existing])
        for pattern in noise_patterns:
            if pattern.lower() in row_text:
                noise_count += 1
                break
    
    print(f"    ✓ RESULT: {noise_count} rows match noise patterns")
    
    # 4. Google News RSS URLs
    print(f"\n[4] GOOGLE NEWS RSS ARTICLES")
    google_rss_count = 0
    if 'url' in cols:
        google_rss_count = df['url'].str.contains('news.google.com/rss/articles/', na=False, case=False).sum()
    print(f"    ✓ RESULT: {google_rss_count} rows have 'news.google.com/rss/articles/' URLs")
    
    # 5. Duplicates by canonical URL
    print(f"\n[5] DUPLICATE CANONICAL URLS")
    print(f"    (Strip tracking query params and fragments, normalize host/path)")
    
    def normalize_url(url):
        if pd.isna(url):
            return ''
        parsed = urlparse(str(url))
        clean_netloc = parsed.netloc.lower().replace('www.', '')
        clean_path = parsed.path
        return f"{clean_netloc}{clean_path}"
    
    canonical_map = defaultdict(list)
    if 'url' in cols:
        for idx, url in enumerate(df['url']):
            canonical = normalize_url(url)
            if canonical:
                canonical_map[canonical].append(idx)
    
    dup_canonical_urls = sum(1 for indices in canonical_map.values() if len(indices) > 1)
    dup_canonical_instances = sum(len(indices) for indices in canonical_map.values() if len(indices) > 1)
    
    print(f"    ✓ RESULT:")
    print(f"      - Unique canonical URLs with duplicates: {dup_canonical_urls}")
    print(f"      - Total instances of duplicated URLs: {dup_canonical_instances}")
    
    # 6. Duplicates by (date[:10], normalized_title)
    print(f"\n[6] DUPLICATE (DATE[:10], NORMALIZED_TITLE) PAIRS")
    
    def normalize_title(title):
        if pd.isna(title):
            return ''
        return ' '.join(str(title).lower().split())
    
    date_title_map = defaultdict(list)
    if 'date' in cols and 'title' in cols:
        for idx, row in df.iterrows():
            date_key = str(row['date'])[:10] if pd.notna(row['date']) else ''
            title_key = normalize_title(row['title'])
            composite_key = (date_key, title_key)
            date_title_map[composite_key].append(idx)
    
    dup_date_title_pairs = sum(1 for indices in date_title_map.values() if len(indices) > 1)
    dup_date_title_instances = sum(len(indices) for indices in date_title_map.values() if len(indices) > 1)
    
    print(f"    ✓ RESULT:")
    print(f"      - Unique pairs with duplicates: {dup_date_title_pairs}")
    print(f"      - Total instances of duplicated pairs: {dup_date_title_instances}")
    
    # 7. First 10 rows
    print(f"\n[7] FIRST 10 ROWS")
    print("-" * 200)
    
    display_cols = ['date', 'title', 'source', 'url', 'signal_score', 'is_atw_core']
    available_cols = [c for c in display_cols if c in cols]
    
    if available_cols:
        # Use compact printing
        for i in range(min(10, len(df))):
            row = df.iloc[i]
            print(f"\nRow {i}:")
            for col in available_cols:
                val = str(row.get(col, 'N/A'))[:100]
                print(f"  {col}: {val}")
    
    print("\n" + "=" * 100)
    print("VERIFICATION COMPLETE")
    print("=" * 100)
    
    return 0

if __name__ == '__main__':
    sys.exit(main())
