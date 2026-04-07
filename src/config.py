from __future__ import annotations
import os
from pathlib import Path
from dotenv import load_dotenv

load_dotenv(Path(__file__).parent.parent / ".env")


class Config:
    ANTHROPIC_API_KEY: str = os.getenv("ANTHROPIC_API_KEY", "")
    AMADEUS_API_KEY: str = os.getenv("AMADEUS_API_KEY", "")
    AMADEUS_API_SECRET: str = os.getenv("AMADEUS_API_SECRET", "")
    AMADEUS_HOSTNAME: str = os.getenv("AMADEUS_HOSTNAME", "test")
    DEFAULT_CURRENCY: str = os.getenv("DEFAULT_CURRENCY", "BRL")
    APP_LANG: str = os.getenv("APP_LANG", "pt-BR")
    DB_PATH: Path = Path(__file__).parent.parent / "price_cache.db"

    @classmethod
    def is_demo_mode(cls) -> bool:
        env_flag = os.getenv("DEMO_MODE", "").lower()
        if env_flag == "true":
            return True
        if env_flag == "false":
            return False
        return not bool(cls.AMADEUS_API_KEY and cls.AMADEUS_API_SECRET)

    @classmethod
    def has_claude(cls) -> bool:
        return bool(cls.ANTHROPIC_API_KEY)

    @classmethod
    def amadeus_base_url(cls) -> str:
        if cls.AMADEUS_HOSTNAME == "production":
            return "https://api.amadeus.com"
        return "https://test.api.amadeus.com"
