"""
FastAPI server — backend web para o VoePontos.
Rotas: POST /api/search, GET /api/analyze (SSE), GET /api/recent-searches, GET /api/airports
"""
from __future__ import annotations

import dataclasses
import json
import uuid
from datetime import date, datetime
from enum import Enum
from typing import Any, Dict, Optional

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from sse_starlette.sse import EventSourceResponse

from src.agents.travel_agent import TravelAgent
from src.database.cache import PriceCache
from src.models import (
    AIRPORTS,
    CabinClass,
    SearchParams,
    SearchResult,
    TripType,
)
from src.services.search_service import SearchService, parse_date
from src.services.miles_pricing import get_engine as get_pricing_engine, reload_engine

# ── App ───────────────────────────────────────────────────────────────────────

app = FastAPI(title="VoePontos API", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# ── Singletons ────────────────────────────────────────────────────────────────

_cache = PriceCache()
_service = SearchService(cache=_cache)
_agent = TravelAgent()

# In-memory result store: search_id → SearchResult
_result_store: Dict[str, SearchResult] = {}


# ── Serialization ─────────────────────────────────────────────────────────────

def _serialize(obj: Any) -> Any:
    if isinstance(obj, (date, datetime)):
        return obj.isoformat()
    if isinstance(obj, Enum):
        return obj.value
    raise TypeError(f"Object of type {type(obj)} is not JSON serializable")


def result_to_dict(result: SearchResult) -> dict:
    return json.loads(json.dumps(dataclasses.asdict(result), default=_serialize))


# ── Request model ─────────────────────────────────────────────────────────────

class SearchRequest(BaseModel):
    origin: str
    destination: str
    departure_date: str
    return_date: Optional[str] = None
    adults: int = 1
    children: int = 0
    infants: int = 0
    cabin_class: str = "ECONOMY"
    max_budget: Optional[float] = None
    direct_only: bool = False
    include_baggage: bool = False
    customer_profile: str = ""


# ── Routes ────────────────────────────────────────────────────────────────────

@app.post("/api/search")
async def search(req: SearchRequest):
    dep_date = parse_date(req.departure_date)
    if not dep_date:
        raise HTTPException(status_code=400, detail="Data de ida inválida. Use DD/MM/YYYY ou YYYY-MM-DD.")

    ret_date = parse_date(req.return_date) if req.return_date else None

    try:
        cabin = CabinClass(req.cabin_class.upper())
    except ValueError:
        cabin = CabinClass.ECONOMY

    params = SearchParams(
        origin=req.origin.strip().upper(),
        destination=req.destination.strip().upper(),
        departure_date=dep_date,
        return_date=ret_date,
        adults=max(1, req.adults),
        children=max(0, req.children),
        infants=max(0, req.infants),
        cabin_class=cabin,
        trip_type=TripType.ROUND_TRIP if ret_date else TripType.ONE_WAY,
        max_budget=req.max_budget,
        direct_only=req.direct_only,
        include_baggage=req.include_baggage,
        customer_profile=req.customer_profile,
    )

    progress_log: list[str] = []

    def on_progress(msg: str) -> None:
        progress_log.append(msg)

    result = await _service.run_search(params, progress_callback=on_progress)

    search_id = str(uuid.uuid4())
    _result_store[search_id] = result

    # Keep store bounded (max 50 results)
    if len(_result_store) > 50:
        oldest_key = next(iter(_result_store))
        del _result_store[oldest_key]

    payload = result_to_dict(result)
    payload["search_id"] = search_id
    payload["progress_log"] = progress_log
    return payload


@app.get("/api/analyze")
async def analyze(search_id: str = Query(...)):
    result = _result_store.get(search_id)
    if not result:
        raise HTTPException(status_code=404, detail="search_id não encontrado. Faça uma busca primeiro.")

    async def event_generator():
        try:
            async for chunk in _agent.analyze_streaming(result):
                yield {"data": chunk}
        except Exception as exc:
            yield {"data": f"⚠️ Erro na análise: {str(exc)[:100]}"}
        yield {"data": "[DONE]"}

    return EventSourceResponse(event_generator())


@app.get("/api/recent-searches")
async def recent_searches(limit: int = Query(default=10, ge=1, le=50)):
    rows = await _cache.get_recent_searches(limit)
    return rows


@app.get("/api/airports")
async def airports():
    return {
        iata: {"name": a.name, "city": a.city, "country": a.country}
        for iata, a in AIRPORTS.items()
    }


# ── Coeficientes de precificação (admin) ──────────────────────────────────────

@app.get("/api/coefficients")
async def coefficients():
    """Retorna a tabela atual de coeficientes (milhas → R$)."""
    return get_pricing_engine().config


@app.post("/api/coefficients/reload")
async def coefficients_reload():
    """Recarrega coeficientes do disco sem reiniciar o servidor."""
    summary = reload_engine()
    return {"status": "ok", "summary": summary}


@app.post("/api/coefficients/simulate")
async def coefficients_simulate(payload: dict):
    """Simula precificação de uma oferta em milhas sem passar pela BuscaMilhas."""
    engine = get_pricing_engine()
    result = engine.price_miles(
        company=payload.get("company", ""),
        miles_total=float(payload.get("miles_total", 0)),
        fee_embarque=float(payload.get("fee_embarque", 0)),
        fee_resgate=float(payload.get("fee_resgate", 0)),
        miles_type=payload.get("miles_type", ""),
        value_type=payload.get("value_type", ""),
    )
    return {
        "estimated_brl": result.estimated_brl,
        "miles_converted_brl": result.miles_converted_brl,
        "fees_brl": result.fees_brl,
        "coefficient": result.coefficient,
        "coefficient_source": result.coefficient_source,
        "coefficient_configured": result.coefficient_configured,
        "calc_memory": result.calc_memory,
        "miles_total": result.miles_total,
    }


# ── Static files (MUST be last — catch-all) ───────────────────────────────────

import os as _os
_web_dir = _os.path.join(_os.path.dirname(_os.path.dirname(_os.path.dirname(__file__))), "web")
if _os.path.isdir(_web_dir):
    app.mount("/", StaticFiles(directory=_web_dir, html=True), name="static")
