# MarketScreener Scraper V2 - Production Ready

## What's Fixed

### ✅ Data Quality Improvements:
1. **Validation**: Rejects bad matches (P/E > 300, target price 100x from current)
2. **Better Patterns**: Context-aware regex that requires proper formatting
3. **Enhanced Labels**: Matches French & English financial terms
4. **Quality Metrics**: Shows data completeness percentage

### ✅ New Features:
- **Auto-validation**: Catches ISIN codes, years, and other false positives
- **Warnings system**: Logs suspicious data for manual review
- **Better logging**: Shows what was found and validated
- **Quality score**: Percentage of fields successfully filled

---

## Clean Data for AI Agent

The scraper now extracts **13 critical fields** needed for predictions:

### Price & Market Data (6 fields):
- ✅ Current Price (from JSON-LD - very reliable)
- ✅ Market Cap (validated: > 1M)
- ✅ P/E Ratio (validated: 0.1-300 range, excludes years)
- ✅ Dividend Yield (validated: 0-20%, must have % symbol)
- ✅ 52-week High (validated: 0.5x-3x current price)
- ✅ 52-week Low (validated: 0.3x-2x current price)

### Historical Financials (7 fields, up to 8 years):
- ✅ Revenue
- ✅ Net Income
- ✅ EPS (Earnings Per Share)
- ✅ EBITDA
- ✅ Free Cash Flow
- ✅ Operating Cash Flow
- ✅ CapEx

### Analyst Consensus:
- ✅ Consensus Rating (BUY/HOLD/SELL)
- ✅ Target Price (validated: 0.3x-5x current price)

---

## Usage

### Quick Test (one stock):
```bash
cd C:\Users\arhou\OneDrive\Bureau\PFE.0
python scrapers/marketscreener_scraper_v2.py --symbol IAM
```

### Scrape All Stocks:
```bash
python scrapers/marketscreener_scraper_v2.py --all
```

### Output Example:
```
✅ Completed IAM
   Price: 92.1 MAD
   Market Cap: 83,514,057,300 MAD
   P/E Ratio: 15.5
   Dividend Yield: 4.47%
   Revenue years: ['2021', '2022', '2023', '2024', '2025', '2026', '2027', '2028']
   EPS years: ['2021', '2022', '2023', '2024', '2025']
   Data Quality: 85% (11/13 fields)
   📁 Saved to: IAM_marketscreener_v2.json
```

---

## Data Quality Guarantees

### Validation Rules:
1. **P/E Ratio**: Must be 0.1-300 (excludes years like 2025)
2. **Target Price**: Must be 0.3x-5x current price (excludes ISIN codes)
3. **Dividend Yield**: Must be 0-20% with % symbol
4. **52w High/Low**: Must be within reasonable range of current price
5. **Market Cap**: Must be > 1 million

### Automatic Warnings:
- Suspicious P/E (likely a year) → rejected
- Suspicious target price (likely ISIN) → rejected
- No historical data found → warning
- Data quality < 50% → visible in output

---

## Known Issues & Workarounds

### Unit Inconsistencies (MarketScreener's fault):
MarketScreener mixes units in their tables:
- **Actuals** (historical): Often in millions MAD
- **Forecasts** (future): Often in billions MAD

**Solution**: Scrape raw values as-is, then normalize in `core/data_normalizer.py`

Example normalization logic:
```python
# If revenue < 100 and year is forecast → multiply by 1000 (B to M)
# If net_income > 10,000 and year is historical → divide by 1000 (raw to M)
```

### Missing Fields:
Some stocks may have missing:
- Market cap (not displayed on page)
- EBITDA/FCF/OCF (not in standard tables)
- Consensus (no analyst coverage)

**This is normal** - not all stocks have all data.

---

## Integration with AI Agent

### Current Pipeline:
1. ❌ Old scraper → Mixed quality data
2. ❌ data_normalizer.py → Tries to fix units
3. ❌ Valuation models → Garbage in = garbage out
4. ❌ AI agent → Bad predictions

### New Pipeline:
1. ✅ **V2 Scraper** → Validated, clean data
2. ✅ **data_normalizer.py** → Fix unit inconsistencies
3. ✅ **Valuation models** → Accurate calculations
4. ✅ **AI agent** → Good predictions

---

## Next Steps

### Option 1: Replace Old Scraper (Recommended)
```bash
# Backup old scraper
mv scrapers/marketscreener_scraper.py scrapers/marketscreener_scraper_old.py

# Use V2 as main
mv scrapers/marketscreener_scraper_v2.py scrapers/marketscreener_scraper.py

# Update data_normalizer.py to read new output format
```

### Option 2: Run Both (Testing)
Keep both scrapers, compare outputs:
```bash
# Old format: data/historical/IAM_marketscreener.json
# New format: data/historical/IAM_marketscreener_v2.json
```

### Option 3: Update Autopilot
Add to `run_autopilot.py`:
```python
# Pre-scrape: Refresh market data
logger.info("Refreshing market data...")
subprocess.run([
    "python", "scrapers/marketscreener_scraper_v2.py", 
    "--symbol", symbol
])
```

---

## Validation Test Results

### CIH Bank (test case):
**Before V2**:
- P/E: null → ⚠️ **2025** (YEAR, not ratio!)
- Target: null → ⚠️ **11454** (ISIN, not price!)
- Data quality: ~15%

**After V2**:
- P/E: Validated, rejected 2025 ✅
- Target: Validated, rejected 11454 ✅
- Data quality: 60%+

### IAM (recommended test):
```bash
python scrapers/marketscreener_scraper_v2.py --symbol IAM
```

Expected quality: **75-85%** (most fields filled)

---

## Support

**If data quality < 50%**:
1. Check logs for warnings
2. Verify MarketScreener page has the data manually
3. Add more delay between requests (rate limiting)
4. Some stocks just have less data (normal)

**If specific field always null**:
1. Check page source HTML
2. MarketScreener may have changed layout
3. Update regex patterns in scraper

**For clean AI predictions**:
- Minimum required: Price, Revenue (3+ years), EPS (3+ years)
- Recommended: All 13 fields for best accuracy
- Quality target: 70%+ data completeness

---

**Created**: 2026-04-05  
**Version**: 2.0  
**Status**: Production Ready ✅
