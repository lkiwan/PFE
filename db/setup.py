"""PFE database schema setup.

Drops and recreates three schemas (ref, md, ai) wired for the ATW pipeline
and ready to host more tickers later. All market/AI tables FK to
ref.instruments via instrument_id; adding a new ticker is a single INSERT.

Run once:
    python db/setup.py
"""
import os
from sqlalchemy import create_engine, text

DB_URL = os.getenv("DATABASE_URL", "postgresql://postgres:123456@localhost:5432/PFE")


def _drop_schemas(conn):
    print("   [-] Dropping old schemas (ref, md, ai)...")
    conn.execute(text("DROP SCHEMA IF EXISTS ai CASCADE;"))
    conn.execute(text("DROP SCHEMA IF EXISTS md CASCADE;"))
    conn.execute(text("DROP SCHEMA IF EXISTS ref CASCADE;"))


def _create_schemas(conn):
    print("   [+] Creating schemas ref, md, ai...")
    conn.execute(text("CREATE SCHEMA ref;"))
    conn.execute(text("CREATE SCHEMA md;"))
    conn.execute(text("CREATE SCHEMA ai;"))


def _create_ref(conn):
    print("   [+] ref.instruments...")
    conn.execute(text("""
        CREATE TABLE ref.instruments (
            instrument_id           SERIAL PRIMARY KEY,
            ticker                  VARCHAR(20)  NOT NULL UNIQUE,
            isin                    VARCHAR(20)  UNIQUE,
            name                    VARCHAR(200) NOT NULL,
            sector                  VARCHAR(100),
            currency                VARCHAR(10)  DEFAULT 'MAD',
            exchange                VARCHAR(20)  DEFAULT 'BVC',
            country                 VARCHAR(5)   DEFAULT 'MA',
            bourse_casa_id          VARCHAR(20),
            marketscreener_url_code VARCHAR(100),
            medias24_isin           VARCHAR(20),
            is_active               BOOLEAN      DEFAULT TRUE,
            created_at              TIMESTAMPTZ  DEFAULT NOW()
        );
    """))


def _create_md(conn):
    print("   [+] md.historical_prices...")
    conn.execute(text("""
        CREATE TABLE md.historical_prices (
            instrument_id     INTEGER NOT NULL REFERENCES ref.instruments(instrument_id) ON DELETE CASCADE,
            trade_date        DATE    NOT NULL,
            open              NUMERIC,
            close             NUMERIC,
            high              NUMERIC,
            low               NUMERIC,
            shares_traded     NUMERIC,
            value_traded_mad  NUMERIC,
            num_trades        INTEGER,
            market_cap        NUMERIC,
            source            VARCHAR(30) DEFAULT 'bourse_casa',
            scraped_at        TIMESTAMPTZ DEFAULT NOW(),
            PRIMARY KEY (instrument_id, trade_date)
        );
    """))
    conn.execute(text("CREATE INDEX idx_hp_inst_date ON md.historical_prices (instrument_id, trade_date DESC);"))

    print("   [+] md.intraday_snapshots...")
    conn.execute(text("""
        CREATE TABLE md.intraday_snapshots (
            id                SERIAL PRIMARY KEY,
            instrument_id     INTEGER NOT NULL REFERENCES ref.instruments(instrument_id) ON DELETE CASCADE,
            snapshot_ts       TIMESTAMPTZ NOT NULL,
            cotation_ts       TIMESTAMPTZ,
            market_status     VARCHAR(20),
            last_price        NUMERIC,
            open              NUMERIC,
            high              NUMERIC,
            low               NUMERIC,
            prev_close        NUMERIC,
            variation_pct     NUMERIC,
            shares_traded     NUMERIC,
            value_traded_mad  NUMERIC,
            num_trades        INTEGER,
            market_cap        NUMERIC,
            UNIQUE (instrument_id, snapshot_ts)
        );
    """))
    conn.execute(text("CREATE INDEX idx_intraday_inst_ts ON md.intraday_snapshots (instrument_id, snapshot_ts DESC);"))

    print("   [+] md.orderbook_snapshots...")
    conn.execute(text("""
        CREATE TABLE md.orderbook_snapshots (
            id            SERIAL PRIMARY KEY,
            instrument_id INTEGER NOT NULL REFERENCES ref.instruments(instrument_id) ON DELETE CASCADE,
            snapshot_ts   TIMESTAMPTZ NOT NULL,
            bid1_orders NUMERIC, bid1_qty NUMERIC, bid1_price NUMERIC,
            bid2_orders NUMERIC, bid2_qty NUMERIC, bid2_price NUMERIC,
            bid3_orders NUMERIC, bid3_qty NUMERIC, bid3_price NUMERIC,
            bid4_orders NUMERIC, bid4_qty NUMERIC, bid4_price NUMERIC,
            bid5_orders NUMERIC, bid5_qty NUMERIC, bid5_price NUMERIC,
            ask1_price NUMERIC, ask1_qty NUMERIC, ask1_orders NUMERIC,
            ask2_price NUMERIC, ask2_qty NUMERIC, ask2_orders NUMERIC,
            ask3_price NUMERIC, ask3_qty NUMERIC, ask3_orders NUMERIC,
            ask4_price NUMERIC, ask4_qty NUMERIC, ask4_orders NUMERIC,
            ask5_price NUMERIC, ask5_qty NUMERIC, ask5_orders NUMERIC,
            UNIQUE (instrument_id, snapshot_ts)
        );
    """))
    conn.execute(text("CREATE INDEX idx_ob_inst_ts ON md.orderbook_snapshots (instrument_id, snapshot_ts DESC);"))

    print("   [+] md.news_articles...")
    conn.execute(text("""
        CREATE TABLE md.news_articles (
            id            SERIAL PRIMARY KEY,
            instrument_id INTEGER NOT NULL REFERENCES ref.instruments(instrument_id) ON DELETE CASCADE,
            publish_date  TIMESTAMPTZ,
            title         TEXT    NOT NULL,
            source        VARCHAR(100),
            url           TEXT    NOT NULL UNIQUE,
            full_content  TEXT,
            query_source  VARCHAR(100),
            signal_score  INTEGER,
            is_atw_core   BOOLEAN,
            scraped_at    TIMESTAMPTZ DEFAULT NOW()
        );
    """))
    conn.execute(text("CREATE INDEX idx_news_inst_date ON md.news_articles (instrument_id, publish_date DESC);"))

    print("   [+] md.technicals...")
    conn.execute(text("""
        CREATE TABLE md.technicals (
            id              SERIAL PRIMARY KEY,
            instrument_id   INTEGER NOT NULL REFERENCES ref.instruments(instrument_id) ON DELETE CASCADE,
            as_of_date      DATE    NOT NULL,
            trend           VARCHAR(30),
            last_close      NUMERIC,
            technicals_json JSONB   NOT NULL,
            computed_at     TIMESTAMPTZ DEFAULT NOW(),
            UNIQUE (instrument_id, as_of_date)
        );
    """))
    conn.execute(text("CREATE INDEX idx_tech_inst_date ON md.technicals (instrument_id, as_of_date DESC);"))

    print("   [+] md.fundamentals...")
    conn.execute(text("""
        CREATE TABLE md.fundamentals (
            id             SERIAL PRIMARY KEY,
            instrument_id  INTEGER NOT NULL REFERENCES ref.instruments(instrument_id) ON DELETE CASCADE,
            scrape_ts      TIMESTAMPTZ NOT NULL,
            price          NUMERIC,
            market_cap     NUMERIC,
            pe_ratio       NUMERIC,
            price_to_book  NUMERIC,
            dividend_yield NUMERIC,
            target_price   NUMERIC,
            consensus      VARCHAR(30),
            num_analysts   INTEGER,
            high_52w       NUMERIC,
            low_52w        NUMERIC,
            hist_json      JSONB NOT NULL,
            UNIQUE (instrument_id, scrape_ts)
        );
    """))
    conn.execute(text("CREATE INDEX idx_fund_inst_ts ON md.fundamentals (instrument_id, scrape_ts DESC);"))

    print("   [+] md.macro_morocco...")
    conn.execute(text("""
        CREATE TABLE md.macro_morocco (
            date                     DATE PRIMARY KEY,
            frequency_tag            VARCHAR(30),
            bank_roe                 NUMERIC,
            gdp_growth_pct           NUMERIC,
            external_debt_pct_gdp    NUMERIC,
            current_account_pct_gdp  NUMERIC,
            public_debt_pct_gdp      NUMERIC,
            gdp_per_capita_usd       NUMERIC,
            inflation_cpi_pct        NUMERIC,
            residential_property_idx NUMERIC,
            gdp_ci                   NUMERIC,
            gdp_sn                   NUMERIC,
            gdp_cm                   NUMERIC,
            gdp_tn                   NUMERIC,
            loaded_at                TIMESTAMPTZ DEFAULT NOW()
        );
    """))


def _create_ai(conn):
    print("   [+] ai.predictions...")
    conn.execute(text("""
        CREATE TABLE ai.predictions (
            id               SERIAL PRIMARY KEY,
            instrument_id    INTEGER NOT NULL REFERENCES ref.instruments(instrument_id) ON DELETE CASCADE,
            prediction_ts    TIMESTAMPTZ NOT NULL,
            recommendation   VARCHAR(20),
            confidence_pct   NUMERIC,
            intrinsic_value  NUMERIC,
            current_price    NUMERIC,
            upside_pct       NUMERIC,
            composite_score  NUMERIC,
            risk_level       VARCHAR(20),
            models_used      INTEGER,
            context_json     JSONB,
            agent_report     TEXT,
            is_canonical     BOOLEAN DEFAULT FALSE,
            created_at       TIMESTAMPTZ DEFAULT NOW(),
            UNIQUE (instrument_id, prediction_ts)
        );
    """))
    conn.execute(text("CREATE INDEX idx_pred_inst_ts ON ai.predictions (instrument_id, prediction_ts DESC);"))
    conn.execute(text("CREATE INDEX idx_pred_canonical ON ai.predictions (instrument_id, is_canonical) WHERE is_canonical;"))

    print("   [+] ai.valuations...")
    conn.execute(text("""
        CREATE TABLE ai.valuations (
            id              SERIAL PRIMARY KEY,
            prediction_id   INTEGER NOT NULL REFERENCES ai.predictions(id) ON DELETE CASCADE,
            model_name      VARCHAR(30) NOT NULL,
            intrinsic_value NUMERIC,
            confidence      NUMERIC,
            model_json      JSONB,
            UNIQUE (prediction_id, model_name)
        );
    """))

    print("   [+] ai.scores...")
    conn.execute(text("""
        CREATE TABLE ai.scores (
            id              SERIAL PRIMARY KEY,
            prediction_id   INTEGER NOT NULL REFERENCES ai.predictions(id) ON DELETE CASCADE UNIQUE,
            value_score     NUMERIC,
            quality_score   NUMERIC,
            growth_score    NUMERIC,
            safety_score    NUMERIC,
            dividend_score  NUMERIC,
            composite_score NUMERIC
        );
    """))


def _seed_atw(conn):
    print("   [+] Seeding ref.instruments with ATW...")
    conn.execute(text("""
        INSERT INTO ref.instruments
            (ticker, isin, name, sector, currency, exchange, country,
             bourse_casa_id, marketscreener_url_code, medias24_isin)
        VALUES
            ('ATW', 'MA0000012445', 'ATTIJARIWAFA BANK', 'Banking',
             'MAD', 'BVC', 'MA', '511',
             'ATTIJARIWAFA-BANK-SA-41148801', 'MA0000012445')
        ON CONFLICT (ticker) DO NOTHING;
    """))


def setup_database():
    engine = create_engine(DB_URL)
    with engine.begin() as conn:
        print("Initializing PFE database (ref / md / ai)...")
        _drop_schemas(conn)
        _create_schemas(conn)
        _create_ref(conn)
        _create_md(conn)
        _create_ai(conn)
        _seed_atw(conn)
        print("Done. Schemas ref, md, ai are ready; ATW seeded.")


if __name__ == "__main__":
    setup_database()
