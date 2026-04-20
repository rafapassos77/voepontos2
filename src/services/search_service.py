"""
SearchService — lógica de busca desacoplada do Textual.
Pode ser usada tanto pela TUI (app.py) quanto pelo servidor web (FastAPI).
"""
from __future__ import annotations

import re
from datetime import date, datetime
from typing import Callable, Optional

from src.config import Config
from src.database.cache import PriceCache
from src.models import (
    CabinClass,
    FlightOffer,
    PriceTrend,
    SearchParams,
    SearchResult,
    TripType,
)


def parse_date(raw: str) -> Optional[date]:
    """Parse date string in multiple formats: DD/MM/YYYY, YYYY-MM-DD, DD-MM-YYYY."""
    raw = raw.strip()
    if not raw:
        return None
    parts = re.split(r"[/\-\.]", raw)
    if len(parts) != 3:
        return None
    try:
        a, b, c = parts
        if len(c) == 4:
            # DD/MM/YYYY or DD-MM-YYYY
            return date(int(c), int(b), int(a))
        elif len(a) == 4:
            # YYYY-MM-DD
            return date(int(a), int(b), int(c))
        else:
            return None
    except (ValueError, TypeError):
        return None


class SearchService:
    """Serviço de busca de voos, milhas e hotéis."""

    def __init__(self, cache: Optional[PriceCache] = None) -> None:
        self._cache = cache or PriceCache()

    async def run_search(
        self,
        params: SearchParams,
        progress_callback: Optional[Callable[[str], None]] = None,
    ) -> SearchResult:
        """Executa busca completa: voos + hotéis (Amadeus/mock) + milhas (BuscaMilhas)."""
        from src.api.mock_data import (
            generate_flights,
            generate_hotels,
            generate_price_history,
        )

        def log(msg: str) -> None:
            if progress_callback:
                progress_callback(msg)

        is_demo = Config.is_demo_mode()

        # ── 1. Voos + Hotéis (Amadeus ou mock) ──────────────────────────────
        if is_demo:
            flights = generate_flights(params)
            hotels = generate_hotels(params)
            history = generate_price_history(
                params.origin, params.destination, params.cabin_class
            )
        else:
            try:
                from src.api.amadeus_client import AmadeusClient

                client = AmadeusClient()
                flights = await client.search_flights(params)
                hotels = await client.search_hotels(params)
                await client.close()
            except Exception:
                is_demo = True
                flights = generate_flights(params)
                hotels = generate_hotels(params)

            history = await self._cache.get_price_history(
                f"{params.origin}-{params.destination}",
                params.cabin_class,
            )
            if not history:
                history = generate_price_history(
                    params.origin, params.destination, params.cabin_class
                )

        # ── 2. Milhas (BuscaMilhas — sempre ativa) ───────────────────────────
        miles_offers: list = []
        try:
            from src.api.buscamilhas_client import BuscaMilhasClient

            bm = BuscaMilhasClient()
            log("🎯 Buscando milhas em GOL, AZUL, LATAM, TAP, IBERIA, AMERICAN...")
            miles_offers = await bm.search(params, only_miles=True)
            await bm.close()
            if miles_offers:
                log(f"✓ {len(miles_offers)} opção(ões) em milhas encontrada(s)")
            else:
                log("ℹ Nenhuma oferta em milhas disponível para esta rota/data")
        except Exception as exc:
            log(f"ℹ Milhas indisponíveis: {str(exc)[:80]}")

        # ── 3. Análise de mercado nos voos ───────────────────────────────────
        if flights:
            avg = sum(f.price for f in flights) / len(flights)
            for f in flights:
                f.avg_market_price = avg
                f.price_vs_avg_pct = (f.price - avg) / avg * 100

        return SearchResult(
            params=params,
            flights=flights,
            hotels=hotels,
            miles_offers=miles_offers,
            price_history=history,
            is_demo=is_demo,
        )
