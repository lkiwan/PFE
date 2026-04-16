#!/usr/bin/env python3
"""
Direct analysis of ATW news CSV without subprocess - inline execution
"""

import os
os.chdir('C:\\Users\\arhou\\OneDrive\\Bureau\\PFE.0')

# First, let's try to import pandas and analyze
try:
    import pandas as pd
except ImportError:
    print("ERROR: pandas not installed")
    exit(1)

from urllib.parse import urlparse
from collections import defaultdict

csv_path = "data/historical/ATW_news.csv"

print("=" * 80)
print("ATW NEWS SCRAPER CSV ANALYSIS")
print("=" * 80)

# Load CSV
try:
    df = pd.read_csv(csv_path)
    print(f"\n✓ CSV loaded successfully from {csv_path}")
except Exception as e:
    print(f"ERROR loading CSV: {e}")
    exit(1)

# 1. Row count
row_count = len(df)
print(f"\n1. TOTAL ROW COUNT: {row_count}")

# 2. Columns
print(f"\n2. COLUMNS: {list(df.columns)}")

# 3. Noise pattern matching
noise_patterns = ['bebee', 'instagram', 'focus pme', 'egypt', 'egypte', 'égypte', 'cairo', 'le caire']
noise_count = 0
cols_to_check = ['title', 'source', 'url', 'snippet']
cols_existing = [c for c in cols_to_check if c in df.columns]

print(f"\n3. NOISE PATTERN MATCHING:")
print(f"   Checking columns: {cols_existing}")
print(f"   Patterns: {', '.join(noise_patterns)}")

for idx, row in df.iterrows():
    row_text = ' '.join([str(row.get(c, '')).lower() for c in cols_existing])
    for pattern in noise_patterns:
        if pattern.lower() in row_text:
            noise_count += 1
            break

print(f"   ✓ Rows with noise patterns: {noise_count}")

# 4. Google News RSS URLs
google_rss_count = 0
if 'url' in df.columns:
    google_rss_count = df['url'].str.contains('news.google.com/rss/articles/', na=False, case=False).sum()
    
print(f"\n4. GOOGLE NEWS RSS ARTICLES:")
print(f"   Rows with 'news.google.com/rss/articles/' in URL: {google_rss_count}")

# 5. Duplicates by canonical URL
def normalize_url(url):
    if pd.isna(url):
        return ''
    parsed = urlparse(str(url))
    clean_netloc = parsed.netloc.lower().replace('www.', '')
    clean_path = parsed.path
    return f"{clean_netloc}{clean_path}"

canonical_map = defaultdict(list)
if 'url' in df.columns:
    for idx, url in enumerate(df['url']):
        canonical = normalize_url(url)
        if canonical:
            canonical_map[canonical].append(idx)

dup_canonical_urls = sum(1 for indices in canonical_map.values() if len(indices) > 1)
dup_canonical_instances = sum(len(indices) for indices in canonical_map.values() if len(indices) > 1)

print(f"\n5. DUPLICATE CANONICAL URLS:")
print(f"   (Strip tracking query params and fragments, normalize host/path)")
print(f"   - Unique canonical URLs with duplicates: {dup_canonical_urls}")
print(f"   - Total instances of duplicated URLs: {dup_canonical_instances}")

# 6. Duplicates by (date[:10], normalized_title)
def normalize_title(title):
    if pd.isna(title):
        return ''
    return ' '.join(str(title).lower().split())

date_title_map = defaultdict(list)
if 'date' in df.columns and 'title' in df.columns:
    for idx, row in df.iterrows():
        date_key = str(row['date'])[:10] if pd.notna(row['date']) else ''
        title_key = normalize_title(row['title'])
        composite_key = (date_key, title_key)
        date_title_map[composite_key].append(idx)

dup_date_title_pairs = sum(1 for indices in date_title_map.values() if len(indices) > 1)
dup_date_title_instances = sum(len(indices) for indices in date_title_map.values() if len(indices) > 1)

print(f"\n6. DUPLICATE (DATE[:10], NORMALIZED_TITLE) PAIRS:")
print(f"   - Unique pairs with duplicates: {dup_date_title_pairs}")
print(f"   - Total instances of duplicated pairs: {dup_date_title_instances}")

# 7. First 10 rows
print(f"\n7. FIRST 10 ROWS (selected columns):")
print("-" * 180)

display_cols = ['date', 'title', 'source', 'url', 'signal_score', 'is_atw_core']
missing_cols = [c for c in display_cols if c not in df.columns]

if missing_cols:
    print(f"\nWARNING: Missing columns: {missing_cols}")
    display_cols = [c for c in display_cols if c in df.columns]

if len(display_cols) > 0:
    pd.set_option('display.max_colwidth', 60)
    pd.set_option('display.max_columns', None)
    pd.set_option('display.width', 200)
    pd.set_option('display.max_rows', None)
    
    print("\nIndex  |  Date  |  Title  |  Source  |  URL  |  Signal Score  |  ATW Core")
    print("-" * 180)
    for i, row in df[display_cols].head(10).iterrows():
        print(f"{i:<6} | {str(row.get('date', ''))[:19]:<19} | {str(row.get('title', ''))[:40]:<40} | {str(row.get('source', ''))[:15]:<15} | {str(row.get('url', ''))[:50]:<50} | {str(row.get('signal_score', '')):<14} | {str(row.get('is_atw_core', '')):<8}")

print("\n" + "=" * 80)
print("ANALYSIS COMPLETE")
print("=" * 80)
