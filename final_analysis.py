#!/usr/bin/env python3
"""
Final CSV Analysis - outputs ALL results to stdout
Run with: python final_analysis.py
"""

import csv
import os
from urllib.parse import urlparse
from collections import defaultdict
import sys

os.chdir('C:\\Users\\arhou\\OneDrive\\Bureau\\PFE.0')

csv_file = "data/historical/ATW_news.csv"

print("="*100)
print("ATW NEWS CSV ANALYSIS - FINAL RESULTS")
print("="*100)

# Read CSV and count rows
rows = []
with open(csv_file, 'r', encoding='utf-8', errors='ignore') as f:
    reader = csv.DictReader(f)
    for row in reader:
        rows.append(row)

print(f"\n[1] TOTAL DATA ROWS: {len(rows)}")

# Get columns from first row if exists
if rows:
    columns = list(rows[0].keys())
    print(f"\n[2] COLUMNS ({len(columns)}):")
    for i, col in enumerate(columns, 1):
        print(f"    {i}. {col}")

# Noise pattern matching
noise_patterns = ['bebee', 'instagram', 'focus pme', 'egypt', 'egypte', 'égypte', 'cairo', 'le caire']
noise_matches = []
cols_to_check = ['title', 'source', 'url', 'snippet']

print(f"\n[3] NOISE PATTERN MATCHING")
print(f"    Patterns: {', '.join(noise_patterns)}")
print(f"    Checking columns: {cols_to_check}")

for idx, row in enumerate(rows):
    row_text = ' '.join([str(row.get(c, '')).lower() for c in cols_to_check])
    for pattern in noise_patterns:
        if pattern.lower() in row_text:
            noise_matches.append(idx)
            break

print(f"    RESULT: {len(noise_matches)} rows match")

# Google News RSS
print(f"\n[4] GOOGLE NEWS RSS ARTICLES")
google_rss_matches = []
for idx, row in enumerate(rows):
    url = row.get('url', '')
    if 'news.google.com/rss/articles/' in url.lower():
        google_rss_matches.append(idx)

print(f"    RESULT: {len(google_rss_matches)} rows have 'news.google.com/rss/articles/' URLs")

# Canonical URL duplicates
print(f"\n[5] DUPLICATE CANONICAL URLS")
print(f"    (Strip tracking query params, normalize host/path)")

def normalize_url(url):
    if not url:
        return ''
    try:
        parsed = urlparse(url)
        clean_netloc = parsed.netloc.lower().replace('www.', '')
        return f"{clean_netloc}{parsed.path}"
    except:
        return url

canonical_map = defaultdict(list)
for idx, row in enumerate(rows):
    url = row.get('url', '')
    canonical = normalize_url(url)
    if canonical:
        canonical_map[canonical].append(idx)

dup_urls_count = sum(1 for v in canonical_map.values() if len(v) > 1)
dup_urls_instances = sum(len(v) for v in canonical_map.values() if len(v) > 1)

print(f"    - Unique canonical URLs with duplicates: {dup_urls_count}")
print(f"    - Total instances of duplicated URLs: {dup_urls_instances}")

# (date[:10], normalized_title) duplicates
print(f"\n[6] DUPLICATE (DATE[:10], NORMALIZED_TITLE) PAIRS")

def normalize_title(title):
    if not title:
        return ''
    return ' '.join(str(title).lower().split())

date_title_map = defaultdict(list)
for idx, row in enumerate(rows):
    date_str = row.get('date', '')
    title_str = row.get('title', '')
    date_key = date_str[:10] if date_str else ''
    title_key = normalize_title(title_str)
    key = (date_key, title_key)
    date_title_map[key].append(idx)

dup_pairs_count = sum(1 for v in date_title_map.values() if len(v) > 1)
dup_pairs_instances = sum(len(v) for v in date_title_map.values() if len(v) > 1)

print(f"    - Unique pairs with duplicates: {dup_pairs_count}")
print(f"    - Total instances of duplicated pairs: {dup_pairs_instances}")

# First 10 rows
print(f"\n[7] FIRST 10 ROWS (date, title, source, url, signal_score, is_atw_core)")
print("-"*150)

display_cols = ['date', 'title', 'source', 'url', 'signal_score', 'is_atw_core']

for i, row in enumerate(rows[:10]):
    print(f"\n  ROW {i}:")
    for col in display_cols:
        val = row.get(col, 'N/A')
        # Truncate long values
        if len(str(val)) > 80:
            val = str(val)[:77] + "..."
        print(f"    {col}: {val}")

print("\n" + "="*100)
print("ANALYSIS COMPLETE")
print("="*100)

print("\n\nSUMMARY OF COUNTS:")
print(f"  Total rows: {len(rows)}")
print(f"  Noise pattern matches: {len(noise_matches)}")
print(f"  Google News RSS URLs: {len(google_rss_matches)}")
print(f"  Duplicate canonical URLs: {dup_urls_count} unique, {dup_urls_instances} instances")
print(f"  Duplicate (date, title) pairs: {dup_pairs_count} unique, {dup_pairs_instances} instances")
