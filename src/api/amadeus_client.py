"""
Cliente Amadeus API para busca de voos e hotéis em tempo real.
Documentação: https://developers.amadeus.com/
"""
from __future__ import annotations
import json
import asyncio
from datetime import date
from typing import Optional

import httpx

from src.config import Config
from src.models import (
    FlightOffer, FlightSegment, HotelOffer, PriceHistory, PricePoint,
    PriceTrend, CabinClass, SearchParams, AIRLINES,
)


class AmadeusAuthError(Exception):
    pass


class AmadeusClient:
    """Async client para a Amadeus Travel API."""

    def __init__(self) -> None:
        self._token: Optional[str] = None
        self._token_expiry: float = 0.0
        self._client = httpx.AsyncClient(timeout=30.0)

    async def _authenticate(self) -> str:
        import time
        if self._token and time.time() < self._token_expiry - 30:
            return self._token

        url = f"{Config.amadeus_base_url()}/v1/security/oauth2/token"
        resp = await self._client.post(
            url,
            data={
                "grant_type": "client_credentials",
                "client_id": Config.AMADEUS_API_KEY,
                "client_secret": Config.AMADEUS_API_SECRET,
            },
        )
        if resp.status_code != 200:
            raise AmadeusAuthError(f"Falha na autenticação Amadeus: {resp.text}")

        data = resp.json()
        self._token = data["access_token"]
        self._token_expiry = time.time() + data.get("expires_in", 1799)
        return self._token

    async def _get(self, path: str, params: dict) -> dict:
        token = await self._authenticate()
        url = f"{Config.amadeus_base_url()}{path}"
        resp = await self._client.get(
            url,
            params=params,
            headers={"Authorization": f"Bearer {token}"},
        )
        resp.raise_for_status()
        return resp.json()

    async def search_flights(self, params: SearchParams) -> list[FlightOffer]:
        query: dict = {
            "originLocationCode": params.origin,
            "destinationLocationCode": params.destination,
            "departureDate": params.departure_date.isoformat(),
            "adults": params.adults,
            "travelClass": params.cabin_class.value,
            "max": 20,
            "currencyCode": params.currency,
        }
        if params.return_date:
            query["returnDate"] = params.return_date.isoformat()
        if params.direct_only:
            query["nonStop"] = "true"

        data = await self._get("/v2/shopping/flight-offers", query)
        return self._parse_flights(data, params)

    def _parse_flights(self, data: dict, params: SearchParams) -> list[FlightOffer]:
        offers: list[FlightOffer] = []
        raw_offers = data.get("data", [])
        if not raw_offers:
            return offers

        # Compute average price for asymmetry detection
        prices = []
        for raw in raw_offers:
            try:
                prices.append(float(raw["price"]["grandTotal"]))
            except (KeyError, ValueError):
                pass
        avg_price = sum(prices) / len(prices) if prices else 0.0

        for raw in raw_offers:
            try:
                offer = self._parse_single_flight(raw, params, avg_price)
                if offer:
                    offers.append(offer)
            except Exception:
                continue

        offers.sort(key=lambda o: o.price)
        return offers

    def _parse_single_flight(
        self, raw: dict, params: SearchParams, avg_price: float
    ) -> Optional[FlightOffer]:
        from datetime import datetime

        price = float(raw["price"]["grandTotal"])
        currency = raw["price"]["currency"]

        itineraries = raw.get("itineraries", [])
        if not itineraries:
            return None

        def parse_segments(itinerary: dict) -> list[FlightSegment]:
            segs = []
            for seg in itinerary.get("segments", []):
                dep_str = seg["departure"]["at"]
                arr_str = seg["arrival"]["at"]
                dep = datetime.fromisoformat(dep_str.replace("Z", "+00:00"))
                arr = datetime.fromisoformat(arr_str.replace("Z", "+00:00"))
                duration_min = int((arr - dep).total_seconds() / 60)
                carrier = seg.get("carrierCode", "??")
                segs.append(FlightSegment(
                    origin=seg["departure"]["iataCode"],
                    destination=seg["arrival"]["iataCode"],
                    departure=dep,
                    arrival=arr,
                    carrier=carrier,
                    carrier_name=AIRLINES.get(carrier, carrier),
                    flight_number=f"{carrier}{seg.get('number', '')}",
                    duration_minutes=duration_min,
                    stops=0,
                ))
            # Mark intermediate stops
            for i, s in enumerate(segs[:-1]):
                s.stops = 1
            return segs

        outbound = parse_segments(itineraries[0])
        inbound = parse_segments(itineraries[1]) if len(itineraries) > 1 else []

        pct_vs_avg = (price - avg_price) / avg_price * 100 if avg_price else 0.0

        if pct_vs_avg < -12:
            trend = PriceTrend.ASYMMETRIC
        elif pct_vs_avg > 8:
            trend = PriceTrend.UP
        elif pct_vs_avg < -5:
            trend = PriceTrend.DOWN
        else:
            trend = PriceTrend.STABLE

        deal_score = 0
        if pct_vs_avg < -15:
            deal_score = min(95, int(80 - pct_vs_avg))
        elif pct_vs_avg < -8:
            deal_score = min(74, int(55 - pct_vs_avg))
        elif pct_vs_avg < -3:
            deal_score = min(49, int(35 - pct_vs_avg))

        # Parse traveler pricing for baggage info
        baggage = False
        for tp in raw.get("travelerPricings", []):
            for seg_p in tp.get("fareDetailsBySegment", []):
                if seg_p.get("includedCheckedBags", {}).get("quantity", 0) > 0:
                    baggage = True
                    break

        # Seats available
        seats = raw.get("numberOfBookableSeats", 9)

        return FlightOffer(
            id=raw.get("id", "AMZ"),
            outbound=outbound,
            inbound=inbound,
            price=price,
            currency=currency,
            cabin=params.cabin_class,
            seats_left=seats,
            baggage_included=baggage,
            price_trend=trend,
            avg_market_price=avg_price,
            price_vs_avg_pct=pct_vs_avg,
            is_deal=deal_score >= 50,
            deal_score=deal_score,
        )

    async def search_hotels(self, params: SearchParams) -> list[HotelOffer]:
        # Step 1: Get hotel IDs for city
        city_data = await self._get(
            "/v1/reference-data/locations/hotels/by-city",
            {"cityCode": params.destination, "ratings": "3,4,5"},
        )
        hotel_ids = [h["hotelId"] for h in city_data.get("data", [])[:20]]
        if not hotel_ids:
            return []

        # Step 2: Get offers for those hotels
        if not params.return_date:
            return []

        nights = (params.return_date - params.departure_date).days
        if nights <= 0:
            return []

        offers_data = await self._get(
            "/v3/shopping/hotel-offers",
            {
                "hotelIds": ",".join(hotel_ids),
                "checkInDate": params.departure_date.isoformat(),
                "checkOutDate": params.return_date.isoformat(),
                "adults": params.adults,
                "currency": params.currency,
                "bestRateOnly": "true",
            },
        )

        return self._parse_hotels(offers_data, params, nights)

    def _parse_hotels(self, data: dict, params: SearchParams, nights: int) -> list[HotelOffer]:
        from src.models import AIRPORTS
        dest = AIRPORTS.get(params.destination)
        city = dest.city if dest else params.destination

        offers: list[HotelOffer] = []
        for raw in data.get("data", []):
            try:
                hotel = raw["hotel"]
                hotel_offers = raw.get("offers", [])
                if not hotel_offers:
                    continue

                best_offer = hotel_offers[0]
                price_total = float(best_offer["price"]["total"])
                currency = best_offer["price"]["currency"]
                rate_per_night = price_total / nights if nights > 0 else price_total

                offers.append(HotelOffer(
                    id=hotel.get("hotelId", "AMZ"),
                    name=hotel.get("name", "Hotel"),
                    city=city,
                    stars=int(hotel.get("rating", 3)),
                    check_in=params.departure_date,
                    check_out=params.return_date,
                    room_type=best_offer.get("room", {}).get("typeEstimated", {}).get("category", "Standard"),
                    price_per_night=round(rate_per_night, 2),
                    total_price=round(price_total, 2),
                    currency=currency,
                    breakfast_included=best_offer.get("boardType", "") in ("BREAKFAST", "FULL_BOARD"),
                    cancellation_policy=best_offer.get("policies", {}).get("cancellation", {}).get("description", ""),
                    rating=float(hotel.get("rating", 7.5)),
                    review_count=0,
                    price_trend=PriceTrend.STABLE,
                    avg_market_price=price_total,
                    price_vs_avg_pct=0.0,
                    deal_score=0,
                ))
            except Exception:
                continue

        offers.sort(key=lambda h: h.total_price)
        return offers

    async def close(self) -> None:
        await self._client.aclose()
