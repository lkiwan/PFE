import sys
import argparse
import logging
from pathlib import Path
from dotenv import load_dotenv

# Ensure the root project directory is in the path to avoid ModuleNotFoundError
_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_ROOT))

from agno.agent import Agent
from agno.models.groq import Groq
from agents.tools import get_atw_stock_advisory_context

# Load environment variables from .env file in the project root
load_dotenv(_ROOT / ".env")

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")

def get_advisor_agent(model_id: str = "llama-3.3-70b-versatile") -> Agent:
    """
    Constructs the Agno AI Agent using Groq.
    Equips the agent with the internal tool it needs to pull real-time
    financial data synthesized by our Python engines.
    """
    agent = Agent(
        model=Groq(id=model_id),
        tools=[get_atw_stock_advisory_context],
        description="You are a senior quantitative Moroccan stock advisor for a hedge fund, specializing in Attijariwafa Bank (ATW).",
        instructions=[
            "1. You must ALWAYS use the `get_atw_stock_advisory_context` tool to retrieve the stock's data before answering.",
            "2. Never guess or hallucinate financial numbers. Use only the data returned by the tool.",
            "3. Because you are inserting data into a strict PostgreSQL architecture, you MUST format the VERY FIRST three lines of your response exactly as follows:",
            "RECOMMENDATION: [BUY/HOLD/SELL]",
            "CONFIDENCE: [0 to 100]",
            "TIMEFRAME: [e.g. 1-3 Months / 6-12 Months]",
            "",
            "4. After that blank line, write your professional 3-paragraph advisory report.",
            "5. Paragraph 1: Primary fundamental reason for your recommendation.",
            "6. Paragraph 2: Comment on the Whale activity and technical trends from the data.",
            "7. Paragraph 3: Highlight the risks and final thoughts.",
            "8. Keep your tone highly professional, objective, and strictly based on the provided metrics."
        ],
        markdown=True
    )
    return agent

def main():
    parser = argparse.ArgumentParser(description="ATW AI Advisor")
    parser.add_argument("--test", action="store_true", help="Run a test prediction for ATW")
    parser.add_argument("--query", type=str, default="Based on our quantitative models, what is the current advisory for Attijariwafa Bank (ATW)?")
    args = parser.parse_args()

    print("🚀 Initializing Agno AI Quantitative Advisor...")
    agent = get_advisor_agent()

    if args.test:
        print(f"\n🗣️  User Query: {args.query}\n")
        print("🤖 AI Advisor is analyzing the data via tools...\n" + "-"*60)
        
        # In Agno, we run agent.print_response for standard CLI output
        agent.print_response(args.query, stream=True)
        print("\n" + "-"*60 + "\n✅ Test Complete.")

if __name__ == "__main__":
    main()
