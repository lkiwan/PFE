import asyncio
import pandas as pd
from io import StringIO
from datetime import datetime
from bs4 import BeautifulSoup

from scrapers.base_scraper import BaseScraper

class MasiScraper(BaseScraper):
    """
    Scrapes the MASI Index historical data from Investing.com.
    Investing.com is heavily protected, so this forces Selenium usage.
    """
    URL = "https://fr.investing.com/indices/masi-historical-data"
    
    def __init__(self, use_db: bool = True):
        super().__init__(use_selenium=True, use_db=use_db)
        
    def _clean_number(self, text_val: str):
        if not text_val or text_val.strip() in ("-", "", "N/A"):
            return None
        s = text_val.strip().replace("%", "")
        
        multiplier = 1
        if s.endswith("M"):
            multiplier = 1_000_000
            s = s[:-1]
        elif s.endswith("K"):
            multiplier = 1_000
            s = s[:-1]
            
        if "," in s and "." in s:
            s = s.replace(".", "").replace(",", ".")
        elif "," in s:
            s = s.replace(",", ".")
            
        try:
            return float(s) * multiplier
        except ValueError:
            return None

    def fetch_masi_data(self, max_rows: int = 18):
        print("🚀 Starting MASI Index Scraper (Investing.com)...")
        self.driver.get(self.URL)
        import time
        time.sleep(5)  # Wait for JS and Cloudflare
        
        soup = BeautifulSoup(self.driver.page_source, "html.parser")
        table = soup.find("table")
        if not table:
            print("❌ Could not find MASI data table. Cloudflare blocked?")
            return []
            
        records = []
        rows = table.find("tbody").find_all("tr") if table.find("tbody") else []
        
        for row in rows[:max_rows]:
            cells = row.find_all("td")
            if len(cells) < 7: continue
            
            try:
                date_val = datetime.strptime(cells[0].text.strip(), "%d/%m/%Y").date()
            except:
                continue
                
            records.append({
                "index_name": "MASI",
                "trade_date": date_val,
                "close_price": self._clean_number(cells[1].text),
                "open_price": self._clean_number(cells[2].text),
                "high": self._clean_number(cells[3].text),
                "low": self._clean_number(cells[4].text),
                "volume": self._clean_number(cells[5].text),
                "change_pct": self._clean_number(cells[6].text),
                "source_name": "investing"
            })
            
        print(f"✅ Parsed {len(records)} MASI records.")
        return records


class Medias24Scraper(BaseScraper):
    """
    Scrapes Medias24 Historical Data.
    Since Medias24 is less strict, we use aiohttp to make it lightweight!
    """
    BASE_URL_HIST = "https://medias24.com/leboursier/fiche-action?action={slug}&valeur=historiques"
    
    def __init__(self, use_db: bool = True):
        # We don't initialize Selenium here! (Lighter)
        super().__init__(use_selenium=False, use_db=use_db)
        
    def _clean_number(self, value):
        if not value or pd.isna(value): return None
        s = str(value).strip().replace("\u202f", "").replace(" ", "").replace("%", "")
        s = s.replace("MAD", "").replace("mad", "").replace(",", ".")
        try:
            return float(s)
        except ValueError:
            return None

    async def fetch_history_aiohttp(self, slug: str):
        print(f"🚀 Starting Medias24 aiohttp Scraper for {slug}...")
        url = self.BASE_URL_HIST.format(slug=slug)
        
        try:
            html = await self.fetch_html_aiohttp(url)
            # Medias24 tables are easily parseable if they render server-side
            tables = pd.read_html(StringIO(html), decimal=",", thousands=" ")
            target_df = None
            
            for df in tables:
                cols = " ".join([str(c).lower() for c in df.columns])
                if "cours" in cols and ("date" in cols or "séance" in cols):
                    target_df = df
                    break
                    
            if target_df is None or target_df.empty:
                print(f"⚠️ Medias24 might be loading dynamically for {slug}. Use Selenium if needed.")
                return []
                
            payloads = []
            date_col = next((c for c in target_df.columns if 'date' in str(c).lower() or 'séance' in str(c).lower()), 'Date')
            
            for _, row in target_df.head(18).iterrows():
                try:
                    trade_date = datetime.strptime(str(row[date_col]).strip(), "%d/%m/%Y").date()
                except ValueError:
                    continue
                    
                payloads.append({
                    "trade_date": trade_date,
                    "price": self._clean_number(row.get('Cours')),
                    "volume": self._clean_number(row.get('Volume'))
                })
            print(f"✅ Medias24 aiohttp got {len(payloads)} records for {slug}.")
            return payloads
            
        except Exception as e:
            print(f"❌ Error in Medias24 scraper for {slug}: {e}")
            return []
