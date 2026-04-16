#!/usr/bin/env python3
"""
Quick syntax validation for the updated scrapers.
"""

import sys
import ast

print("=" * 70)
print("SYNTAX VALIDATION FOR SCRAPERS")
print("=" * 70)

files_to_check = [
    ('testing/run_scraper.py', 'testing/run_scraper.py'),
    ('scrapers/atw_news_scraper.py', 'scrapers/atw_news_scraper.py'),
]

all_ok = True

for label, filepath in files_to_check:
    print(f"\nChecking {label}...")
    try:
        with open(filepath, 'r', encoding='utf-8') as f:
            code = f.read()
        ast.parse(code)
        print(f"  ✓ Syntax valid")
    except SyntaxError as e:
        print(f"  ✗ Syntax error at line {e.lineno}: {e.msg}")
        all_ok = False
    except Exception as e:
        print(f"  ✗ Error: {e}")
        all_ok = False

print("\n" + "=" * 70)
if all_ok:
    print("✓ All files have valid Python syntax!")
    print("\nYou can now run:")
    print("  python scrapers/atw_news_scraper.py")
    print("  python testing/run_scraper.py --symbol ATW")
else:
    print("✗ Some files have syntax errors. Please review above.")
    sys.exit(1)

print("=" * 70)
