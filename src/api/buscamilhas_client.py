"""
Cliente da API BuscaMilhas (http://apiv2.buscamilhas.com)
Busca passagens aéreas emitidas com milhas de múltiplas companhias.
"""
from __future__ import annotations
import asyncio
from datetime import datetime
from typing import Optional

import httpx

from src.config import Config
from src.models import MilesOffer, MilesConnection, CabinClass, TripType, SearchParams


# ─── Credenciais ──────────────────────────────────────────────────────────────
BUSCAMILHAS_ENDPOINT = "http://apiv2.buscamilhas.com"
BUSCAMILHAS_CHAVE = "592e006ac74407ba20bafd01185c74d3"
BUSCAMILHAS_SENHA = "d9af15431d6c3d7992827b6364cd43a9"

# Companhias suportadas (uma por requisição)
SUPPORTED_AIRLINES = ["GOL", "AZUL", "LATAM", "TAP", "IBERIA", "AMERICAN"]

# Mapeamento de cabine para o formato da API
CABIN_MAP = {
    CabinClass.ECONOMY: "economica",
    CabinClass.PREMIUM_ECONOMY: "economica",
    CabinClass.BUSINESS: "executiva",
    CabinClass.FIRST: "executiva",
}


def _fmt_date(d) -> str:
    """Formata data para DD/MM/AAAA conforme exigido pela API."""
    return d.strftime("%d/%m/%Y")


def _parse_dt(s: str) -> Optional[datetime]:
    """Tenta parsear datetime vindo da API (vários formatos possíveis)."""
    if not s:
        return None
    for fmt in (
        "%Y-%m-%dT%H:%M:%S",
        "%Y-%m-%dT%H:%M:%SZ",
        "%Y-%m-%d %H:%M:%S",
        "%d/%m/%Y %H:%M",
        "%d/%m/%Y %H:%M:%S",
    ):
        try:
            return datetime.strptime(s, fmt)
        except ValueError:
            continue
    return None


def _safe_float(val) -> float:
    """Converte para float de forma segura."""
    try:
        return float(str(val).replace(",", ".").strip())
    except (ValueError, TypeError):
        return 0.0


class BuscaMilhasClient:
    """Busca passagens em milhas para múltiplas companhias em paralelo."""

    def __init__(self) -> None:
        self._client = httpx.AsyncClient(
            timeout=httpx.Timeout(30.0, connect=10.0),
        )

    async def search(
        self,
        params: SearchParams,
        airlines: Optional[list[str]] = None,
        only_miles: bool = True,
    ) -> list[MilesOffer]:
        """
        Busca em todas as companhias em paralelo e consolida os resultados.

        Args:
            params: Parâmetros da busca (origem, destino, datas, etc.)
            airlines: Lista de companhias a buscar (default = todas suportadas)
            only_miles: True = apenas milhas, False = milhas + pagante
        """
        targets = airlines or SUPPORTED_AIRLINES
        tasks = [
            self._search_airline(params, airline, only_miles)
            for airline in targets
        ]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        offers: list[MilesOffer] = []
        for r in results:
            if isinstance(r, list):
                offers.extend(r)

        # Ordenar: ida primeiro, por milhas crescente
        offers.sort(key=lambda o: (o.direction, o.total_miles_adult or o.miles_adult))
        return offers

    async def _search_airline(
        self,
        params: SearchParams,
        airline: str,
        only_miles: bool,
    ) -> list[MilesOffer]:
        """Faz a requisição para uma companhia e parseia os resultados."""
        cabin = CABIN_MAP.get(params.cabin_class, "economica")
        tipo_viagem = 1 if params.return_date else 0

        payload: dict = {
            "Companhias": [airline],
            "TipoViagem": tipo_viagem,
            "Trechos": [
                {
                    "Origem": params.origin,
                    "Destino": params.destination,
                    "DataIda": _fmt_date(params.departure_date),
                }
            ],
            "Classe": cabin,
            "Adultos": params.adults,
            "Criancas": params.children,
            "Bebes": params.infants,
            "Chave": BUSCAMILHAS_CHAVE,
            "Senha": BUSCAMILHAS_SENHA,
            "SomenteMilhas": only_miles,
            "SomentePagante": False,
        }

        if params.return_date:
            payload["Trechos"][0]["DataVolta"] = _fmt_date(params.return_date)

        try:
            resp = await self._client.post(BUSCAMILHAS_ENDPOINT, json=payload)
            resp.raise_for_status()
            data = resp.json()
        except httpx.TimeoutException:
            return []
        except httpx.HTTPStatusError:
            return []
        except Exception:
            return []

        # Verify status
        status = data.get("Status", {})
        if status.get("Erro") or not status.get("Sucesso"):
            return []

        trechos = data.get("Trechos", {})
        offers: list[MilesOffer] = []

        for trecho_key, trecho in trechos.items():
            voos = trecho.get("Voos", [])
            for voo in voos:
                offer = self._parse_voo(voo, airline, only_miles)
                if offer:
                    offers.append(offer)

        return offers

    def _parse_voo(
        self, voo: dict, airline: str, only_miles: bool
    ) -> Optional[MilesOffer]:
        """Converte um objeto Voo da API para MilesOffer."""
        try:
            departure = _parse_dt(voo.get("Embarque", ""))
            arrival = _parse_dt(voo.get("Desembarque", ""))

            if not departure or not arrival:
                return None

            duration_raw = voo.get("Duracao", "")
            duration_min = self._parse_duration(duration_raw)

            # Parse connections
            conn_list: list[MilesConnection] = []
            for c in voo.get("Conexoes", []) or []:
                c_dep = _parse_dt(c.get("Embarque", ""))
                c_arr = _parse_dt(c.get("Desembarque", ""))
                if c_dep and c_arr:
                    conn_list.append(MilesConnection(
                        origin=c.get("Origem", ""),
                        destination=c.get("Destino", ""),
                        departure=c_dep,
                        arrival=c_arr,
                        carrier=c.get("Companhia", airline),
                        flight_number=str(c.get("NumeroVoo", "")),
                        duration_minutes=int((c_arr - c_dep).total_seconds() / 60),
                    ))

            # Miles values
            miles_adult = _safe_float(voo.get("Adulto", 0))
            miles_child = _safe_float(voo.get("Crianca", 0))
            miles_infant = _safe_float(voo.get("Bebe", 0))
            total_adult = _safe_float(voo.get("TotalAdulto", 0)) or miles_adult
            total_child = _safe_float(voo.get("TotalCrianca", 0)) or miles_child
            total_infant = _safe_float(voo.get("TotalBebe", 0)) or miles_infant

            # Airport fee
            fee_raw = voo.get("TaxaEmbarqueFaixaEtaria", {}) or {}
            fee_adult = _safe_float(fee_raw.get("Adulto", voo.get("TaxaEmbarque", 0)))
            fee_child = _safe_float(fee_raw.get("Crianca", 0))
            fee_infant = _safe_float(fee_raw.get("Bebe", 0))
            rescue_fee = _safe_float(voo.get("TaxaResgate", 0))

            # Baggage
            baggage = str(voo.get("LimiteBagagem", "")) if voo.get("LimiteBagagem") is not None else ""

            return MilesOffer(
                company=voo.get("Companhia", airline),
                flight_number=str(voo.get("NumeroVoo", "")),
                direction=int(voo.get("Sentido", 1)),
                origin=voo.get("Origem", ""),
                destination=voo.get("Destino", ""),
                departure=departure,
                arrival=arrival,
                duration_minutes=duration_min,
                connections=int(voo.get("NumeroConexoes", len(conn_list))),
                connection_list=conn_list,
                miles_adult=miles_adult,
                miles_child=miles_child,
                miles_infant=miles_infant,
                total_miles_adult=total_adult,
                total_miles_child=total_child,
                total_miles_infant=total_infant,
                fee_adult=fee_adult,
                fee_child=fee_child,
                fee_infant=fee_infant,
                rescue_fee=rescue_fee,
                miles_type=str(voo.get("TipoMilhas", "")),
                value_type=str(voo.get("TipoValor", "")),
                baggage_limit=baggage,
                is_miles=only_miles,
            )
        except Exception:
            return None

    def _parse_duration(self, raw) -> int:
        """Converte duração para minutos. Aceita 'HH:MM', minutos int, ou string."""
        if not raw:
            return 0
        if isinstance(raw, (int, float)):
            return int(raw)
        s = str(raw).strip()
        # HH:MM or HH:MM:SS
        if ":" in s:
            parts = s.split(":")
            try:
                h = int(parts[0])
                m = int(parts[1])
                return h * 60 + m
            except (ValueError, IndexError):
                return 0
        # Plain number string (minutes)
        try:
            return int(s)
        except ValueError:
            return 0

    async def close(self) -> None:
        await self._client.aclose()
