"""
Casablanca Bourse Multi-Instrument Scraper (Interactive & Incremental)
======================================================================
Fetches historical OHLCV, volume, trades, and market cap for multiple 
stocks from the official Casablanca Stock Exchange API.

Interactive Menu:
- Choose to scrape ALL configured instruments.
- Or select specific instruments by number.

Persistence:
- Incremental: Tracks last scraped date per symbol in bourse_casa_state.json.
- Database: Syncs directly to PostgreSQL 'public.md_eod_bars'.
- CSV: Backs up data to 'data/historical/{SYMBOL}_bourse_casa_full.csv'.
"""

import os
import csv
import json
import certifi
import time
import sys
from datetime import datetime, timedelta
from typing import List, Dict, Optional
from pathlib import Path

import cloudscraper
from sqlalchemy import create_engine, text

# Fix SSL cert path (PostgreSQL install overrides system certs)
os.environ["REQUESTS_CA_BUNDLE"] = certifi.where()
os.environ["SSL_CERT_FILE"] = certifi.where()

_ROOT = Path(__file__).resolve().parent.parent

# --- Configuration ---
BASE_URL = "https://www.casablanca-bourse.com/api/proxy/fr/api/bourse_data/instrument_history"
STATE_DIR = _ROOT / "data" / "scrapers"
STATE_FILE = STATE_DIR / "bourse_casa_state.json"
CONFIG_FILE = STATE_DIR / "instruments_bourse_casa.json"
DATA_DIR = _ROOT / "data" / "historical"

# DB Connection
DB_URL = os.getenv("DATABASE_URL", "postgresql://postgres:123456@localhost:5432/PFE")
engine = create_engine(DB_URL)

def create_scraper() -> cloudscraper.CloudScraper:
    """Create a cloudscraper session with appropriate headers."""
    scraper = cloudscraper.create_scraper(
        browser={"browser": "chrome", "platform": "windows", "mobile": False}
    )
    scraper.headers.update({
        "Accept": "application/vnd.api+json",
        "Content-Type": "application/vnd.api+json",
    })
    return scraper

def load_config() -> List[Dict]:
    """Load instrument mapping from JSON config."""
    if not CONFIG_FILE.exists():
        print(f"❌ Error: Config file {CONFIG_FILE} not found.")
        return []
    with open(CONFIG_FILE, "r") as f:
        data = json.load(f)
        return data.get("instruments", [])

def load_state() -> Dict:
    """Load the last scraped dates for each symbol."""
    if STATE_FILE.exists():
        with open(STATE_FILE, "r") as f:
            state = json.load(f)
            # Ensure it's the new format
            if "last_scraped_date" in state and isinstance(state["last_scraped_date"], dict):
                return state["last_scraped_date"]
            elif "last_scraped_date" in state: # Old single-string format
                return {"CIH": state["last_scraped_date"]}
    return {}

def save_state(symbol: str, last_date: str):
    """Update and save the state for a specific symbol."""
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    current_state = {}
    if STATE_FILE.exists():
        with open(STATE_FILE, "r") as f:
            file_data = json.load(f)
            current_state = file_data.get("last_scraped_date", {}) if isinstance(file_data.get("last_scraped_date"), dict) else {}
    
    current_state[symbol] = last_date
    with open(STATE_FILE, "w") as f:
        json.dump({"last_scraped_date": current_state}, f, indent=2)

def fetch_history_page(scraper: cloudscraper.CloudScraper, symbol: str, instrument_id: str, start_date: str, offset: int = 0, limit: int = 250) -> Dict:
    """Fetch a single page of historical data from the API."""
    scraper.headers["Referer"] = f"https://www.casablanca-bourse.com/fr/instruments?instrument={instrument_id}"
    
    params = {
        "fields[instrument_history]": "symbol,created,openingPrice,coursCourant,highPrice,lowPrice,cumulTitresEchanges,cumulVolumeEchange,totalTrades,capitalisation,coursAjuste,closingPrice,ratioConsolide",
        "fields[instrument]": "symbol,libelleFR,libelleAR,libelleEN,emetteur_url,instrument_url",
        "fields[taxonomy_term--bourse_emetteur]": "name",
        "include": "symbol",
        "sort[date-seance][path]": "created",
        "sort[date-seance][direction]": "DESC",
        "filter[filter-historique-instrument-emetteur][condition][path]": "symbol.codeSociete.meta.drupal_internal__target_id",
        "filter[filter-historique-instrument-emetteur][condition][value]": "-1",
        "filter[filter-historique-instrument-emetteur][condition][operator]": "=",
        "filter[instrument-history-class][condition][path]": "symbol.codeClasse.field_code",
        "filter[instrument-history-class][condition][value]": "1",
        "filter[instrument-history-class][condition][operator]": "=",
        "filter[published]": "1",
        "page[offset]": str(offset),
        "page[limit]": str(limit),
        "filter[filter-date-start-vh-select][condition][path]": "field_seance_date",
        "filter[filter-date-start-vh-select][condition][operator]": ">=",
        "filter[filter-date-start-vh-select][condition][value]": start_date,
        "filter[filter-historique-instrument-emetteur][condition][path]": "symbol.meta.drupal_internal__target_id",
        "filter[filter-historique-instrument-emetteur][condition][operator]": "=",
        "filter[filter-historique-instrument-emetteur][condition][value]": instrument_id
    }
    
    resp = scraper.get(BASE_URL, params=params, timeout=30)
    if resp.status_code != 200:
        raise Exception(f"API Error {resp.status_code}: {resp.text[:500]}")
    
    return resp.json()

def scrape_symbol(symbol: str, instrument_id: str, start_date: str) -> List[Dict]:
    """Fetch historical records for a symbol since start_date."""
    scraper = create_scraper()
    all_records = []
    offset = 0
    limit = 250
    
    while True:
        data = fetch_history_page(scraper, symbol, instrument_id, start_date, offset, limit)
        page_data = data.get("data", [])
        if not page_data:
            break
            
        for item in page_data:
            attr = item.get("attributes", {})
            all_records.append({
                "Séance": attr.get("created"),
                "Instrument": symbol,
                "Ticker": symbol,
                "Ouverture": attr.get("openingPrice"),
                "Dernier Cours": attr.get("closingPrice"),
                "+haut du jour": attr.get("highPrice"),
                "+bas du jour": attr.get("lowPrice"),
                "Nombre de titres échangés": attr.get("cumulTitresEchanges"),
                "Volume des échanges": attr.get("cumulVolumeEchange"),
                "Nombre de transactions": attr.get("totalTrades"),
                "Capitalisation": attr.get("capitalisation")
            })
            
        links = data.get("links", {})
        if "next" not in links:
            break
        offset += limit
        time.sleep(0.5)
        
    return all_records

def save_to_postgresql(records: List[Dict]):
    """Insert or skip records in public.md_eod_bars."""
    if not records:
        return 0
    
    inserted_count = 0
    with engine.begin() as conn:
        for r in records:
            exists = conn.execute(text(
                "SELECT 1 FROM public.md_eod_bars WHERE valeur_name = :val AND trade_date = :dt LIMIT 1"
            ), {"val": r["Ticker"], "dt": r["Séance"]}).fetchone()
            
            if not exists:
                try:
                    val_op = float(r["Ouverture"]) if r["Ouverture"] else None
                    val_cl = float(r["Dernier Cours"]) if r["Dernier Cours"] else None
                    val_hi = float(r["+haut du jour"]) if r["+haut du jour"] else None
                    val_lo = float(r["+bas du jour"]) if r["+bas du jour"] else None
                    val_vol = int(float(r["Nombre de titres échangés"])) if r["Nombre de titres échangés"] else 0
                    val_tr = str(int(float(r["Nombre de transactions"]))) if r["Nombre de transactions"] else "0"
                    val_cap = float(r["Capitalisation"]) if r["Capitalisation"] else None
                    val_ref = float(r["Volume des échanges"]) if r["Volume des échanges"] else None

                    conn.execute(text("""
                        INSERT INTO public.md_eod_bars (
                            valeur_name, trade_date, cours_open, cours_close, 
                            cours_plus_haut, cours_plus_bas, volume_titres,
                            nombre_transactions, capitalisation, cours_reference
                        ) VALUES (
                            :val, :dt, :op, :cl, :hi, :lo, :vol, :tr, :cap, :ref
                        )
                    """), {
                        "val": r["Ticker"], "dt": r["Séance"], "op": val_op, "cl": val_cl,
                        "hi": str(val_hi) if val_hi is not None else None,
                        "lo": str(val_lo) if val_lo is not None else None,
                        "vol": val_vol, "tr": val_tr, "cap": val_cap, "ref": val_ref
                    })
                    inserted_count += 1
                except (ValueError, TypeError):
                    continue
    return inserted_count

def save_to_csv_incremental(symbol: str, records: List[Dict]):
    """Append new records to symbol-specific CSV."""
    if not records:
        return 0
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    csv_path = DATA_DIR / f"{symbol}_bourse_casa_full.csv"
    
    records.sort(key=lambda x: x["Séance"])
    exists = csv_path.exists()
    existing_dates = set()
    
    if exists:
        with open(csv_path, "r", encoding="utf-8-sig") as f:
            reader = csv.DictReader(f)
            for row in reader:
                existing_dates.add(row.get("Séance"))
    
    new_rows = [r for r in records if r["Séance"] not in existing_dates]
    if not new_rows:
        return 0
        
    mode = "a" if exists else "w"
    with open(csv_path, mode, newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=list(records[0].keys()))
        if not exists:
            writer.writeheader()
        writer.writerows(new_rows)
    return len(new_rows)

import argparse

def main():
    parser = argparse.ArgumentParser(description="Casablanca Bourse Scraper")
    parser.add_argument("--symbol", help="Scrape a specific symbol (e.g. CIH)")
    parser.add_argument("--all", action="store_true", help="Scrape all markets")
    args = parser.parse_args()

    print("=" * 60)
    print("  Casablanca Bourse Scraper: Interactive & Multi-Stock")
    print("=" * 60)
    
    instruments = load_config()
    if not instruments:
        return

    to_process = []

    if args.symbol:
        to_process = [inst for inst in instruments if inst['symbol'].upper() == args.symbol.upper()]
        if not to_process:
            print(f"❌ Symbol '{args.symbol}' not found in config.")
            return
    elif args.all:
        to_process = instruments
    else:
        # Interactive Menu
        print("\nAvailable Markets:")
        print(f"  [0]  ALL MARKETS")
        for i, inst in enumerate(instruments, 1):
            print(f"  [{i}]  {inst['symbol']} - {inst['name']}")

        choice = input("\nSelect market(s) to scrape (e.g. 0 or 1,3,5): ").strip()
        
        if choice == "0":
            to_process = instruments
        else:
            try:
                indices = [int(x.strip()) for x in choice.split(",") if x.strip().isdigit()]
                to_process = [instruments[i-1] for i in indices if 0 < i <= len(instruments)]
            except Exception:
                print("❌ Invalid selection.")
                return

    if not to_process:
        print("❌ No valid markets selected.")
        return

    state = load_state()
    
    for inst in to_process:
        symbol = inst['symbol']
        inst_id = inst['id']
        print(f"\n🚀 Processing: {symbol} (ID: {inst_id})")
        
        last_date = state.get(symbol, "2010-01-01")
        last_date_obj = datetime.strptime(last_date, "%Y-%m-%d")
        start_date = (last_date_obj + timedelta(days=1)).strftime("%Y-%m-%d")
        
        try:
            new_records = scrape_symbol(symbol, inst_id, start_date)
            if not new_records:
                print(f"  [+] {symbol}: Already up to date.")
                continue

            print(f"  [+] {symbol}: Found {len(new_records)} new trading days.")
            db_count = save_to_postgresql(new_records)
            print(f"  [+] Database: Inserted {db_count} records.")
            csv_count = save_to_csv_incremental(symbol, new_records)
            print(f"  [+] CSV: Appended {csv_count} records.")
            
            newest_date = max(r["Séance"] for r in new_records)
            save_state(symbol, newest_date)
            print(f"  [+] State: Updated to {newest_date}")
            
        except Exception as e:
            print(f"  ❌ Error processing {symbol}: {e}")

    print("\n✅ All scraping tasks completed.")

if __name__ == "__main__":
    main()
