from __future__ import annotations
from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Optional
from enum import Enum


class CabinClass(str, Enum):
    ECONOMY = "ECONOMY"
    PREMIUM_ECONOMY = "PREMIUM_ECONOMY"
    BUSINESS = "BUSINESS"
    FIRST = "FIRST"

    def label(self) -> str:
        labels = {
            "ECONOMY": "Econômica",
            "PREMIUM_ECONOMY": "Prem. Econômica",
            "BUSINESS": "Executiva",
            "FIRST": "Primeira Classe",
        }
        return labels.get(self.value, self.value)


class TripType(str, Enum):
    ONE_WAY = "one_way"
    ROUND_TRIP = "round_trip"


class PriceTrend(str, Enum):
    UP = "up"
    DOWN = "down"
    STABLE = "stable"
    ASYMMETRIC = "asymmetric"  # preço abaixo do esperado = oportunidade


@dataclass
class Airport:
    iata: str
    name: str
    city: str
    country: str

    def display(self) -> str:
        return f"{self.iata} – {self.city}"


@dataclass
class SearchParams:
    origin: str
    destination: str
    departure_date: date
    return_date: Optional[date] = None
    adults: int = 1
    children: int = 0
    infants: int = 0
    cabin_class: CabinClass = CabinClass.ECONOMY
    trip_type: TripType = TripType.ROUND_TRIP
    max_budget: Optional[float] = None
    direct_only: bool = False
    include_baggage: bool = False
    currency: str = "BRL"
    customer_profile: str = ""  # preferences/context for AI analysis


@dataclass
class FlightSegment:
    origin: str
    destination: str
    departure: datetime
    arrival: datetime
    carrier: str
    carrier_name: str
    flight_number: str
    duration_minutes: int
    stops: int = 0

    def duration_fmt(self) -> str:
        h, m = divmod(self.duration_minutes, 60)
        return f"{h}h{m:02d}m"


@dataclass
class FlightOffer:
    id: str
    outbound: list[FlightSegment]
    inbound: list[FlightSegment]
    price: float
    currency: str
    cabin: CabinClass
    seats_left: int
    baggage_included: bool
    price_trend: PriceTrend = PriceTrend.STABLE
    avg_market_price: float = 0.0
    price_vs_avg_pct: float = 0.0  # negative = cheaper than avg
    is_deal: bool = False
    deal_score: int = 0  # 0-100, higher = better deal

    @property
    def main_carrier(self) -> str:
        return self.outbound[0].carrier_name if self.outbound else "?"

    @property
    def total_stops(self) -> int:
        return sum(s.stops for s in self.outbound)

    @property
    def total_duration_out(self) -> int:
        return sum(s.duration_minutes for s in self.outbound)

    def price_fmt(self) -> str:
        sym = "R$" if self.currency == "BRL" else self.currency
        return f"{sym} {self.price:,.2f}"

    def trend_icon(self) -> str:
        icons = {
            PriceTrend.UP: "↑",
            PriceTrend.DOWN: "↓",
            PriceTrend.STABLE: "→",
            PriceTrend.ASYMMETRIC: "★",
        }
        return icons.get(self.price_trend, "?")

    def deal_badge(self) -> str:
        if self.deal_score >= 80:
            return "🔥 OFERTA IMPERDÍVEL"
        if self.deal_score >= 60:
            return "✨ ÓTIMO PREÇO"
        if self.deal_score >= 40:
            return "👍 BOM NEGÓCIO"
        return ""


@dataclass
class HotelOffer:
    id: str
    name: str
    city: str
    stars: int
    check_in: date
    check_out: date
    room_type: str
    price_per_night: float
    total_price: float
    currency: str
    breakfast_included: bool
    cancellation_policy: str
    rating: float  # 0-10
    review_count: int
    price_trend: PriceTrend = PriceTrend.STABLE
    avg_market_price: float = 0.0
    price_vs_avg_pct: float = 0.0
    deal_score: int = 0

    @property
    def nights(self) -> int:
        return (self.check_out - self.check_in).days

    def price_fmt(self) -> str:
        sym = "R$" if self.currency == "BRL" else self.currency
        return f"{sym} {self.total_price:,.2f}"

    def stars_fmt(self) -> str:
        return "★" * self.stars + "☆" * (5 - self.stars)


@dataclass
class PricePoint:
    date: date
    price: float
    source: str = "amadeus"


@dataclass
class PriceHistory:
    route: str  # "GRU-CDG"
    cabin: CabinClass
    points: list[PricePoint] = field(default_factory=list)

    @property
    def current_price(self) -> float:
        return self.points[-1].price if self.points else 0.0

    @property
    def min_price(self) -> float:
        return min(p.price for p in self.points) if self.points else 0.0

    @property
    def max_price(self) -> float:
        return max(p.price for p in self.points) if self.points else 0.0

    @property
    def avg_price(self) -> float:
        if not self.points:
            return 0.0
        return sum(p.price for p in self.points) / len(self.points)

    def trend(self) -> PriceTrend:
        if len(self.points) < 3:
            return PriceTrend.STABLE
        recent = self.points[-3:]
        avg_recent = sum(p.price for p in recent) / 3
        if self.current_price < avg_recent * 0.93:
            return PriceTrend.ASYMMETRIC
        if self.current_price > avg_recent * 1.05:
            return PriceTrend.UP
        if self.current_price < avg_recent * 0.98:
            return PriceTrend.DOWN
        return PriceTrend.STABLE


@dataclass
class MilesConnection:
    origin: str
    destination: str
    departure: datetime
    arrival: datetime
    carrier: str
    flight_number: str
    duration_minutes: int


@dataclass
class MilesOffer:
    """Oferta de voo em milhas via BuscaMilhas API."""
    company: str               # GOL, AZUL, LATAM, TAP, IBERIA, etc.
    flight_number: str
    direction: int             # 1 = ida, 2 = volta
    origin: str
    destination: str
    departure: datetime
    arrival: datetime
    duration_minutes: int
    connections: int
    connection_list: list[MilesConnection] = field(default_factory=list)

    # Valores em milhas
    miles_adult: float = 0.0
    miles_child: float = 0.0
    miles_infant: float = 0.0
    total_miles_adult: float = 0.0
    total_miles_child: float = 0.0
    total_miles_infant: float = 0.0

    # Taxas (sempre em dinheiro, BRL)
    fee_adult: float = 0.0      # TaxaEmbarque unitário
    fee_child: float = 0.0
    fee_infant: float = 0.0
    rescue_fee: float = 0.0     # TaxaResgate (Azul)

    # Tipo de cabine conforme denominação da companhia
    miles_type: str = ""        # TipoMilhas: smiles, Economy, LIGHT ECONOMY…
    value_type: str = ""        # TipoValor: PO, LT, Azul, Mais Azul…

    # Bagagem
    baggage_limit: str = ""

    # Metadados
    is_miles: bool = True       # True = resultado em milhas, False = pagante

    @property
    def duration_fmt(self) -> str:
        h, m = divmod(self.duration_minutes, 60)
        return f"{h}h{m:02d}m"

    @property
    def direct(self) -> bool:
        return self.connections == 0

    def miles_fmt(self, miles: float) -> str:
        if miles >= 1_000:
            return f"{miles:,.0f} pts"
        return f"{miles:.0f} pts"

    def fee_fmt(self, fee: float) -> str:
        return f"R$ {fee:,.2f}"

    def label_direction(self) -> str:
        return "IDA" if self.direction == 1 else "VOLTA"


@dataclass
class SearchResult:
    params: SearchParams
    flights: list[FlightOffer] = field(default_factory=list)
    hotels: list[HotelOffer] = field(default_factory=list)
    miles_offers: list[MilesOffer] = field(default_factory=list)
    price_history: Optional[PriceHistory] = None
    ai_analysis: str = ""
    search_time_ms: int = 0
    is_demo: bool = False

    @property
    def best_flight(self) -> Optional[FlightOffer]:
        if not self.flights:
            return None
        return min(self.flights, key=lambda f: f.price)

    @property
    def asymmetric_flights(self) -> list[FlightOffer]:
        return [f for f in self.flights if f.price_trend == PriceTrend.ASYMMETRIC]

    @property
    def best_miles_offer(self) -> Optional[MilesOffer]:
        outbound = [o for o in self.miles_offers if o.direction == 1 and o.is_miles]
        if not outbound:
            return None
        return min(outbound, key=lambda o: o.total_miles_adult or o.miles_adult)


# Known airports for autocomplete
AIRPORTS: dict[str, Airport] = {
    "GRU": Airport("GRU", "Guarulhos Intl.", "São Paulo", "Brasil"),
    "GIG": Airport("GIG", "Galeão Intl.", "Rio de Janeiro", "Brasil"),
    "BSB": Airport("BSB", "Pres. Juscelino K.", "Brasília", "Brasil"),
    "SSA": Airport("SSA", "Dep. Luís E. M.", "Salvador", "Brasil"),
    "FOR": Airport("FOR", "Pinto Martins", "Fortaleza", "Brasil"),
    "REC": Airport("REC", "Guararapes", "Recife", "Brasil"),
    "POA": Airport("POA", "Salgado Filho", "Porto Alegre", "Brasil"),
    "MAO": Airport("MAO", "Eduardo Gomes", "Manaus", "Brasil"),
    "BEL": Airport("BEL", "Val-de-Cans", "Belém", "Brasil"),
    "CWB": Airport("CWB", "Afonso Pena", "Curitiba", "Brasil"),
    "CDG": Airport("CDG", "Charles de Gaulle", "Paris", "França"),
    "LHR": Airport("LHR", "Heathrow", "Londres", "Reino Unido"),
    "JFK": Airport("JFK", "John F. Kennedy", "Nova York", "EUA"),
    "MIA": Airport("MIA", "Miami Intl.", "Miami", "EUA"),
    "MAD": Airport("MAD", "Barajas", "Madrid", "Espanha"),
    "LIS": Airport("LIS", "Humberto Delgado", "Lisboa", "Portugal"),
    "FCO": Airport("FCO", "Leonardo da Vinci", "Roma", "Itália"),
    "AMS": Airport("AMS", "Schiphol", "Amsterdam", "Holanda"),
    "FRA": Airport("FRA", "Frankfurt Main", "Frankfurt", "Alemanha"),
    "EZE": Airport("EZE", "Ezeiza Intl.", "Buenos Aires", "Argentina"),
    "SCL": Airport("SCL", "Comodoro A.", "Santiago", "Chile"),
    "BOG": Airport("BOG", "El Dorado", "Bogotá", "Colômbia"),
    "DXB": Airport("DXB", "Dubai Intl.", "Dubai", "EAU"),
    "NRT": Airport("NRT", "Narita", "Tóquio", "Japão"),
    "SYD": Airport("SYD", "Kingsford Smith", "Sydney", "Austrália"),
    "ORD": Airport("ORD", "O'Hare Intl.", "Chicago", "EUA"),
    "LAX": Airport("LAX", "Los Angeles Intl.", "Los Angeles", "EUA"),
    "MXP": Airport("MXP", "Malpensa", "Milão", "Itália"),
    "BCN": Airport("BCN", "El Prat", "Barcelona", "Espanha"),
    "YYZ": Airport("YYZ", "Pearson Intl.", "Toronto", "Canadá"),
    "ORU": Airport("ORU", "Juan Mendoza", "Oruro", "Bolívia"),
    "CUN": Airport("CUN", "Cancún Intl.", "Cancún", "México"),
    "MXP": Airport("MXP", "Malpensa", "Milão", "Itália"),
}
