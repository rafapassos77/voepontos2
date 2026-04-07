"""
Gerador de dados mock realistas para modo demo.
Simula padrões reais de preços de passagens aéreas brasileiras.
"""
from __future__ import annotations
import random
import math
from datetime import date, datetime, timedelta
from typing import Optional

from src.models import (
    FlightOffer, FlightSegment, HotelOffer, PriceHistory, PricePoint,
    PriceTrend, CabinClass, SearchParams, AIRPORTS
)

# ─── Companhias aéreas brasileiras e internacionais ───────────────────────────
AIRLINES = {
    "LA": "LATAM",
    "G3": "GOL",
    "AD": "Azul",
    "TP": "TAP Air Portugal",
    "AA": "American Airlines",
    "AF": "Air France",
    "KL": "KLM",
    "IB": "Iberia",
    "BA": "British Airways",
    "LH": "Lufthansa",
    "UA": "United Airlines",
    "DL": "Delta Air Lines",
    "EK": "Emirates",
    "NH": "ANA",
    "LX": "Swiss",
}

# ─── Rotas com preços base e duração (minutos) ─────────────────────────────────
ROUTES: dict[str, dict] = {
    "GRU-CDG": {"base": 4500, "duration": 690, "carriers": ["LA", "AF", "TP", "AA"], "stops_prob": 0.3},
    "GRU-LHR": {"base": 4800, "duration": 720, "carriers": ["LA", "BA", "TP", "KL"], "stops_prob": 0.4},
    "GRU-JFK": {"base": 4200, "duration": 660, "carriers": ["LA", "AA", "DL", "UA"], "stops_prob": 0.35},
    "GRU-MIA": {"base": 3200, "duration": 570, "carriers": ["LA", "AA", "G3", "AD"], "stops_prob": 0.2},
    "GRU-MAD": {"base": 4100, "duration": 660, "carriers": ["LA", "IB", "TP", "AF"], "stops_prob": 0.3},
    "GRU-LIS": {"base": 3900, "duration": 630, "carriers": ["LA", "TP", "BA"], "stops_prob": 0.2},
    "GRU-FCO": {"base": 4600, "duration": 720, "carriers": ["LA", "AF", "LH", "IB"], "stops_prob": 0.5},
    "GRU-AMS": {"base": 4700, "duration": 720, "carriers": ["KL", "LA", "LH", "AF"], "stops_prob": 0.4},
    "GRU-FRA": {"base": 4300, "duration": 690, "carriers": ["LH", "LA", "LX", "AF"], "stops_prob": 0.4},
    "GRU-DXB": {"base": 5800, "duration": 810, "carriers": ["EK", "LA", "AF"], "stops_prob": 0.6},
    "GRU-NRT": {"base": 7200, "duration": 1020, "carriers": ["NH", "LA", "DL"], "stops_prob": 0.7},
    "GRU-SYD": {"base": 8500, "duration": 1380, "carriers": ["EK", "LA", "NH"], "stops_prob": 0.8},
    "GRU-LAX": {"base": 5100, "duration": 870, "carriers": ["LA", "AA", "DL", "UA"], "stops_prob": 0.5},
    "GRU-EZE": {"base": 1200, "duration": 150, "carriers": ["LA", "G3", "AD"], "stops_prob": 0.1},
    "GRU-SCL": {"base": 1400, "duration": 180, "carriers": ["LA", "G3", "AD"], "stops_prob": 0.1},
    "GIG-CDG": {"base": 4600, "duration": 705, "carriers": ["LA", "AF", "TP"], "stops_prob": 0.4},
    "GIG-LIS": {"base": 4000, "duration": 645, "carriers": ["LA", "TP"], "stops_prob": 0.25},
    "GIG-MIA": {"base": 3400, "duration": 570, "carriers": ["LA", "AA"], "stops_prob": 0.3},
    "FOR-LIS": {"base": 3200, "duration": 480, "carriers": ["TP", "LA"], "stops_prob": 0.2},
    "REC-LIS": {"base": 3100, "duration": 450, "carriers": ["TP", "LA"], "stops_prob": 0.2},
    "BSB-CDG": {"base": 4700, "duration": 720, "carriers": ["LA", "AF", "TP"], "stops_prob": 0.5},
    "POA-MAD": {"base": 4300, "duration": 690, "carriers": ["LA", "IB", "TP"], "stops_prob": 0.4},
    "CWB-JFK": {"base": 4500, "duration": 720, "carriers": ["LA", "AA"], "stops_prob": 0.5},
    "GRU-ORD": {"base": 4800, "duration": 810, "carriers": ["UA", "AA", "LA"], "stops_prob": 0.5},
    "GRU-YYZ": {"base": 4900, "duration": 840, "carriers": ["LA", "AA", "AC"], "stops_prob": 0.5},
    "GRU-BCN": {"base": 4400, "duration": 720, "carriers": ["LA", "IB", "VY"], "stops_prob": 0.4},
    "GRU-CUN": {"base": 3600, "duration": 600, "carriers": ["LA", "AA"], "stops_prob": 0.35},
}

# Multiplicadores de preço por cabine
CABIN_MULTIPLIERS = {
    CabinClass.ECONOMY: 1.0,
    CabinClass.PREMIUM_ECONOMY: 1.8,
    CabinClass.BUSINESS: 4.5,
    CabinClass.FIRST: 9.0,
}

# Multiplicadores por dia da semana (seg=0 ... dom=6)
DOW_MULTIPLIERS = [1.02, 0.92, 0.90, 0.95, 1.08, 1.12, 1.05]

# Hotéis por cidade
HOTEL_TEMPLATES: dict[str, list[dict]] = {
    "Paris": [
        {"name": "Le Grand Hôtel", "stars": 5, "base_rate": 980, "rating": 9.1},
        {"name": "Mercure Opéra", "stars": 4, "base_rate": 620, "rating": 8.3},
        {"name": "Ibis Paris Centre", "stars": 3, "base_rate": 320, "rating": 7.8},
        {"name": "CitizenM Paris", "stars": 4, "base_rate": 450, "rating": 8.7},
    ],
    "Londres": [
        {"name": "The Savoy", "stars": 5, "base_rate": 1200, "rating": 9.4},
        {"name": "Premier Inn City", "stars": 3, "base_rate": 380, "rating": 8.0},
        {"name": "Hilton Canary Wharf", "stars": 4, "base_rate": 680, "rating": 8.5},
    ],
    "Nova York": [
        {"name": "The Plaza Hotel", "stars": 5, "base_rate": 1500, "rating": 9.2},
        {"name": "Pod 51 Hotel", "stars": 3, "base_rate": 420, "rating": 8.1},
        {"name": "Marriott Times Square", "stars": 4, "base_rate": 750, "rating": 8.4},
        {"name": "Ace Hotel NYC", "stars": 4, "base_rate": 560, "rating": 8.6},
    ],
    "Miami": [
        {"name": "Faena Hotel", "stars": 5, "base_rate": 900, "rating": 9.0},
        {"name": "Loews Miami Beach", "stars": 4, "base_rate": 580, "rating": 8.3},
        {"name": "Hampton Inn South Beach", "stars": 3, "base_rate": 350, "rating": 7.9},
    ],
    "Madrid": [
        {"name": "Hotel Ritz Madrid", "stars": 5, "base_rate": 850, "rating": 9.3},
        {"name": "NH Gran Vía", "stars": 4, "base_rate": 420, "rating": 8.2},
        {"name": "Hospes Puerta Alcalá", "stars": 5, "base_rate": 720, "rating": 9.0},
    ],
    "Lisboa": [
        {"name": "Bairro Alto Hotel", "stars": 5, "base_rate": 680, "rating": 9.1},
        {"name": "Memmo Alfama", "stars": 4, "base_rate": 380, "rating": 8.6},
        {"name": "HF Fénix Garden", "stars": 4, "base_rate": 290, "rating": 8.0},
    ],
    "Roma": [
        {"name": "Hotel de Russie", "stars": 5, "base_rate": 920, "rating": 9.2},
        {"name": "NH Collection Roma", "stars": 4, "base_rate": 480, "rating": 8.4},
        {"name": "Generator Rome", "stars": 3, "base_rate": 180, "rating": 8.1},
    ],
    "Dubai": [
        {"name": "Burj Al Arab", "stars": 5, "base_rate": 3500, "rating": 9.6},
        {"name": "Atlantis The Palm", "stars": 5, "base_rate": 1200, "rating": 9.0},
        {"name": "Ibis Dubai Mall", "stars": 3, "base_rate": 280, "rating": 7.8},
    ],
}


def _get_city_for_iata(iata: str) -> str:
    a = AIRPORTS.get(iata)
    return a.city if a else iata


def _price_with_noise(base: float, noise_pct: float = 0.15) -> float:
    factor = 1.0 + random.uniform(-noise_pct, noise_pct)
    return round(base * factor, 2)


def _advance_purchase_factor(departure: date, today: date) -> float:
    """Quanto mais antecipado, geralmente mais barato (até certo ponto)."""
    days_ahead = (departure - today).days
    if days_ahead <= 0:
        return 1.4
    if days_ahead <= 7:
        return 1.35
    if days_ahead <= 14:
        return 1.20
    if days_ahead <= 30:
        return 1.05
    if days_ahead <= 60:
        return 0.95
    if days_ahead <= 90:
        return 0.92
    if days_ahead <= 180:
        return 0.98
    return 1.10


def _make_flight_segment(
    origin: str,
    destination: str,
    departure: datetime,
    carrier: str,
    duration: int,
    stops: int,
) -> FlightSegment:
    arrival = departure + timedelta(minutes=duration)
    flight_num = f"{carrier}{random.randint(100, 9999)}"
    return FlightSegment(
        origin=origin,
        destination=destination,
        departure=departure,
        arrival=arrival,
        carrier=carrier,
        carrier_name=AIRLINES.get(carrier, carrier),
        flight_number=flight_num,
        duration_minutes=duration,
        stops=stops,
    )


def generate_flights(params: SearchParams) -> list[FlightOffer]:
    route_key = f"{params.origin}-{params.destination}"
    route_info = ROUTES.get(route_key)

    # Try reverse if direct route not found
    if not route_info:
        route_key = f"{params.destination}-{params.origin}"
        route_info = ROUTES.get(route_key)

    if not route_info:
        # Generic fallback
        route_info = {
            "base": 3500,
            "duration": 600,
            "carriers": ["LA", "G3", "AA"],
            "stops_prob": 0.4,
        }

    today = date.today()
    cabin_mult = CABIN_MULTIPLIERS[params.cabin_class]
    dow_mult = DOW_MULTIPLIERS[params.departure_date.weekday()]
    advance_mult = _advance_purchase_factor(params.departure_date, today)
    pax_mult = max(1.0, 0.9 + 0.1 * (params.adults + params.children))

    offers: list[FlightOffer] = []
    carriers = route_info["carriers"]

    # Calculate market average for asymmetry detection
    base_market = route_info["base"] * cabin_mult * advance_mult

    num_offers = min(len(carriers) + random.randint(1, 3), 8)
    carrier_pool = (carriers * 3)[:num_offers]

    for i, carrier in enumerate(carrier_pool):
        # Each carrier has slightly different pricing
        carrier_factor = 1.0 + (i * 0.04) + random.uniform(-0.08, 0.08)
        price = route_info["base"] * cabin_mult * dow_mult * advance_mult * carrier_factor * pax_mult
        price = _price_with_noise(price, 0.08)

        # Occasionally inject asymmetric pricing (great deal)
        is_asymmetric = random.random() < 0.15
        if is_asymmetric:
            price *= random.uniform(0.75, 0.88)

        price = round(price, 2)
        pct_vs_avg = (price - base_market) / base_market * 100

        # Determine trend
        if is_asymmetric:
            trend = PriceTrend.ASYMMETRIC
        elif pct_vs_avg > 8:
            trend = PriceTrend.UP
        elif pct_vs_avg < -5:
            trend = PriceTrend.DOWN
        else:
            trend = PriceTrend.STABLE

        # Deal score
        deal_score = 0
        if pct_vs_avg < -15:
            deal_score = random.randint(75, 95)
        elif pct_vs_avg < -8:
            deal_score = random.randint(50, 74)
        elif pct_vs_avg < -3:
            deal_score = random.randint(30, 49)

        # Build flight segments
        dep_dt = datetime.combine(params.departure_date, datetime.min.time().replace(
            hour=random.choice([6, 8, 10, 13, 15, 18, 21]),
            minute=random.choice([0, 15, 30, 45]),
        ))

        has_stop = random.random() < route_info["stops_prob"]
        stops = 1 if has_stop else 0
        duration_mod = route_info["duration"] + (stops * random.randint(60, 150))

        outbound = [_make_flight_segment(
            params.origin, params.destination, dep_dt, carrier, duration_mod, stops
        )]

        inbound: list[FlightSegment] = []
        if params.return_date:
            ret_dep = datetime.combine(params.return_date, datetime.min.time().replace(
                hour=random.choice([7, 9, 12, 16, 19]),
                minute=random.choice([0, 20, 40]),
            ))
            inbound = [_make_flight_segment(
                params.destination, params.origin, ret_dep, carrier,
                duration_mod + random.randint(-30, 60), stops
            )]
            price *= 1.9  # approximate round trip

        offer = FlightOffer(
            id=f"DEMO-{carrier}-{i:03d}",
            outbound=outbound,
            inbound=inbound,
            price=price,
            currency=params.currency,
            cabin=params.cabin_class,
            seats_left=random.randint(1, 9),
            baggage_included=random.random() > 0.5,
            price_trend=trend,
            avg_market_price=base_market,
            price_vs_avg_pct=pct_vs_avg,
            is_deal=deal_score >= 50,
            deal_score=deal_score,
        )
        offers.append(offer)

    # Sort by price
    offers.sort(key=lambda o: o.price)
    return offers


def generate_hotels(params: SearchParams) -> list[HotelOffer]:
    if not params.return_date:
        return []

    dest_airport = AIRPORTS.get(params.destination)
    city = dest_airport.city if dest_airport else params.destination

    # Find hotels for destination city
    hotel_list = HOTEL_TEMPLATES.get(city, [])
    if not hotel_list:
        # Fallback generic hotels
        hotel_list = [
            {"name": f"Grand Hotel {city}", "stars": 4, "base_rate": 500, "rating": 8.2},
            {"name": f"City Inn {city}", "stars": 3, "base_rate": 280, "rating": 7.6},
            {"name": f"Boutique {city} Suites", "stars": 4, "base_rate": 420, "rating": 8.5},
        ]

    nights = (params.return_date - params.departure_date).days
    if nights <= 0:
        nights = 3

    offers: list[HotelOffer] = []
    for tmpl in hotel_list:
        rate = tmpl["base_rate"] * random.uniform(0.85, 1.20)
        total = round(rate * nights, 2)
        pct_vs_avg = random.uniform(-20, 20)

        trend = PriceTrend.STABLE
        if pct_vs_avg < -12:
            trend = PriceTrend.ASYMMETRIC
        elif pct_vs_avg > 10:
            trend = PriceTrend.UP
        elif pct_vs_avg < -5:
            trend = PriceTrend.DOWN

        deal_score = max(0, int(-pct_vs_avg * 3))

        room_types = ["Standard", "Superior", "Deluxe", "Suite Junior", "Suite"]
        room_type = room_types[min(tmpl["stars"] - 1, len(room_types) - 1)]

        policies = [
            "Cancelamento gratuito até 24h antes",
            "Cancelamento gratuito até 48h antes",
            "Não reembolsável",
            "Cancelamento gratuito até 7 dias antes",
        ]

        offers.append(HotelOffer(
            id=f"HTL-{len(offers):03d}",
            name=tmpl["name"],
            city=city,
            stars=tmpl["stars"],
            check_in=params.departure_date,
            check_out=params.return_date,
            room_type=room_type,
            price_per_night=round(rate, 2),
            total_price=total,
            currency=params.currency,
            breakfast_included=random.random() > 0.5,
            cancellation_policy=random.choice(policies),
            rating=tmpl["rating"] + random.uniform(-0.3, 0.3),
            review_count=random.randint(200, 5000),
            price_trend=trend,
            avg_market_price=tmpl["base_rate"] * nights,
            price_vs_avg_pct=pct_vs_avg,
            deal_score=min(100, deal_score),
        ))

    offers.sort(key=lambda h: h.total_price)
    return offers


def generate_price_history(
    origin: str,
    destination: str,
    cabin: CabinClass,
    days: int = 30,
) -> PriceHistory:
    route_key = f"{origin}-{destination}"
    route_info = ROUTES.get(route_key) or ROUTES.get(f"{destination}-{origin}")
    base = (route_info["base"] if route_info else 3500) * CABIN_MULTIPLIERS[cabin]

    today = date.today()
    points: list[PricePoint] = []

    # Simulate a realistic price curve with occasional dips and spikes
    price = base * random.uniform(0.92, 1.08)
    for i in range(days):
        d = today - timedelta(days=days - i - 1)
        # Random walk with mean reversion
        delta = random.gauss(0, base * 0.03)
        price = price + delta
        price = max(base * 0.6, min(base * 1.5, price))  # clamp
        # Occasional promotional dip
        if random.random() < 0.05:
            price *= random.uniform(0.80, 0.90)
        # Weekend spikes
        if d.weekday() in (4, 5):
            price *= 1.04
        points.append(PricePoint(date=d, price=round(price, 2), source="demo"))

    return PriceHistory(
        route=route_key,
        cabin=cabin,
        points=points,
    )
