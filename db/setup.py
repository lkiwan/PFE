import os
from sqlalchemy import create_engine, text

# Default to the local PFE DB
DB_URL = os.getenv("DATABASE_URL", "postgresql://postgres:123456@localhost:5432/PFE")

def setup_database():
    engine = create_engine(DB_URL)
    
    with engine.begin() as conn:
        print("🚀 Initializing Database Restructure...")
        
        # We need to create 'md' schema if it doesn't exist
        conn.execute(text("CREATE SCHEMA IF NOT EXISTS md;"))
        
        print("   [+] Dropping old tables to start fresh...")
        conn.execute(text("DROP TABLE IF EXISTS md.predictions CASCADE;"))
        conn.execute(text("DROP TABLE IF EXISTS md.news_articles CASCADE;"))
        conn.execute(text("DROP TABLE IF EXISTS md.historical_prices CASCADE;"))
        # Agno's PgMemory creates its own tables, usually `agent_sessions` or similar. We leave those alone or let Agno manage them automatically.

        print("   [+] Creating md.historical_prices...")
        conn.execute(text("""
            CREATE TABLE md.historical_prices (
                id SERIAL PRIMARY KEY,
                ticker VARCHAR(20) NOT NULL,
                trade_date DATE NOT NULL,
                close_price NUMERIC,
                volume NUMERIC,
                scraped_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(ticker, trade_date)
            );
        """))

        print("   [+] Creating md.news_articles...")
        conn.execute(text("""
            CREATE TABLE md.news_articles (
                id SERIAL PRIMARY KEY,
                ticker VARCHAR(20) NOT NULL,
                publish_date DATE,
                headline TEXT NOT NULL,
                url TEXT NOT NULL,
                scraped_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(url)
            );
        """))

        print("   [+] Creating md.predictions...")
        conn.execute(text("""
            CREATE TABLE md.predictions (
                id SERIAL PRIMARY KEY,
                ticker VARCHAR(20) NOT NULL,
                prediction_date DATE NOT NULL,
                recommendation VARCHAR(50), 
                context_json JSONB,
                agent_report TEXT,
                UNIQUE(ticker, prediction_date)
            );
        """))

        print("✅ Database Restructure Complete! Clean Slate ready for Autopilot.")

if __name__ == "__main__":
    setup_database()
