import os
import sys
import re
from pathlib import Path
from datetime import datetime

_ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(_ROOT))

from dotenv import load_dotenv
from sqlalchemy import create_engine, text
from agno.agent import Agent
from agno.models.groq import Groq
from agents.tools import get_iam_stock_advisory_context

load_dotenv(_ROOT / ".env")

DB_URL = os.getenv("DATABASE_URL", "postgresql://postgres:123456@localhost:5432/PFE")
engine = create_engine(DB_URL)

def get_instrument_id(conn, symbol="IAM"):
    res = conn.execute(text("SELECT instrument_id FROM ref.instruments WHERE symbol=:s LIMIT 1"), {"s": symbol}).fetchone()
    if res:
        return res[0]
    return None

def get_last_prediction(conn, instrument_id):
    """Fetches the previous AI prediction natively from ai.predictions."""
    res = conn.execute(text(
        """SELECT prediction_date, predicted_trend, confidence_score, timeframe, ai_reasoning 
           FROM ai.predictions 
           WHERE instrument_id=:iid 
           ORDER BY prediction_date DESC LIMIT 1"""
    ), {"iid": instrument_id}).fetchone()
    
    if res:
        return (f"On {res[0]}, you recommended {res[1]} with {res[2]}% confidence for a {res[3]} timeframe. "
                f"Your previous report was: {res[4][:300]}...")
    return "This is your first time analyzing this stock. No previous memory."

import subprocess

def run_data_sync(symbol="IAM"):
    """Runs the Casablanca Bourse scraper for the target symbol."""
    print(f"🔄 [0/4] Synchronizing Market Data for {symbol}...")
    try:
        # Construct path to scraper
        scraper_path = _ROOT / "scrapers" / "bourse_casa_scraper.py"
        
        # Run as a subprocess to keep it clean and isolated
        result = subprocess.run(
            [sys.executable, str(scraper_path), "--symbol", symbol],
            capture_output=True, text=True, check=True
        )
        # print(result.stdout) # Optional: print scraper output
        print(f"   [+] Market data for {symbol} is now up to date.")
    except subprocess.CalledProcessError as e:
        print(f"   [!] WARNING: Market data sync failed for {symbol}: {e.stderr}")
    except Exception as e:
        print(f"   [!] WARNING: Unexpected error during sync: {e}")

def run_master_autopilot():
    print("🚀 [1/4] Connecting to Native Relational Database...")
    # Target Symbol (can be parameterized later)
    target_symbol = "IAM"
    
    # Step 0: Sync Data
    run_data_sync(target_symbol)
    
    with engine.begin() as conn:
        instrument_id = get_instrument_id(conn, target_symbol)
        if not instrument_id:
            print(f"❌ ERROR: Could not find '{target_symbol}' in ref.instruments table.")
            # For testing fallback:
            instrument_id = 1
            print(f"⚠️ Falling back to dummy instrument_id = {instrument_id} for testing.")
        else:
            print(f"   [+] Successfully linked symbol '{target_symbol}' to instrument_id = {instrument_id}")

        print("\n🧠 [2/4] Generating AI Context & Relational Memory...")
        memory_context = get_last_prediction(conn, instrument_id)
        live_json_context = get_iam_stock_advisory_context()
        
    print("\n🤖 [3/4] Activating Agno AI Advisor (Groq)...")
    agent = Agent(
        model=Groq(id="llama-3.3-70b-versatile"),
        description="You are a senior quantitative Moroccan stock advisor.",
        instructions=[
            "1. Read the JSON context.",
            "2. Read PREVIOUS Memory.",
            "3. Because you are inserting data into a strict PostgreSQL architecture, you MUST format the VERY FIRST three lines of your response exactly as follows:",
            "RECOMMENDATION: [BUY or HOLD or SELL]",
            "CONFIDENCE: [0 to 100]",
            "TIMEFRAME: [e.g. 1-3 Months]",
            "",
            "4. After that blank line, write your professional 3-paragraph advisory report.",
            "5. Paragraph 1: Primary fundamental reason.",
            "6. Paragraph 2: Comment on the Whale activity and technical trends from the data.",
            "7. Paragraph 3: Highlight the risks and final thoughts."
        ],
        markdown=True
    )
    
    query = f"""
    The stock is IAM.
    [MEMORY CONTEXT]: {memory_context}
    
    [LIVE JSON DATA]: {live_json_context}
    
    Write the final advisory report now adhering strictly to the constraints.
    """
    
    print("   [+] Thinking deeply...")
    response = agent.run(query)
    report_text = response.content
    
    print("\n--- FINAL RAW OUTPUT ---")
    print(report_text)
    print("------------------------\n")
    
    print("🔄 [4/4] Parsing & Inserting into ai.predictions...")
    
    trend_match = re.search(r"RECOMMENDATION:\s*(.+)", report_text, re.IGNORECASE)
    conf_match = re.search(r"CONFIDENCE:\s*(.+)", report_text, re.IGNORECASE)
    time_match = re.search(r"TIMEFRAME:\s*(.+)", report_text, re.IGNORECASE)

    predicted_trend = trend_match.group(1).strip() if trend_match else "UNKNOWN"
    timeframe = time_match.group(1).strip() if time_match else "UNKNOWN"
    
    try:
        # The AI outputs 0-100, but the DB expects 0.0-1.0 (numeric 5,4)
        confidence_score = float(re.sub(r"[^\d.]", "", conf_match.group(1))) / 100.0 if conf_match else 0.0
    except ValueError:
        confidence_score = 0.0

    print(f"   [+] Parsed Trend: {predicted_trend}")
    print(f"   [+] Parsed Confidence: {confidence_score}")
    print(f"   [+] Parsed Timeframe: {timeframe}")

    with engine.begin() as conn:
        conn.execute(text("""
            INSERT INTO ai.predictions (
                instrument_id, prediction_date, predicted_trend, confidence_score, timeframe, ai_reasoning
            ) VALUES (
                :iid, :pdata, :ptrend, :conf, :tf, :reason
            )
        """), {
            "iid": instrument_id,
            "pdata": datetime.now(),
            "ptrend": predicted_trend,
            "conf": confidence_score,
            "tf": timeframe,
            "reason": report_text
        })
    print("✅ Institutional Autopilot Execution Complete!")

if __name__ == "__main__":
    run_master_autopilot()
