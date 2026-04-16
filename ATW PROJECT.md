# ATW Project — Handoff Document

**Date of this snapshot:** 2026-04-15 (updated: news scraper dates — MarketScreener `data-utc-date`, article-page date extraction for Boursenews/L'Économiste, IR Attijariwafa + Attijari CIB sources removed, `snippet` column dropped, CSV rows flattened to one-line-per-article)
**Purpose:** anything a fresh Claude session needs to pick up where we left off. Read this before `CLAUDE.md` — `CLAUDE.md` still carries IAM-era content mixed with the pivot note, so this file is the source of truth for the current ATW state.

---

## 1. TL;DR

PFE (thesis) project: quantitative stock advisory for **ATW (Attijariwafa Bank)** on the Casablanca Stock Exchange. Originally built around IAM (Maroc Telecom), fully pivoted to ATW on **2026-04-14**. The IAM version is preserved on branch `v1-iam-archive` (local + GitHub). `main` is now the ATW timeline.

Pipeline in one line:
`scrapers → 5 valuation models + scoring + whale + sentiment → Agno/Groq LLM → PostgreSQL`

All five valuation models, the scoring engine, whale strategy, and sentiment engine are wired and run on real ATW data. The AI agent (`run_autopilot.py`) produces BUY/HOLD/SELL with confidence and a reasoning report.

---

## 2. Pivot context (IAM → ATW)

| Decision | What | Why |
|---|---|---|
| Archive strategy | `git checkout -b v1-iam-archive && git push -u origin v1-iam-archive` | No file duplication; `main` carries ATW only |
| Data discovery | **ATW data already in the repo** before pivot | `data/historical/ATW_*` files existed; no new historical scraping |
| News approach | Free RSS + direct HTML scrapes, **no paid APIs** | Serper/Brave were considered and rejected |
| News scraper | Brand-new `scrapers/atw_news_scraper.py` | MarketScreener per-stock approach replaced for ATW |
| Sector constants | Reworked for Moroccan banking | Banking beta 0.90, 215.14M shares, CAPM cost of equity 9.35% |

The pivot plan (executed): `C:\Users\arhou\.claude\plans\smooth-forging-moth.md`.

---

## 3. Architecture (what feeds what)

```
DATA SOURCES                                                OUTPUT FILES
──────────────────────────────────────────────────────────────────────────────────
scrapers/bourse_casa_scraper.py --symbol ATW     →    data/historical/ATW_bourse_casa_full.csv
  Casablanca Stock Exchange API (OHLCV, 3+ yrs)         (747+ rows)

core/data_merger.py ATW                          →    data/historical/ATW_merged.json
  Combines MS v2/v3 + normalization                     (100% quality fundamentals)

scrapers/atw_news_scraper.py                     →    data/historical/ATW_news.csv
  ┌─ 4 direct page scrapers (high-signal, fast)        (~166 rows)
  │    Medias24 topic + WP REST (tag 8987),              state: data/scrapers/atw_news_state.json
  │    Boursenews stock page,
  │    MarketScreener ATW news,
  │    L'Economiste WordPress search
  └─ Google News RSS (opt-in: --with-gnews / --deep)
                                                      → (fast path: ~25s total)
  IR Attijariwafa + Attijari CIB removed (pages do not expose dates)

scrapers/atw_realtime_scraper.py snapshot        →    data/historical/ATW_intraday_{date}.csv
  Medias24 JSON API (pure requests, no Selenium)         + ATW_orderbook_{date}.csv
  getStockInfo + getTransactions + getBidAsk             state: data/scrapers/atw_realtime_state.json
                                                         (~2s per call, user schedules externally)

scrapers/atw_realtime_scraper.py finalize        →    appends EOD row to ATW_bourse_casa_full.csv
  Consolidates today's intraday → exact 11-col           (idempotent via finalized_days[])
  schema matching bourse_casa output

                        ↓
─────────────────────────────────────────
PROCESSING  (all ticker-agnostic)
─────────────────────────────────────────
• core/data_normalizer.py       → millions MAD
• models/dcf_model.py           → intrinsic value
• models/ddm_model.py           → intrinsic value (banks)
• models/graham_model.py        → intrinsic value
• models/monte_carlo.py         → intrinsic value
• models/relative_valuation.py  → intrinsic value
• strategies/scoring_engine.py  → 5-factor composite
• strategies/whale_strategy.py  → volume spike + SMA trend
• strategies/news_sentiment.py  → FR+EN keyword sentiment

                        ↓
─────────────────────────────────────────
AI AGENT
─────────────────────────────────────────
agents/tools.py             → assembles JSON context
agents/advisor_agent.py     → Agno agent config (Groq llama-3.3-70b)
run_autopilot.py            → entry point, parses response, writes to ai.predictions
```

---

## 4. Files we built / changed during the ATW pivot

### Created

| File | Role |
|---|---|
| `scrapers/atw_news_scraper.py` | **Main deliverable.** RSS + direct HTML scraping, body extraction, strict ISO dates, ticker column |
| `scrapers/atw_realtime_scraper.py` | **Session 2026-04-15.** Intraday snapshots + orderbook via Medias24 JSON API, EOD finalize → bourse_casa CSV schema |
| `data/scrapers/atw_realtime_state.json` | Realtime scraper state (debounce, finalized_days, last-snapshot counters) |
| `data/scrapers/atw_news_state.json` | News scraper state (seen_urls, per_source_last_seen, failed_body_urls, gnews_resolved) |
| `ATW PROJECT.md` (this file) | Handoff doc |

### Rewritten / significantly changed

| File | Change |
|---|---|
| `utils/financial_constants.py` | Banking sector defaults (`STOCK_BETA=0.90`, `NUM_SHARES=215_140_839`, CAPM cost of equity); `IAM_BETA = STOCK_BETA` kept as backward-compat alias |
| `strategies/news_sentiment.py` | Added ~80 French finance words to `POSITIVE_WORDS` / `NEGATIVE_WORDS`; swapped substring matching → token matching (fixes `"ban"` matching inside `"banque"`); French entries in `EVENT_CATEGORIES` |
| `agents/tools.py` | Default symbol `"IAM"` → `"ATW"`; function renamed `get_iam_stock_advisory_context` → `get_atw_stock_advisory_context`; `load_news_data()` reads `{SYMBOL}_news.csv`, renames `title→Title`, `date→Date`, `ticker→Ticker`, prefers `full_content→Full_Content` over `snippet` |
| `agents/advisor_agent.py` | Company-name references IAM/Maroc Telecom → ATW/Attijariwafa Bank |
| `run_autopilot.py` | Default `--symbol ATW` |
| `CLAUDE.md` | Pivot note added at the top (body still IAM-leaning — treat this doc as primary) |

### Untouched (already ticker-agnostic)

All five valuation models, `scoring_engine.py`, `recommendation_engine.py`, `whale_strategy.py`, and `bourse_casa_scraper.py` — they take the ticker as input. No changes needed.

---

## 5. The news scraper in detail (`scrapers/atw_news_scraper.py`)

### Sources

**4 direct scrapers** (high-signal, ATW-specific hubs). IR Attijariwafa and Attijari CIB were removed on 2026-04-15: their article pages render dates client-side, so every row from them was dateless.

| Function | URL | Date source |
|---|---|---|
| `scrape_medias24_topic()` + `scrape_medias24_wp_posts()` | https://medias24.com/sujet/attijariwafa-bank/ + WP REST tag 8987 | Listing / JSON `date` |
| `scrape_boursenews_stock()` | https://boursenews.ma/action/attijariwafa-bank | Article page JSON-LD `datePublished` (French long form, parsed by `_parse_french_date`) |
| `scrape_marketscreener_atw_news()` | https://www.marketscreener.com/quote/stock/ATTIJARIWAFA-BANK-SA-41148801/news/ | Listing `<span class="js-date-relative" data-utc-date="...">` |
| `scrape_leconomiste_search()` | https://www.leconomiste.com/?s=attijariwafa | Article page `<meta property="article:published_time">` |

**Discovery fallback** — `fetch_google_news_rss()` x 3 queries:
- `"Attijariwafa bank" -site:attijariwafa.com -site:attijariwafabank.com` in `MA:fr`
- `"Attijariwafa"` in `MA:fr`
- `"Attijariwafa bank"` in `US:en`

### Key techniques

- **Google News CBMi URLs** — use `googlenewsdecoder` package (`gnewsdecoder(url, interval=1)`). `requests` with `allow_redirects=True` does NOT work because Google News uses a JavaScript redirect, returning HTTP 200 with a redirect page.
- **Body extraction** — `requests.get()` to download (respects our certifi env) + `trafilatura.extract(html, url=url)` to parse. Do NOT use `trafilatura.fetch_url()` — it ignores certifi env vars.
- **SSL on Windows** — must set `REQUESTS_CA_BUNDLE`, `CURL_CA_BUNDLE`, `SSL_CERT_FILE` to `certifi.where()` at import time. The system env `CURL_CA_BUNDLE` points to a nonexistent Postgres path.
- **Blocklist** split in two:
  - `BLOCKED_HOST_SUBSTRINGS` — matched against hostname only (safe for substring like `"attijariwafa"`)
  - `BLOCKED_HOSTPATH_SUBSTRINGS` — matched against `host + first_path_segment` (for things like `google.com/maps`)
  - `WHITELISTED_HOST_SUFFIXES` overrides the blocklist — lets `ir.attijariwafabank.com` and `attijaricib.com` through despite the blanket `"attijariwafa"` block
- **Unresolved Google News guard** — drop any URL still containing `news.google.com` after resolution (decoder failed → unreliable source field)

### Output schema (`data/historical/ATW_news.csv`)

Columns: `date, ticker, title, source, url, full_content, query_source, signal_score, is_atw_core, scraping_date`

> `snippet` was removed on 2026-04-15 — it was always empty for direct scrapers, and `agents/tools.py` already preferred `full_content` so nothing downstream read it. Rows are flattened to one CSV line per article by `_flatten()` (newlines inside bodies collapsed to spaces).

- `date`: strict ISO — `YYYY-MM-DDTHH:MM:SS+00:00` or bare `YYYY-MM-DD`. Empty if landing-page scrape couldn't extract a date (~19 rows).
- `ticker`: always `ATW` currently. Single source of truth in `TICKER = "ATW"` constant.
- `query_source`: tells you which scraper produced the row. Values: `direct:medias24_topic`, `direct:medias24_wp`, `direct:boursenews_stock`, `direct:marketscreener_atw_news`, `direct:leconomiste_search`, `direct:aujourdhui_search`, `google_news:MA:fr`, `google_news:US:en`.
- `signal_score`: integer 0-100 relevance score (keyword-rule based, ATW alpha signal oriented).
- `is_atw_core`: `1` if article is directly about ATW performance/strategy/rating, else `0`.
- `scraping_date`: timestamp (ISO 8601) when the article was processed by the scraper. Helps track data freshness and pipeline runs.
- Noise rows are removed during processing (BeBee, Instagram/Focus PME, Egypt-only coverage).
- Deduplication now keeps one row per canonical URL or `(date, normalized title)` pair to collapse Google News redirect duplicates.

### Exact scraped value names (`atw_news_scraper.py`)

Final CSV fields written (in order):

`date, ticker, title, source, url, full_content, query_source, signal_score, is_atw_core, scraping_date`

- Directly scraped from sources: `date`, `title`, `source`, `url`, `full_content` (when enabled), `query_source`
- Added/derived in pipeline: `ticker`, `signal_score`, `is_atw_core`, `scraping_date`

### CLI

```bash
# Full production run (~15-20 min, includes body fetching)
PYTHONIOENCODING=utf-8 python scrapers/atw_news_scraper.py

# Fast sanity (no bodies, ~3 min)
python scrapers/atw_news_scraper.py --no-bodies

# Limit body fetching to first N (faster partial fill)
python scrapers/atw_news_scraper.py --body-limit 30

# Date filter
python scrapers/atw_news_scraper.py --since 2026-01-01
```

Progress logging every 10 articles during enrichment (added because run looks frozen otherwise).

---

## 6. The sentiment engine in detail (`strategies/news_sentiment.py`)

- **Bilingual vocabulary**: ~200 words across English + French in `POSITIVE_WORDS` / `NEGATIVE_WORDS`. Accented forms (`hausse`, `bénéfice`, `plongé`) kept as-is.
- **Token-based matching**: regex `[a-zàâäéèêëïîôöùûüç]+` extracts whole words; scoring uses `POSITIVE_WORDS & tokens`. This fixed the `"ban"` inside `"banque"` false-positive bug that biased every ATW article negative.
- **Multi-word phrases** in `EVENT_CATEGORIES` still use substring matching (works for `"chiffre d'affaires"`, `"cours cible"`, etc.).
- **Scoring**: base 50, ±15 per net word, capped [0,100]. Overall label: POSITIVE ≥ 65, NEGATIVE ≤ 35, else NEUTRAL.

Before/after on the same CSV: `NEUTRAL 38` → `POSITIVE 73.5`. Events detected grew from just `market` → `earnings, market, regulatory, management, merger_acquisition, dividend, expansion`.

---

## 7. Data state (2026-04-15)

| File | Rows | Status |
|---|---|---|
| `data/historical/ATW_bourse_casa_full.csv` | 748 | Up to 2026-04-15 (includes row finalized from realtime scraper) |
| `data/historical/ATW_merged.json` | - | 100% quality, fundamentals |
| `data/historical/ATW_marketscreener_v3.json` | - | V3 raw |
| `data/historical/ATW_news.csv` | 166 | 100% with date, 100% with `full_content`. One article per CSV line. |
| `data/historical/ATW_intraday_2026-04-15.csv` | - | Realtime snapshots (one row per `snapshot` call) |
| `data/historical/ATW_orderbook_2026-04-15.csv` | - | 5-level bid/ask per snapshot |
| `data/scrapers/atw_news_state.json` | 323 URLs | Incremental state |
| `data/scrapers/atw_realtime_state.json` | - | Debounce + finalized_days |

---

## 8. How to run end-to-end

```bash
# 1. Refresh data (daily)
python scrapers/bourse_casa_scraper.py --symbol ATW       # EOD OHLCV
python core/data_merger.py ATW                             # Fundamentals (weekly is fine)
python scrapers/atw_news_scraper.py                        # News — FAST path, ~25s, no flags

# 1b. Intraday (user schedules externally, ≤15 min cadence, trading hours)
python scrapers/atw_realtime_scraper.py snapshot           # Per-tick snapshot
python scrapers/atw_realtime_scraper.py finalize           # Once after 15:30 Casa — EOD row

# 1c. News with deep enrichment (weekly or on demand)
python scrapers/atw_news_scraper.py --deep                 # Adds gnews + body fetch (~1-2 min warm)

# 2. Smoke tests
python quick_test.py                # company name + price
python test_wired_pipeline.py       # all 5 valuation models + scores

# 3. Full AI prediction (needs GROQ_API_KEY + Postgres)
python run_autopilot.py             # default symbol is ATW
```

Environment requirements:
- Python 3.13
- `.env` with `DATABASE_URL=postgresql://postgres:123456@localhost:5432/PFE` and `GROQ_API_KEY=...`
- Python deps: `feedparser`, `requests`, `beautifulsoup4`, `trafilatura`, `googlenewsdecoder`, `certifi`, `pandas`, `sqlalchemy`, `agno`, `groq`

---

## 9. Gotchas (things that burned us)

1. **Windows SSL error** — system env `CURL_CA_BUNDLE` points to a nonexistent Postgres path, breaking `requests` and `pip`. Fix: `certifi` env override at scraper import; for pip, `unset REQUESTS_CA_BUNDLE CURL_CA_BUNDLE SSL_CERT_FILE PIP_CERT` before install.
2. **Unicode on Windows console** — `cp1252` fails on emoji and some French chars. Prefix Python calls with `PYTHONIOENCODING=utf-8`.
3. **Google News redirect is JavaScript** — not HTTP 302. `requests.get(..., allow_redirects=True)` stays on `news.google.com`. Use `googlenewsdecoder`.
4. **Trafilatura `fetch_url` ignores certifi** — fetch with our `requests` session, pass HTML to `trafilatura.extract(html, url=url)`.
5. **Blocklist substring traps** — `"attijariwafa"` matched article slugs like `press.airarabia.com/...-attijariwafa-bank-...`. Fix: split blocklist into host-only and host+path variants.
6. **Medias24 topic page leaks sidebar** — page renders sitewide recommended links too. Filter on URL slug OR title mentioning Attijariwafa.
7. **Sentiment `"ban"` false positive** — matched inside `"banque"`, biased everything negative. Fixed by token matching.
8. **ISO-8601 with timezone parse** — `strptime` doesn't handle `+00:00` suffix; use `datetime.fromisoformat`. `_parse_date` in `news_sentiment.py` was patched.

---

## 9.5. Session 2026-04-15 — realtime scraper + incremental news state + fast defaults

Three distinct problems tackled, each worth documenting in isolation so the decisions hold up if someone tries to unwind them.

### 9.5.1 Realtime scraper (`scrapers/atw_realtime_scraper.py`)

**Goal:** intraday ATW snapshots at ≤15-min cadence for the autopilot, plus an EOD `finalize` that consolidates the day into one row matching the existing `ATW_bourse_casa_full.csv` schema. Scheduling is external (user runs it via cron / task scheduler / manual loop).

**Initial issue — JS-rendered SPA.** `https://medias24.com/leboursier/fiche-action?action=attijariwafa-bank` is a React-style SPA. `requests.get()` returned an HTML shell with `"Chargement..."` spinners, no data. First plan called for Selenium (reused pattern from `marketscreener_scraper_v3.py`).

**Better solution — found the JSON API.** User hinted *"media24 use wp api"*. Investigation:
- WordPress REST (`/wp-json/wp/v2/...`) only serves editorial content, not market data.
- Read `medias24.com/leboursier/js/api_v4.js` directly — contains `getStockInfo`, `getStockOHLC`, `getBidAsk`, `getTransactions`, `getStockIntraday` routed through `/content/api?method=X&ISIN=...&format=json&t=<ms>`.
- Required header: `Referer: https://medias24.com/leboursier/fiche-action?action=attijariwafa-bank`. Without it, 403.
- ATW ISIN wasn't in `CLAUDE.md` (only CIH + IAM were documented). Recovered by grepping the fiche-action HTML for `MA\d{10}` → `MA0000012445`.

**Outcome:** scraper rewritten to use `requests` directly — no Chrome, no webdriver. Snapshot finishes in ~2s vs. 10-15s via Selenium. Still a single file, clean dependency surface.

**State design** — `data/scrapers/atw_realtime_state.json`:
```json
{
  "last_snapshot_ts": "...",
  "last_snapshot_shares_traded": 103272,
  "last_snapshot_num_trades": 164,
  "finalized_days": ["2026-04-14", "2026-04-15"]
}
```
- 60-second debounce against accidental rapid re-calls
- Stall detection: if counters unchanged + local time > 15:30 Casablanca → replay cached snapshot without hitting the API
- `finalize` is idempotent via `finalized_days[]` — running it twice never duplicates the EOD row

**Verified end-to-end** on 2026-04-15: snapshot → cooldown → finalize → re-finalize. Appended row: `2026-04-15,ATW,ATW,700.2,700.2,709.0,700.2,103272,72311054.0,164,150641615467.8`.

**Exact scraped value names (`atw_realtime_scraper.py`)**

1. Medias24 `getStockInfo` → snapshot values:
   `cotation`, `cours`, `ouverture`, `max`, `min`, `cloture`, `variation`, `volumeTitre`, `volume`, `capitalisation`
2. Medias24 `getTransactions` → used to derive:
   `num_trades` (count of trades)
3. Medias24 `getBidAsk` → orderbook values per level:
   `bidOrder`, `bidQte`, `bidValue`, `askValue`, `askQte`, `askOrder`

Files and written fields:

- `ATW_intraday_{YYYY-MM-DD}.csv`  
  `timestamp, cotation, market_status, last_price, open, high, low, prev_close, variation_pct, shares_traded, value_traded_mad, num_trades, market_cap`
- `ATW_orderbook_{YYYY-MM-DD}.csv`  
  `timestamp` + level-1..5 fields: `bid{i}_orders, bid{i}_qty, bid{i}_price, ask{i}_price, ask{i}_qty, ask{i}_orders`
- `ATW_bourse_casa_full.csv` (on `finalize`)  
  `Séance, Instrument, Ticker, Ouverture, Dernier Cours, +haut du jour, +bas du jour, Nombre de titres échangés, Volume des échanges, Nombre de transactions, Capitalisation`
- `ATW_technicals_{YYYY-MM-DD}.json` (computed from EOD CSV)  
  `as_of_date, last_close, trend, moving_averages, RSI, MACD, bollinger_bands, stochastic, ATR_14, VWAP_20d, support_resistance`

### 9.5.2 Incremental news scraper state

**Issue:** `atw_news_scraper.py` was re-scraping everything every run. ~150 articles × (~2s body fetch + 1s polite delay) = **~10-15 min per run** even when nothing changed. The user had a memory rule already saved (`feedback_incremental_state.md`): *"scrap just new news without spending too much time for the previous ones"*.

**Solution:** `data/scrapers/atw_news_state.json` now tracks:
```json
{
  "seen_urls": {"https://...": "2026-04-13T...", ...},
  "per_source_last_seen": {"direct:medias24_wp": "...", ...},
  "failed_body_urls": [...],
  "gnews_resolved": {"news.google.com/...": "https://..."},
  "last_full_run_ts": "..."
}
```

Three layered caches in `enrich_with_bodies()`:
1. **Body cache reuse** — if URL already in existing CSV with non-empty `full_content`, skip the trafilatura fetch entirely, reuse the cached body.
2. **Failed-URL memory** — if `_fetch_article_body()` previously returned empty (paywall, bot wall, unparseable), URL is added to `failed_body_urls`; subsequent runs skip it. No retry forever.
3. **Google News resolve cache** — `gnewsdecoder` results cached in `gnews_resolved`. Next run short-circuits the 2-3s per URL cost.

**Sub-issue — CSV overwrites destroyed cache.** First version of the merge did `dict(existing)` then overlaid `filtered`. A `--no-bodies` run would overlay empty-body articles on top of cached bodies, **wiping the cache**. Fix: during merge, preserve existing `full_content` when the new article has none.

**Sub-issue — killed runs lost all progress.** `_save_state()` only fired at the very end of `run()`. User killed mid-enrichment (~40/290) multiple times → state never persisted → every retry started from zero. Fix: `enrich_with_bodies()` now checkpoints state every 20 articles (flushes `gnews_resolved` + `failed_body_urls` to disk). A killed run still banks partial progress.

### 9.5.3 New source — Medias24 WP REST API (tag 8987)

**Before:** only the HTML topic page (`/sujet/attijariwafa-bank/`) → ~6 items, noisy (sidebar leakage).
**After:** `https://medias24.com/wp-json/wp/v2/posts?tags=8987&per_page=100&orderby=date&order=desc` → 128 clean JSON items with structured `date`, `title`, `link`, `excerpt`.

Tag ID 8987 (slug `attijariwafa-bank`) was discovered via `/wp-json/wp/v2/tags?search=attijariwafa` — more precise than the generic category 12575 (ECONOMIE) initially suggested in the user's message.

### 9.5.4 Fast-by-default news scraper

**Issue after 9.5.1-9.5.3:** even with all the state caching, the first warm-up run still took 10+ min because Google News URL resolution is 189 × 2-3s = ~9 min, happening BEFORE the cache check (gnewsdecoder has to run to know if the resolved URL is in cache). User killed three consecutive runs out of frustration.

**Root insight:** the 6 direct scrapers already produce 150+ ATW-specific articles — more than enough for sentiment. Google News is discovery fallback for international coverage, not a daily need. Body enrichment is a nice-to-have (sentiment engine falls back to title-only at `news_sentiment.py:214`).

**Solution — flip defaults.** Everything slow is now opt-in:

| Flag | Effect | Default |
|---|---|---|
| (none) | Direct scrapers only, no body fetch — fast path | **active** |
| `--with-gnews` | Add Google News RSS + gnewsdecoder resolution | off |
| `--with-bodies` | Enable trafilatura body enrichment | off |
| `--deep` | `--with-gnews --with-bodies` | off |
| `--body-limit N` | Implies `--with-bodies`, caps new fetches | none |
| `--full-refresh` | Ignore state, rescrape everything | off |
| `--since YYYY-MM-DD` | Date filter | none |

Log line at start declares the mode explicitly (`Mode: direct sources only, no body fetch (fast path)`).

**Verified runtime on 2026-04-15**: default run completes in **25.1 seconds** with 332 rows preserved + ~150 items re-scraped. Matches the plan's <30s target.

### 9.5.5 Lessons (what to keep in mind)

1. **Look for JSON APIs before Selenium.** Reading the site's JS bundle often reveals endpoints. Selenium is the expensive last resort.
2. **Checkpoint state mid-operation, not at the end.** Long operations get killed. If state only persists at completion, the user re-pays the cost forever.
3. **Caches need teeth.** A cache that gets wiped on the next run is worse than no cache — it hides the real cost. Always test: "does a killed run lose progress?" and "does a flag that skips work also preserve what was there?"
4. **Default to fast.** Opt-in to slow. Users kill runs that feel frozen; they rarely notice runs that finish quickly.
5. **Verify the "fast path" actually got fast.** `time` the default run after every change. Target numbers in the plan, check them in verification.

---

## 10. Known follow-ups (not yet done)

In rough priority order:

1. **Phase 7 database schema** — `ref.instruments` and `ai.predictions` tables. `db/setup.py` currently only creates `md.*`.
2. ~~**MarketScreener news dates missing**~~ — ✅ Fixed 2026-04-15: read `data-utc-date` attribute on `<span class="js-date-relative">` (25/25 rows have dates).
3. ~~**Body / date extraction for direct scrapers**~~ — ✅ Fixed 2026-04-15: `_extract_article_date()` reads `<meta article:published_time>`, JSON-LD `datePublished` (ISO + French via `_parse_french_date`), and `<time datetime>` during body fetch. Boursenews + L'Économiste now provide dates. IR Attijariwafa + Attijari CIB sources dropped entirely (client-side rendered dates).
4. **Banking-specific model tuning** — EV/EBITDA doesn't apply to banks. Some ratios in `relative_valuation.py` silently fall back to generic sector numbers. Worth revisiting per banking best practices.
5. **Arabic sentiment vocabulary** — out of scope now; revisit if RSS coverage shifts toward Arabic press.
6. **Negation handling in sentiment** — *"résultats ne bondissent pas"* still scores positive. Proper fix is a French sentiment model (CamemBERT) — separate project.
7. **Multi-ticker scraping** — current scraper is ATW-hardcoded at the URL level. Extending to MNG/BCP would need either per-ticker scrape functions or URL templates parameterized by ticker. The `TICKER` constant + `ticker` CSV column are already designed for this.

---

## 11. Useful reference paths

- Plan file for the pivot: `C:\Users\arhou\.claude\plans\smooth-forging-moth.md`
- Instrument registry (ATW id=511, bourse casa): `data/scrapers/instruments_bourse_casa.json`
- Instrument registry (MarketScreener url_code): `data/scrapers/instruments_marketscreener.json`
- Git branch with IAM archive: `v1-iam-archive` (local + origin)

---

## 12. What "done" looks like right now

Running `python scrapers/atw_news_scraper.py && PYTHONIOENCODING=utf-8 python -c "from strategies.news_sentiment import NewsSentimentAnalyzer; import pandas as pd; df = pd.read_csv('data/historical/ATW_news.csv').rename(columns={'title':'Title','date':'Date','full_content':'Full_Content'}); print(NewsSentimentAnalyzer().analyze_sentiment(df))"`
should output something like:

```
{'overall_sentiment': 'POSITIVE', 'sentiment_score': 73.5, 'total_articles': 17,
 'positive_count': 10, 'negative_count': 3,
 'events_detected': ['market', 'regulatory', 'earnings', 'management',
                     'merger_acquisition', 'dividend', 'expansion']}
```

If a fresh session sees this result, the ATW pipeline is healthy.
