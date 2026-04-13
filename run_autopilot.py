import os
import sys
import re
import json
import argparse
from pathlib import Path
from datetime import datetime

_ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(_ROOT))

from dotenv import load_dotenv
from sqlalchemy import create_engine, text
from agno.agent import Agent
from agno.models.groq import Groq
from agents.tools import get_stock_advisory_context

load_dotenv(_ROOT / ".env")

DB_URL = os.getenv("DATABASE_URL", "postgresql://postgres:123456@localhost:5432/PFE")
engine = create_engine(DB_URL)

DATA_DIR = _ROOT / "data" / "historical"


# =============================================================================
# Auto-detect stocks with sufficient data
# =============================================================================

def find_ready_stocks(min_years: int = 3) -> list:
    """Find all stocks that have enough data to run the AI prediction.

    Requirements:
    - merged JSON exists with price, revenue, eps, ebitda (>= min_years each)
    - bourse casa CSV exists
    """
    ready = []
    for f in sorted(DATA_DIR.glob("*_merged.json")):
        sym = f.stem.replace("_merged", "")
        try:
            d = json.load(open(f, encoding="utf-8"))
        except Exception:
            continue

        has_price = bool(d.get("price"))
        has_revenue = len(d.get("hist_revenue", {})) >= min_years
        has_eps = len(d.get("hist_eps", {})) >= min_years
        has_ebitda = len(d.get("hist_ebitda", {})) >= min_years
        has_bourse = (DATA_DIR / f"{sym}_bourse_casa_full.csv").exists()

        if has_price and has_revenue and has_eps and has_ebitda and has_bourse:
            ready.append(sym)

    return ready


# =============================================================================
# Database helpers
# =============================================================================

def get_instrument_id(conn, symbol):
    res = conn.execute(
        text("SELECT instrument_id FROM ref.instruments WHERE symbol=:s LIMIT 1"),
        {"s": symbol},
    ).fetchone()
    return res[0] if res else None


def get_last_prediction(conn, instrument_id):
    res = conn.execute(
        text(
            """SELECT prediction_date, predicted_trend, confidence_score, timeframe, ai_reasoning
               FROM ai.predictions
               WHERE instrument_id=:iid
               ORDER BY prediction_date DESC LIMIT 1"""
        ),
        {"iid": instrument_id},
    ).fetchone()

    if res:
        return (
            f"On {res[0]}, you recommended {res[1]} with {res[2]}% confidence "
            f"for a {res[3]} timeframe. Your previous report was: {res[4][:300]}..."
        )
    return "This is your first time analyzing this stock. No previous memory."


# =============================================================================
# Data sync
# =============================================================================

import subprocess


def run_data_sync(symbol):
    """Runs the Casablanca Bourse scraper for the target symbol."""
    print(f"   [sync] Updating market data for {symbol}...")
    try:
        scraper_path = _ROOT / "scrapers" / "bourse_casa_scraper.py"
        subprocess.run(
            [sys.executable, str(scraper_path), "--symbol", symbol],
            capture_output=True, text=True, check=True,
        )
        print(f"   [sync] Market data for {symbol} is up to date.")
    except subprocess.CalledProcessError as e:
        print(f"   [sync] WARNING: sync failed for {symbol}: {e.stderr[:200]}")
    except Exception as e:
        print(f"   [sync] WARNING: {e}")


# =============================================================================
# Single stock prediction
# =============================================================================

def run_prediction(target_symbol, skip_sync=False):
    """Run the full AI prediction pipeline for one stock."""
    print(f"\n{'='*60}")
    print(f"  AI Prediction: {target_symbol}")
    print(f"{'='*60}")

    # Step 0: Sync market data
    if not skip_sync:
        run_data_sync(target_symbol)

    # Step 1: DB connection + memory
    print(f"\n   [1/4] Connecting to Database...")
    with engine.begin() as conn:
        instrument_id = get_instrument_id(conn, target_symbol)
        if not instrument_id:
            print(f"   WARNING: '{target_symbol}' not in ref.instruments, using fallback id=1")
            instrument_id = 1
        else:
            print(f"   Linked '{target_symbol}' to instrument_id={instrument_id}")

        print(f"   [2/4] Generating AI Context...")
        memory_context = get_last_prediction(conn, instrument_id)
        live_json_context = get_stock_advisory_context(target_symbol)

    # Step 2: AI prediction
    print(f"   [3/4] Activating Agno AI Advisor (Groq)...")
    agent = Agent(
        model=Groq(id="llama-3.3-70b-versatile"),
        description="You are a senior quantitative Moroccan stock advisor.",
        instructions=[
            "1. Read the JSON context.",
            "2. Read PREVIOUS Memory.",
            "3. Because you are inserting data into a strict PostgreSQL architecture, "
            "you MUST format the VERY FIRST three lines of your response exactly as follows:",
            "RECOMMENDATION: [BUY or HOLD or SELL]",
            "CONFIDENCE: [0 to 100]",
            "TIMEFRAME: [e.g. 1-3 Months]",
            "",
            "4. After that blank line, write your professional 3-paragraph advisory report.",
            "5. Paragraph 1: Primary fundamental reason.",
            "6. Paragraph 2: Comment on the Whale activity and technical trends from the data.",
            "7. Paragraph 3: Highlight the risks and final thoughts.",
        ],
        markdown=True,
    )

    query = f"""
    The stock is {target_symbol}.
    [MEMORY CONTEXT]: {memory_context}

    [LIVE JSON DATA]: {live_json_context}

    Write the final advisory report now adhering strictly to the constraints.
    """

    print("   Thinking deeply...")
    response = agent.run(query)
    report_text = response.content

    print(f"\n--- {target_symbol} REPORT ---")
    print(report_text)
    print("----------------------------\n")

    # Step 3: Parse and insert
    print(f"   [4/4] Parsing & inserting into ai.predictions...")

    trend_match = re.search(r"RECOMMENDATION:\s*(.+)", report_text, re.IGNORECASE)
    conf_match = re.search(r"CONFIDENCE:\s*(.+)", report_text, re.IGNORECASE)
    time_match = re.search(r"TIMEFRAME:\s*(.+)", report_text, re.IGNORECASE)

    predicted_trend = trend_match.group(1).strip() if trend_match else "UNKNOWN"
    timeframe = time_match.group(1).strip() if time_match else "UNKNOWN"

    try:
        raw_conf = float(re.sub(r"[^\d.]", "", conf_match.group(1))) if conf_match else 0.0
    except ValueError:
        raw_conf = 0.0

    # Normalize: AI sometimes outputs 0-1 scale, sometimes 0-100 scale
    # If value <= 1.0 it's already 0-1, otherwise convert from 0-100
    if raw_conf > 1.0:
        confidence_display = raw_conf          # e.g. 60 → display as 60%
        confidence_db = raw_conf / 100.0       # e.g. 60 → store as 0.6
    else:
        confidence_display = raw_conf * 100    # e.g. 0.6 → display as 60%
        confidence_db = raw_conf               # e.g. 0.6 → store as 0.6

    print(f"   Trend: {predicted_trend}")
    print(f"   Confidence: {confidence_display:.0f}%")
    print(f"   Timeframe: {timeframe}")

    with engine.begin() as conn:
        conn.execute(
            text(
                """INSERT INTO ai.predictions (
                    instrument_id, prediction_date, predicted_trend,
                    confidence_score, timeframe, ai_reasoning
                ) VALUES (:iid, :pdata, :ptrend, :conf, :tf, :reason)"""
            ),
            {
                "iid": instrument_id,
                "pdata": datetime.now(),
                "ptrend": predicted_trend,
                "conf": confidence_db,
                "tf": timeframe,
                "reason": report_text,
            },
        )

    print(f"   Done: {target_symbol} -> {predicted_trend}")
    return predicted_trend, confidence_display


# =============================================================================
# Main
# =============================================================================

def _safe_print(text):
    try:
        print(text)
    except UnicodeEncodeError:
        print(text.encode(errors="replace").decode("ascii", errors="replace"))


def main():
    parser = argparse.ArgumentParser(description="AI Stock Autopilot")
    parser.add_argument("--symbol", help="Stock symbol (e.g. IAM)")
    parser.add_argument("--all", action="store_true", help="Run for all stocks with sufficient data")
    parser.add_argument("--no-sync", action="store_true", help="Skip market data sync")
    args = parser.parse_args()

    ready = find_ready_stocks()

    # --- Mode 1: explicit symbol ---
    if args.symbol:
        sym = args.symbol.upper()
        if sym not in ready:
            print(f"WARNING: {sym} may not have enough data. Running anyway...")
        run_prediction(sym, skip_sync=args.no_sync)
        return

    # --- Mode 2: --all ---
    if args.all:
        _safe_print(f"\nRunning AI predictions for {len(ready)} stocks with full data...")
        _safe_print(f"Stocks: {', '.join(ready)}\n")

        results = {}
        for idx, sym in enumerate(ready, 1):
            _safe_print(f"\n[{idx}/{len(ready)}] Processing {sym}...")
            try:
                trend, conf = run_prediction(sym, skip_sync=args.no_sync)
                results[sym] = f"{trend} ({conf:.0f}%)"
            except Exception as e:
                _safe_print(f"   FAILED: {e}")
                results[sym] = "FAILED"

        _safe_print(f"\n{'='*60}")
        _safe_print("SUMMARY")
        _safe_print(f"{'='*60}")
        for sym, result in results.items():
            _safe_print(f"  {sym:5s}: {result}")
        _safe_print(f"{'='*60}")
        return

    # --- Mode 3: interactive picker ---
    if not ready:
        print("No stocks with sufficient data found.")
        print("Run the scrapers and merger first.")
        return

    _safe_print(f"\nAI Stock Autopilot")
    _safe_print(f"{'='*55}")
    _safe_print(f"  [0] ALL ({len(ready)} stocks with full data)")
    for i, sym in enumerate(ready, 1):
        _safe_print(f"  [{i}] {sym}")

    try:
        choice = input("\nSelect number: ").strip()
        if not choice:
            return
        choice = int(choice)
    except (ValueError, KeyboardInterrupt):
        print("Cancelled.")
        return

    if choice == 0:
        # Run all
        results = {}
        for idx, sym in enumerate(ready, 1):
            _safe_print(f"\n[{idx}/{len(ready)}] Processing {sym}...")
            try:
                trend, conf = run_prediction(sym, skip_sync=args.no_sync)
                results[sym] = f"{trend} ({conf:.0f}%)"
            except Exception as e:
                _safe_print(f"   FAILED: {e}")
                results[sym] = "FAILED"

        _safe_print(f"\n{'='*60}")
        _safe_print("SUMMARY")
        _safe_print(f"{'='*60}")
        for sym, result in results.items():
            _safe_print(f"  {sym:5s}: {result}")
        _safe_print(f"{'='*60}")

    elif 1 <= choice <= len(ready):
        run_prediction(ready[choice - 1], skip_sync=args.no_sync)
    else:
        print("Invalid selection.")


if __name__ == "__main__":
    main()
