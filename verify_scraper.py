#!/usr/bin/env python3
"""
Verify ATW news scraper CSV output with detailed analysis
"""
import subprocess
import sys
import os
import pandas as pd
from urllib.parse import urlparse, parse_qs
from collections import defaultdict
import re

# Step 1: Run the backfill command
print("=" * 80)
print("STEP 1: Running backfill scraper...")
print("=" * 80)

result = subprocess.run(
    [sys.executable, "scrapers/atw_news_scraper.py", "--backfill-existing", "--out", "data/historical/ATW_news.csv"],
    cwd="C:\\Users\\arhou\\OneDrive\\Bureau\\PFE.0",
    capture_output=True,
    text=True
)

print(result.stdout)
if result.stderr:
    print("STDERR:", result.stderr)
print(f"Return code: {result.returncode}\n")

# Step 2: Verify CSV
print("=" * 80)
print("STEP 2: Verifying CSV output...")
print("=" * 80)

csv_path = "C:\\Users\\arhou\\OneDrive\\Bureau\\PFE.0\\data\\historical\\ATW_news.csv"

if not os.path.exists(csv_path):
    print(f"ERROR: CSV file not found at {csv_path}")
    sys.exit(1)

# Load the CSV
df = pd.read_csv(csv_path)
print(f"\n✓ CSV loaded successfully")

# Row count
row_count = len(df)
print(f"\n1. Row count: {row_count}")

# Columns
print(f"\n2. Columns: {list(df.columns)}")

# Noise pattern matching
noise_patterns = ['bebee', 'instagram', 'focus pme', 'egypt', 'egypte', 'égypte', 'cairo', 'le caire']
noise_count = 0
cols_to_check = ['title', 'source', 'url', 'snippet']
cols_existing = [c for c in cols_to_check if c in df.columns]

for idx, row in df.iterrows():
    row_text = ' '.join([str(row.get(c, '')).lower() for c in cols_existing])
    for pattern in noise_patterns:
        if pattern.lower() in row_text:
            noise_count += 1
            break  # Count each row only once

print(f"\n3. Rows matching noise patterns: {noise_count}")
print(f"   (Patterns: {', '.join(noise_patterns)})")

# Google News RSS URLs
google_rss_count = 0
if 'url' in df.columns:
    google_rss_count = df['url'].str.contains('news.google.com/rss/articles/', na=False, case=False).sum()
    
print(f"\n4. Rows with news.google.com/rss/articles/ URLs: {google_rss_count}")

# Duplicates by canonical URL
def normalize_url(url):
    """Normalize URL by stripping tracking params and fragments"""
    if pd.isna(url):
        return ''
    parsed = urlparse(str(url))
    # Remove tracking parameters
    clean_path = parsed.path
    clean_netloc = parsed.netloc.lower().replace('www.', '')
    return f"{clean_netloc}{clean_path}"

canonical_duplicates = defaultdict(int)
if 'url' in df.columns:
    for url in df['url']:
        canonical = normalize_url(url)
        if canonical:
            canonical_duplicates[canonical] += 1

dup_canonical_count = sum(1 for count in canonical_duplicates.values() if count > 1)
print(f"\n5. Duplicate canonical URLs (count of URLs with duplicates): {dup_canonical_count}")
print(f"   Total canonical URL instances with duplicates: {sum(count for count in canonical_duplicates.values() if count > 1)}")

# Duplicates by (date[:10], normalized_title)
def normalize_title(title):
    """Normalize title: strip extra spaces and lowercase"""
    if pd.isna(title):
        return ''
    return ' '.join(str(title).lower().split())

date_title_dupes = defaultdict(int)
if 'date' in df.columns and 'title' in df.columns:
    for idx, row in df.iterrows():
        date_key = str(row['date'])[:10]
        title_key = normalize_title(row['title'])
        composite_key = (date_key, title_key)
        date_title_dupes[composite_key] += 1

dup_date_title_count = sum(1 for count in date_title_dupes.values() if count > 1)
print(f"\n6. Duplicate (date[:10], normalized_title) pairs: {dup_date_title_count}")
print(f"   Total instances with duplicates: {sum(count for count in date_title_dupes.values() if count > 1)}")

# First 10 rows
print(f"\n7. First 10 rows (date, title, source, url, signal_score, is_atw_core):")
print("-" * 150)

display_cols = ['date', 'title', 'source', 'url', 'signal_score', 'is_atw_core']
display_cols = [c for c in display_cols if c in df.columns]

if len(display_cols) > 0:
    display_df = df[display_cols].head(10).copy()
    # Format for readability
    pd.set_option('display.max_colwidth', 50)
    pd.set_option('display.max_columns', None)
    pd.set_option('display.width', None)
    print(display_df.to_string(index=False))
else:
    print("WARNING: Display columns not found in CSV")
    print(df.head(10).to_string())

print("\n" + "=" * 80)
print("VERIFICATION COMPLETE")
print("=" * 80)
