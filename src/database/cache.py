"""
Cache SQLite para histórico de preços e pesquisas recentes.
Permite rastrear variações de preços ao longo do tempo.
"""
from __future__ import annotations
import json
import asyncio
from datetime import date, datetime, timedelta
from typing import Optional

import aiosqlite

from src.config import Config
from src.models import PriceHistory, PricePoint, CabinClass, SearchParams


CREATE_TABLES = """
CREATE TABLE IF NOT EXISTS price_history (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    route       TEXT NOT NULL,
    cabin       TEXT NOT NULL,
    price_date  TEXT NOT NULL,
    price       REAL NOT NULL,
    source      TEXT DEFAULT 'cache',
    created_at  TEXT DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(route, cabin, price_date)
);

CREATE TABLE IF NOT EXISTS recent_searches (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    origin      TEXT NOT NULL,
    destination TEXT NOT NULL,
    departure   TEXT NOT NULL,
    cabin       TEXT NOT NULL,
    best_price  REAL,
    num_offers  INTEGER,
    searched_at TEXT DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS watchlist (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    route       TEXT NOT NULL,
    cabin       TEXT NOT NULL,
    target_price REAL NOT NULL,
    active      INTEGER DEFAULT 1,
    created_at  TEXT DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_price_history_route ON price_history(route, cabin);
CREATE INDEX IF NOT EXISTS idx_recent_searches ON recent_searches(origin, destination, searched_at);
"""


class PriceCache:
    """Cache assíncrono de preços usando SQLite."""

    def __init__(self, db_path: Optional[str] = None) -> None:
        self._db_path = str(db_path or Config.DB_PATH)
        self._initialized = False

    async def _get_conn(self) -> aiosqlite.Connection:
        conn = await aiosqlite.connect(self._db_path)
        conn.row_factory = aiosqlite.Row
        if not self._initialized:
            await conn.executescript(CREATE_TABLES)
            await conn.commit()
            self._initialized = True
        return conn

    async def save_price_point(
        self,
        route: str,
        cabin: CabinClass,
        price_date: date,
        price: float,
        source: str = "live",
    ) -> None:
        async with await self._get_conn() as db:
            await db.execute(
                """INSERT OR REPLACE INTO price_history (route, cabin, price_date, price, source)
                   VALUES (?, ?, ?, ?, ?)""",
                (route, cabin.value, price_date.isoformat(), price, source),
            )
            await db.commit()

    async def get_price_history(
        self,
        route: str,
        cabin: CabinClass,
        days: int = 30,
    ) -> Optional[PriceHistory]:
        since = (date.today() - timedelta(days=days)).isoformat()
        async with await self._get_conn() as db:
            async with db.execute(
                """SELECT price_date, price, source FROM price_history
                   WHERE route = ? AND cabin = ? AND price_date >= ?
                   ORDER BY price_date ASC""",
                (route, cabin.value, since),
            ) as cursor:
                rows = await cursor.fetchall()

        if not rows:
            return None

        points = [
            PricePoint(
                date=date.fromisoformat(row["price_date"]),
                price=row["price"],
                source=row["source"],
            )
            for row in rows
        ]
        return PriceHistory(route=route, cabin=cabin, points=points)

    async def save_search(
        self,
        params: SearchParams,
        best_price: Optional[float],
        num_offers: int,
    ) -> None:
        async with await self._get_conn() as db:
            await db.execute(
                """INSERT INTO recent_searches (origin, destination, departure, cabin, best_price, num_offers)
                   VALUES (?, ?, ?, ?, ?, ?)""",
                (
                    params.origin,
                    params.destination,
                    params.departure_date.isoformat(),
                    params.cabin_class.value,
                    best_price,
                    num_offers,
                ),
            )
            await db.commit()

    async def get_recent_searches(self, limit: int = 10) -> list[dict]:
        async with await self._get_conn() as db:
            async with db.execute(
                """SELECT origin, destination, cabin, MIN(best_price) as best_price,
                          MAX(searched_at) as last_searched, COUNT(*) as search_count
                   FROM recent_searches
                   GROUP BY origin, destination, cabin
                   ORDER BY last_searched DESC
                   LIMIT ?""",
                (limit,),
            ) as cursor:
                rows = await cursor.fetchall()

        return [dict(row) for row in rows]

    async def add_to_watchlist(
        self,
        route: str,
        cabin: CabinClass,
        target_price: float,
    ) -> None:
        async with await self._get_conn() as db:
            await db.execute(
                """INSERT OR REPLACE INTO watchlist (route, cabin, target_price)
                   VALUES (?, ?, ?)""",
                (route, cabin.value, target_price),
            )
            await db.commit()

    async def get_watchlist(self) -> list[dict]:
        async with await self._get_conn() as db:
            async with db.execute(
                """SELECT w.route, w.cabin, w.target_price,
                          h.price as current_price
                   FROM watchlist w
                   LEFT JOIN (
                       SELECT route, cabin, price
                       FROM price_history
                       WHERE (route, cabin, price_date) IN (
                           SELECT route, cabin, MAX(price_date)
                           FROM price_history GROUP BY route, cabin
                       )
                   ) h ON h.route = w.route AND h.cabin = w.cabin
                   WHERE w.active = 1
                   ORDER BY w.created_at DESC""",
            ) as cursor:
                rows = await cursor.fetchall()

        return [dict(row) for row in rows]

    async def get_price_alerts(self) -> list[dict]:
        """Returns watchlist items where current price <= target."""
        items = await self.get_watchlist()
        return [
            item for item in items
            if item.get("current_price") and item["current_price"] <= item["target_price"]
        ]
