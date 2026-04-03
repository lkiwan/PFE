import time
import pandas as pd
from io import StringIO
from datetime import datetime, timedelta

from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC

from scrapers.base_scraper import BaseScraper


class OrderBookScraper(BaseScraper):
    """
    Scrapes the Level 2 Order Book from Medias24.
    Because this requires deep Javascript execution, it uses Selenium.
    """
    BASE_URL_OB = "https://medias24.com/leboursier/fiche-action?action={slug}&valeur=carnet-d-ordres"
    
    def __init__(self, use_db: bool = True):
        # We must initialize Selenium here
        super().__init__(use_selenium=True, use_db=use_db)
        
    def _clean_number(self, value):
        if not value or pd.isna(value): return None
        s = str(value).strip().replace("\u202f", "").replace("\xa0", "").replace(" ", "").replace(",", ".")
        try:
            return float(s)
        except ValueError:
            return None

    def fetch_order_book(self, slug: str, instrument_id: int):
        print(f"🚀 Starting Selenium Level 2 OrderBook Scraper for {slug}...")
        url = self.BASE_URL_OB.format(slug=slug)
        self.driver.get(url)
        
        try:
            # Wait for JS to inject the tables
            WebDriverWait(self.driver, 15).until(
                EC.presence_of_element_located((By.CSS_SELECTOR, "table"))
            )
            time.sleep(2)
            
            tables = pd.read_html(StringIO(self.driver.page_source), decimal=",", thousands=" ")
            target_df = None
            
            for df in tables:
                cols = " ".join([str(c).lower() for c in df.columns])
                if "achat" in cols or "vente" in cols or "prix" in cols:
                    target_df = df
                    break
                    
            if target_df is None or target_df.empty:
                print(f"⚠️ No orderbook table found for {slug}")
                return []
                
            # Standardize columns
            if len(target_df.columns) >= 6:
                target_df = target_df.iloc[:, :6]
                target_df.columns = ["ordres_achat", "qte_achat", "prix_achat", "prix_vente", "qte_vente", "ordres_vente"]
            elif len(target_df.columns) == 4:
                target_df.columns = ["qte_achat", "prix_achat", "prix_vente", "qte_vente"]
                
            payloads = []
            snap_time = datetime.now()
            
            for _, row in target_df.iterrows():
                # Skip the 'TOTAL' row
                if "total" in str(row.get("prix_achat", "")).lower():
                    continue
                    
                bid_qty = self._clean_number(row.get("qte_achat"))
                bid_price = self._clean_number(row.get("prix_achat"))
                ask_price = self._clean_number(row.get("prix_vente"))
                ask_qty = self._clean_number(row.get("qte_vente"))
                
                if bid_price is None and ask_price is None:
                    continue

                snap_time += timedelta(microseconds=1)
                
                payloads.append({
                    "instrument_id": instrument_id,
                    "snapshot_time": snap_time,
                    "bid_price": bid_price,
                    "bid_qty": bid_qty,
                    "ask_price": ask_price,
                    "ask_qty": ask_qty,
                    "source_name": "medias24",
                })

            print(f"✅ Extracted {len(payloads)} active bid/ask levels for {slug}.")
            return payloads
            
        except Exception as e:
            print(f"❌ Error scraping orderbook for {slug}: {e}")
            return []
