import os
import certifi
import asyncio
import aiohttp
from typing import Optional, Dict, Any

from sqlalchemy import create_engine, text
from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.chrome.options import Options
from webdriver_manager.chrome import ChromeDriverManager

class BaseScraper:
    """
    Parent class to handle DB connections and web requests using either 
    aiohttp (lightweight) or Selenium (heavyweight).
    """
    def __init__(self, use_selenium: bool = False, use_db: bool = True):
        self.use_selenium = use_selenium
        self.use_db = use_db
        self.engine = None
        self.driver = None
        
        # Setup SSL context for aiohttp
        os.environ["REQUESTS_CA_BUNDLE"] = certifi.where()
        os.environ["SSL_CERT_FILE"] = certifi.where()
        
        if self.use_db:
            self._init_db()
            
        if self.use_selenium:
            self._init_selenium()

    def _init_db(self):
        db_url = os.getenv("DATABASE_URL")
        # For PFE, if DB_URL is not set we might just want to store locally or warn.
        if not db_url:
            print("⚠️ WARNING: DATABASE_URL not set in environment. Falling back to local sqlite.")
            db_url = "sqlite:///pfe_database.db"
        self.engine = create_engine(db_url, pool_pre_ping=True, future=True)

    def _init_selenium(self):
        options = Options()
        options.add_argument("--headless=new")
        options.add_argument("--no-sandbox")
        options.add_argument("--disable-dev-shm-usage")
        options.add_argument("--disable-gpu")
        options.add_argument("--window-size=1920,1080")
        options.add_argument(
            "user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
        )
        service = Service(ChromeDriverManager().install())
        self.driver = webdriver.Chrome(service=service, options=options)

    async def fetch_html_aiohttp(self, url: str, headers: Optional[Dict[str, str]] = None) -> str:
        """Lightweight html fetcher for static pages."""
        async with aiohttp.ClientSession(headers=headers) as session:
            async with session.get(url) as response:
                response.raise_for_status()
                return await response.text()

    def close(self):
        """Cleanup resources."""
        if self.driver:
            self.driver.quit()
        if self.engine:
            self.engine.dispose()

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()
