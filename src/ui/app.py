"""
VoePontos – Terminal de Agência de Turismo
Interface TUI profissional com análise de preços em tempo real.
"""
from __future__ import annotations
import asyncio
from datetime import date, timedelta
from typing import Optional

from textual import work
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Container, Horizontal, Vertical, ScrollableContainer
from textual.widgets import (
    Header, Footer, Button, Input, Label, DataTable, RichLog,
    TabbedContent, TabPane, Static, Select, Checkbox, LoadingIndicator,
    Sparkline,
)
from textual.reactive import reactive
from textual.screen import ModalScreen
from rich.text import Text
from rich.panel import Panel
from rich.table import Table
from rich.columns import Columns
from rich.markup import escape

from src.config import Config
from src.models import (
    SearchParams, SearchResult, FlightOffer, HotelOffer,
    PriceTrend, CabinClass, TripType, AIRPORTS,
)
from src.agents.travel_agent import TravelAgent
from src.database.cache import PriceCache


# ─── CSS ──────────────────────────────────────────────────────────────────────
APP_CSS = """
Screen {
    background: #0a0a1a;
}

/* ─── Header ─── */
.app-header {
    background: #0f0f2a;
    color: #00d4ff;
    height: 3;
    padding: 0 2;
    border-bottom: solid #1a3a6e;
    layout: horizontal;
    align: left middle;
}

.header-title {
    color: #00d4ff;
    text-style: bold;
    width: auto;
}

.header-mode {
    color: #ff9500;
    text-style: italic;
    width: auto;
    margin-left: 2;
}

.header-status {
    color: #44ff88;
    dock: right;
    width: auto;
    padding-right: 2;
}

/* ─── Layout ─── */
#main-layout {
    layout: horizontal;
    height: 1fr;
}

#left-pane {
    width: 32;
    background: #0d1428;
    border-right: solid #1a3a6e;
    padding: 1;
    overflow-y: auto;
}

#right-pane {
    width: 1fr;
    layout: vertical;
}

/* ─── Search Panel ─── */
.section-title {
    color: #00d4ff;
    text-style: bold;
    margin-bottom: 1;
    padding: 0;
}

.field-label {
    color: #8899aa;
    margin-top: 1;
    margin-bottom: 0;
}

Input {
    background: #0f1f3a;
    border: solid #1a3a6e;
    color: #ffffff;
    height: 3;
}

Input:focus {
    border: solid #00d4ff;
}

Select {
    background: #0f1f3a;
    border: solid #1a3a6e;
    color: #ffffff;
    height: 3;
}

Checkbox {
    color: #aabbcc;
    margin-top: 1;
}

#btn-search {
    background: #0055ff;
    color: white;
    text-style: bold;
    height: 3;
    margin-top: 1;
    border: none;
}

#btn-search:hover {
    background: #0077ff;
}

#btn-search.-loading {
    background: #333355;
    color: #888899;
}

#btn-clear {
    background: #1a1a3a;
    color: #8899aa;
    height: 3;
    margin-top: 1;
    border: solid #1a3a6e;
}

/* ─── Search History ─── */
#history-section {
    margin-top: 2;
    border-top: dashed #1a3a6e;
    padding-top: 1;
}

.history-item {
    color: #6677aa;
    height: 2;
    padding: 0 1;
}

.history-item:hover {
    background: #0f1f3a;
    color: #aabbff;
}

/* ─── Results Tabs ─── */
#results-tabs {
    height: 55%;
    border-bottom: solid #1a3a6e;
}

TabbedContent {
    height: 1fr;
}

TabPane {
    padding: 0;
}

ContentTab {
    background: #0f1f3a;
    color: #8899aa;
}

ContentTab.-active {
    background: #0a0a1a;
    color: #00d4ff;
}

DataTable {
    background: #0a0a1a;
    height: 1fr;
}

DataTable > .datatable--header {
    background: #0f1f3a;
    color: #00d4ff;
    text-style: bold;
}

DataTable > .datatable--cursor {
    background: #1a3a6e;
    color: white;
}

/* ─── Analysis + Chart ─── */
#bottom-panels {
    height: 45%;
    layout: horizontal;
}

#analysis-panel {
    width: 65%;
    border-right: solid #1a3a6e;
    padding: 1;
    overflow-y: auto;
}

#chart-panel {
    width: 35%;
    padding: 1;
    overflow-y: auto;
}

RichLog {
    background: #050510;
    color: #ccddee;
    height: 1fr;
}

/* ─── Loading ─── */
LoadingIndicator {
    color: #00d4ff;
}

/* ─── Status Bar ─── */
#status-bar {
    background: #0f0f2a;
    height: 1;
    padding: 0 2;
    color: #556677;
    layout: horizontal;
    align: left middle;
    border-top: solid #1a3a6e;
}

.status-text {
    color: #556677;
    width: auto;
}

.status-mode-demo {
    color: #ff9500;
    dock: right;
    width: auto;
    padding-right: 1;
}

/* ─── Modal ─── */
WatchlistModal {
    align: center middle;
}

#modal-container {
    background: #0d1428;
    border: solid #00d4ff;
    width: 60;
    height: 20;
    padding: 2;
}
"""


# ─── IATA Autocomplete suggestions ───────────────────────────────────────────
IATA_SUGGESTIONS = list(AIRPORTS.keys())

CABIN_OPTIONS = [
    ("Econômica", CabinClass.ECONOMY),
    ("Prem. Econômica", CabinClass.PREMIUM_ECONOMY),
    ("Executiva", CabinClass.BUSINESS),
    ("Primeira Classe", CabinClass.FIRST),
]


# ─── Watchlist Modal ──────────────────────────────────────────────────────────
class WatchlistModal(ModalScreen):
    BINDINGS = [("escape", "dismiss", "Fechar")]

    def __init__(self, route: str, cabin: str) -> None:
        super().__init__()
        self._route = route
        self._cabin = cabin

    def compose(self) -> ComposeResult:
        with Container(id="modal-container"):
            yield Label(f"📌 Monitorar Preço: {self._route}", classes="section-title")
            yield Label("Preço alvo (R$):", classes="field-label")
            yield Input(placeholder="Ex: 3500.00", id="target-price-input")
            yield Button("Adicionar ao Monitoramento", id="btn-add-watch", variant="primary")
            yield Button("Cancelar", id="btn-cancel-watch")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "btn-cancel-watch":
            self.dismiss()
        elif event.button.id == "btn-add-watch":
            try:
                price = float(self.query_one("#target-price-input", Input).value)
                self.dismiss(price)
            except ValueError:
                pass


# ─── Price Chart Widget ───────────────────────────────────────────────────────
class PriceChartWidget(Static):
    """ASCII chart for price history visualization."""

    def render_chart(self, history) -> str:
        if not history or not history.points:
            return "[dim]Sem histórico disponível[/dim]"

        points = history.points
        prices = [p.price for p in points]
        n = len(prices)
        if n == 0:
            return "[dim]Sem dados[/dim]"

        min_p = min(prices)
        max_p = max(prices)
        height = 8
        width = min(n, 40)

        # Downsample if needed
        if n > width:
            step = n / width
            sampled = [prices[int(i * step)] for i in range(width)]
        else:
            sampled = prices

        current = sampled[-1]
        avg = sum(sampled) / len(sampled)

        # Build chart rows
        chart_rows = []
        for row in range(height - 1, -1, -1):
            threshold = min_p + (max_p - min_p) * row / (height - 1) if max_p != min_p else min_p
            line = ""
            for val in sampled:
                if val >= threshold - (max_p - min_p) / (height * 2):
                    if val < avg * 0.93:
                        line += "[green]█[/green]"
                    elif val > avg * 1.07:
                        line += "[red]█[/red]"
                    else:
                        line += "[yellow]█[/yellow]"
                else:
                    line += " "
            if row == height - 1:
                line += f" [dim]R${max_p:,.0f}[/dim]"
            elif row == 0:
                line += f" [dim]R${min_p:,.0f}[/dim]"
            chart_rows.append(line)

        trend = history.trend()
        trend_color = {
            PriceTrend.UP: "red",
            PriceTrend.DOWN: "green",
            PriceTrend.STABLE: "yellow",
            PriceTrend.ASYMMETRIC: "green",
        }.get(trend, "white")

        result = "\n".join(chart_rows)
        result += f"\n[dim]{'─' * width}[/dim]"
        result += f"\n[{trend_color}]Tendência: {trend.value.upper()}[/{trend_color}]"
        result += f"  [cyan]Atual: R${current:,.0f}[/cyan]"
        result += f"\n[dim]Média: R${avg:,.0f}  Min: R${min_p:,.0f}  Max: R${max_p:,.0f}[/dim]"
        return result


# ─── Main Application ─────────────────────────────────────────────────────────
class VoePontosApp(App):
    """Terminal de Agência de Turismo com análise IA em tempo real."""

    CSS = APP_CSS
    TITLE = "VoePontos"
    SUB_TITLE = "Terminal de Agência de Turismo"

    BINDINGS = [
        Binding("ctrl+b", "search", "Buscar", show=True),
        Binding("ctrl+l", "clear_results", "Limpar", show=True),
        Binding("ctrl+w", "add_watchlist", "Monitorar", show=True),
        Binding("ctrl+h", "toggle_history", "Histórico", show=True),
        Binding("ctrl+q", "quit", "Sair", show=True),
        Binding("f1", "help_screen", "Ajuda", show=False),
    ]

    # Reactive state
    is_searching: reactive[bool] = reactive(False)
    status_text: reactive[str] = reactive("Pronto. Preencha os campos e pressione Buscar.")
    current_result: reactive[Optional[SearchResult]] = reactive(None)

    def __init__(self) -> None:
        super().__init__()
        self._agent = TravelAgent()
        self._cache = PriceCache()
        self._chart_widget = PriceChartWidget()
        self._recent_searches: list[dict] = []

    # ─── Compose ──────────────────────────────────────────────────────────────

    def compose(self) -> ComposeResult:
        # Header
        with Container(classes="app-header"):
            yield Label("✈  VoePontos", classes="header-title")
            mode_label = "DEMO" if Config.is_demo_mode() else "LIVE"
            mode_color = "orange" if Config.is_demo_mode() else "green"
            yield Label(f"[{mode_color}]● {mode_label}[/{mode_color}]", classes="header-mode", markup=True)
            claude_status = "🤖 Claude ativo" if Config.has_claude() else "🤖 Claude offline"
            yield Label(claude_status, classes="header-status")

        with Container(id="main-layout"):
            # ─── Left: Search ───────────────────────────────────────────────
            with Vertical(id="left-pane"):
                yield Label("🔍 BUSCA DE VIAGEM", classes="section-title")

                yield Label("Origem (IATA):", classes="field-label")
                yield Input(placeholder="Ex: GRU", id="origin-input", max_length=3)

                yield Label("Destino (IATA):", classes="field-label")
                yield Input(placeholder="Ex: CDG", id="dest-input", max_length=3)

                yield Label("Data de Ida:", classes="field-label")
                tomorrow = (date.today() + timedelta(days=30)).strftime("%d/%m/%Y")
                yield Input(placeholder=tomorrow, id="dep-date-input")

                yield Label("Data de Volta:", classes="field-label")
                ret_default = (date.today() + timedelta(days=37)).strftime("%d/%m/%Y")
                yield Input(placeholder=ret_default, id="ret-date-input")

                yield Label("Adultos:", classes="field-label")
                yield Input(placeholder="1", id="adults-input", max_length=2)

                yield Label("Cabine:", classes="field-label")
                yield Select(
                    [(label, cabin) for label, cabin in CABIN_OPTIONS],
                    id="cabin-select",
                    value=CabinClass.ECONOMY,
                )

                yield Label("Budget Máx (R$):", classes="field-label")
                yield Input(placeholder="Sem limite", id="budget-input")

                yield Label("Perfil do cliente:", classes="field-label")
                yield Input(
                    placeholder="Ex: família, lua de mel, negócios...",
                    id="profile-input",
                )

                yield Checkbox("Apenas voos diretos", id="direct-check")
                yield Checkbox("Com bagagem incluída", id="baggage-check")

                yield Button("🔍 BUSCAR AGORA", id="btn-search", variant="primary")
                yield Button("✗ Limpar", id="btn-clear")

                # Recent searches
                with Container(id="history-section"):
                    yield Label("⏱ BUSCAS RECENTES", classes="section-title")
                    yield Static(id="history-container", markup=True)

            # ─── Right: Results ──────────────────────────────────────────────
            with Vertical(id="right-pane"):
                # Tabs: Flights + Hotels
                with Container(id="results-tabs"):
                    with TabbedContent(id="results-tabbed"):
                        with TabPane("✈ Voos", id="tab-flights"):
                            yield DataTable(id="flights-table", zebra_stripes=True, cursor_type="row")
                        with TabPane("🏨 Hotéis", id="tab-hotels"):
                            yield DataTable(id="hotels-table", zebra_stripes=True, cursor_type="row")

                # Analysis + Chart
                with Horizontal(id="bottom-panels"):
                    with Vertical(id="analysis-panel"):
                        yield Label("🤖 ANÁLISE INTELIGENTE (Claude Opus)", classes="section-title")
                        yield RichLog(id="analysis-log", markup=True, highlight=True, wrap=True)

                    with Vertical(id="chart-panel"):
                        yield Label("📈 VARIAÇÃO DE PREÇOS (30 dias)", classes="section-title")
                        yield Static(id="price-chart", markup=True)

        # Status bar
        with Container(id="status-bar"):
            yield Static(id="status-label", markup=True)
            mode_txt = "● MODO DEMO — dados simulados" if Config.is_demo_mode() else "● API LIVE"
            yield Static(f"[{'orange' if Config.is_demo_mode() else 'green'}]{mode_txt}[/{'orange' if Config.is_demo_mode() else 'green'}]",
                         classes="status-mode-demo", markup=True)

    # ─── On Mount ─────────────────────────────────────────────────────────────

    def on_mount(self) -> None:
        self._setup_tables()
        self._update_status("Pronto. Preencha os campos e pressione [bold cyan]Ctrl+B[/bold cyan] para buscar.")
        self._load_history()

    def _setup_tables(self) -> None:
        ft = self.query_one("#flights-table", DataTable)
        ft.add_columns(
            "  ", "Companhia", "Voo", "Preço", "Var.%", "Duração",
            "Paradas", "Bagagem", "Lugares", "Deal"
        )
        ft.cursor_type = "row"

        ht = self.query_one("#hotels-table", DataTable)
        ht.add_columns(
            "Hotel", "★", "Noites", "Total", "Var.%", "Rating",
            "Café", "Cancelamento"
        )
        ht.cursor_type = "row"

    @work(exclusive=False)
    async def _load_history(self) -> None:
        try:
            searches = await self._cache.get_recent_searches(8)
            self._recent_searches = searches
            self._refresh_history_widget()
        except Exception:
            pass

    def _refresh_history_widget(self) -> None:
        container = self.query_one("#history-container", Static)
        if not self._recent_searches:
            container.update("[dim]Nenhuma busca recente[/dim]")
            return

        lines = []
        for s in self._recent_searches[:6]:
            cabin_label = {"ECONOMY": "Eco", "BUSINESS": "Exec", "PREMIUM_ECONOMY": "PEco", "FIRST": "1ª"}.get(
                s.get("cabin", ""), "Eco"
            )
            price_str = f"R${s['best_price']:,.0f}" if s.get("best_price") else "N/A"
            lines.append(
                f"[cyan]{s['origin']}→{s['destination']}[/cyan] "
                f"[dim]{cabin_label} {price_str}[/dim]"
            )

        container.update("\n".join(lines))

    # ─── Search Logic ─────────────────────────────────────────────────────────

    def _parse_date(self, raw: str) -> Optional[date]:
        raw = raw.strip()
        if not raw:
            return None
        # Try DD/MM/YYYY
        for fmt in ("%d/%m/%Y", "%Y-%m-%d", "%d-%m-%Y"):
            try:
                return date(*[int(x) for x in __import__("re").split(r"[/\-]", raw)][::-1]
                            if fmt == "%Y-%m-%d" else
                            [int(x) for x in __import__("re").split(r"[/\-]", raw)])
            except Exception:
                pass
        # Fallback manual parse
        try:
            parts = __import__("re").split(r"[/\-\.]", raw)
            if len(parts) == 3:
                if len(parts[2]) == 4:  # DD/MM/YYYY
                    return date(int(parts[2]), int(parts[1]), int(parts[0]))
                else:  # YYYY-MM-DD
                    return date(int(parts[0]), int(parts[1]), int(parts[2]))
        except Exception:
            return None

    def _build_search_params(self) -> Optional[SearchParams]:
        origin = self.query_one("#origin-input", Input).value.strip().upper()
        dest = self.query_one("#dest-input", Input).value.strip().upper()

        if not origin or len(origin) != 3:
            self._update_status("[red]⚠ Origem inválida. Use código IATA (ex: GRU)[/red]")
            return None
        if not dest or len(dest) != 3:
            self._update_status("[red]⚠ Destino inválido. Use código IATA (ex: CDG)[/red]")
            return None

        dep_str = self.query_one("#dep-date-input", Input).value
        ret_str = self.query_one("#ret-date-input", Input).value

        dep_date = self._parse_date(dep_str) if dep_str.strip() else date.today() + timedelta(days=30)
        ret_date = self._parse_date(ret_str) if ret_str.strip() else None

        if dep_date is None:
            self._update_status("[red]⚠ Data de ida inválida. Use DD/MM/AAAA[/red]")
            return None

        try:
            adults = int(self.query_one("#adults-input", Input).value or "1")
        except ValueError:
            adults = 1

        cabin_val = self.query_one("#cabin-select", Select).value
        cabin = cabin_val if isinstance(cabin_val, CabinClass) else CabinClass.ECONOMY

        try:
            budget_str = self.query_one("#budget-input", Input).value.strip()
            budget = float(budget_str.replace(",", ".")) if budget_str else None
        except ValueError:
            budget = None

        profile = self.query_one("#profile-input", Input).value.strip()
        direct = self.query_one("#direct-check", Checkbox).value
        baggage = self.query_one("#baggage-check", Checkbox).value

        return SearchParams(
            origin=origin,
            destination=dest,
            departure_date=dep_date,
            return_date=ret_date,
            adults=adults,
            cabin_class=cabin,
            max_budget=budget,
            direct_only=direct,
            include_baggage=baggage,
            customer_profile=profile,
            trip_type=TripType.ROUND_TRIP if ret_date else TripType.ONE_WAY,
        )

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "btn-search":
            self.action_search()
        elif event.button.id == "btn-clear":
            self.action_clear_results()

    def action_search(self) -> None:
        if self.is_searching:
            return
        params = self._build_search_params()
        if params:
            self._run_search(params)

    @work(exclusive=True)
    async def _run_search(self, params: SearchParams) -> None:
        import time
        self.is_searching = True
        btn = self.query_one("#btn-search", Button)
        btn.label = "⏳ Buscando..."
        btn.disabled = True

        log = self.query_one("#analysis-log", RichLog)
        log.clear()
        log.write("[cyan]Iniciando busca...[/cyan]")

        self._clear_tables()
        self._update_status(f"[cyan]Buscando {params.origin} → {params.destination}...[/cyan]")

        t0 = time.time()

        try:
            result = await self._fetch_results(params)
            result.search_time_ms = int((time.time() - t0) * 1000)

            self.current_result = result

            self._populate_flights_table(result.flights)
            self._populate_hotels_table(result.hotels)
            self._update_price_chart(result.price_history)

            best = result.best_flight
            count_msg = f"{len(result.flights)} voo(s), {len(result.hotels)} hotel(is)"
            asym_msg = f" | [green]★ {len(result.asymmetric_flights)} assimétrico(s)[/green]" if result.asymmetric_flights else ""
            demo_flag = " [orange]DEMO[/orange]" if result.is_demo else ""
            self._update_status(
                f"✓ {count_msg}{asym_msg} | {result.search_time_ms}ms{demo_flag}"
            )

            # Save to cache
            await self._cache.save_search(
                params,
                best.price if best else None,
                len(result.flights),
            )
            if best and result.price_history:
                await self._cache.save_price_point(
                    f"{params.origin}-{params.destination}",
                    params.cabin_class,
                    date.today(),
                    best.price,
                    "live" if not result.is_demo else "demo",
                )

            # Refresh history
            self._recent_searches = await self._cache.get_recent_searches(8)
            self._refresh_history_widget()

            # AI analysis (streaming)
            log.clear()
            log.write("[cyan]🤖 Analisando com Claude Opus...[/cyan]\n")
            async for chunk in self._agent.analyze_streaming(result):
                log.write(chunk, animate=False)

        except Exception as e:
            self._update_status(f"[red]⚠ Erro na busca: {escape(str(e)[:100])}[/red]")
            log.write(f"[red]Erro: {escape(str(e))}[/red]")
        finally:
            self.is_searching = False
            btn.label = "🔍 BUSCAR AGORA"
            btn.disabled = False

    async def _fetch_results(self, params: SearchParams) -> SearchResult:
        from src.api.mock_data import (
            generate_flights, generate_hotels, generate_price_history
        )

        is_demo = Config.is_demo_mode()

        if is_demo:
            # Use mock data
            flights = generate_flights(params)
            hotels = generate_hotels(params)
            history = generate_price_history(
                params.origin, params.destination, params.cabin_class
            )
        else:
            # Try real APIs, fall back to mock on error
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

            # Try to get history from cache
            history = await self._cache.get_price_history(
                f"{params.origin}-{params.destination}",
                params.cabin_class,
            )
            if not history:
                history = generate_price_history(
                    params.origin, params.destination, params.cabin_class
                )

        # Apply market analysis
        if flights:
            avg = sum(f.price for f in flights) / len(flights)
            for f in flights:
                f.avg_market_price = avg
                f.price_vs_avg_pct = (f.price - avg) / avg * 100

        return SearchResult(
            params=params,
            flights=flights,
            hotels=hotels,
            price_history=history,
            is_demo=is_demo,
        )

    # ─── Table Population ─────────────────────────────────────────────────────

    def _clear_tables(self) -> None:
        ft = self.query_one("#flights-table", DataTable)
        ft.clear()
        ht = self.query_one("#hotels-table", DataTable)
        ht.clear()

    def _populate_flights_table(self, flights: list[FlightOffer]) -> None:
        table = self.query_one("#flights-table", DataTable)
        table.clear()

        trend_colors = {
            PriceTrend.UP: "red",
            PriceTrend.DOWN: "green",
            PriceTrend.STABLE: "yellow",
            PriceTrend.ASYMMETRIC: "green",
        }
        trend_icons = {
            PriceTrend.UP: "↑",
            PriceTrend.DOWN: "↓",
            PriceTrend.STABLE: "→",
            PriceTrend.ASYMMETRIC: "★",
        }

        for i, f in enumerate(flights):
            color = trend_colors.get(f.price_trend, "white")
            icon = trend_icons.get(f.price_trend, "?")

            # Rank badge
            rank = ""
            if i == 0:
                rank = Text("🥇", justify="center")
            elif i == 1:
                rank = Text("🥈", justify="center")
            elif i == 2:
                rank = Text("🥉", justify="center")
            else:
                rank = Text(str(i + 1), style="dim", justify="center")

            carrier = Text(f.main_carrier, style="cyan")
            flight_num = Text(
                f.outbound[0].flight_number if f.outbound else "?",
                style="dim"
            )

            price_txt = Text(f.price_fmt())
            if f.is_deal:
                price_txt.stylize("bold green")
            elif f.price_trend == PriceTrend.UP:
                price_txt.stylize("red")

            pct_style = "green" if f.price_vs_avg_pct < 0 else "red"
            pct_txt = Text(f"{f.price_vs_avg_pct:+.1f}%", style=pct_style)

            duration = Text(f.outbound[0].duration_fmt() if f.outbound else "?", style="dim")
            stops_txt = Text("DIRETO" if f.total_stops == 0 else f"{f.total_stops} escala(s)",
                             style="green" if f.total_stops == 0 else "yellow")
            bag = Text("✓" if f.baggage_included else "✗",
                       style="green" if f.baggage_included else "dim")
            seats = Text(str(f.seats_left), style="red" if f.seats_left <= 3 else "dim")
            deal_txt = Text(f.deal_badge() or f"{icon}", style=color)

            table.add_row(rank, carrier, flight_num, price_txt, pct_txt,
                          duration, stops_txt, bag, seats, deal_txt)

    def _populate_hotels_table(self, hotels: list[HotelOffer]) -> None:
        table = self.query_one("#hotels-table", DataTable)
        table.clear()

        for h in hotels:
            name = Text(h.name, style="cyan")
            stars = Text(h.stars_fmt(), style="yellow")
            nights = Text(str(h.nights))
            price = Text(h.price_fmt(), style="bold" if h.deal_score >= 50 else "")
            pct_style = "green" if h.price_vs_avg_pct < 0 else "red"
            pct = Text(f"{h.price_vs_avg_pct:+.1f}%", style=pct_style)
            rating = Text(f"{h.rating:.1f}", style="green" if h.rating >= 8.5 else "yellow")
            breakfast = Text("✓" if h.breakfast_included else "✗",
                             style="green" if h.breakfast_included else "dim")
            cancel = Text(h.cancellation_policy[:30], style="dim")
            table.add_row(name, stars, nights, price, pct, rating, breakfast, cancel)

    # ─── Price Chart ──────────────────────────────────────────────────────────

    def _update_price_chart(self, history) -> None:
        chart = self.query_one("#price-chart", Static)
        if not history:
            chart.update("[dim]Sem histórico disponível[/dim]")
            return

        widget = PriceChartWidget()
        chart.update(widget.render_chart(history))

    # ─── Actions ──────────────────────────────────────────────────────────────

    def action_clear_results(self) -> None:
        self._clear_tables()
        self.query_one("#analysis-log", RichLog).clear()
        self.query_one("#price-chart", Static).update("[dim]Execute uma busca para ver o gráfico[/dim]")
        self.current_result = None
        self._update_status("Resultados limpos.")

    def action_add_watchlist(self) -> None:
        result = self.current_result
        if not result:
            self._update_status("[yellow]⚠ Execute uma busca primeiro.[/yellow]")
            return
        params = result.params
        route = f"{params.origin}-{params.destination}"

        def on_dismiss(price) -> None:
            if price:
                self._save_watchlist(route, params.cabin_class, price)

        self.push_screen(WatchlistModal(route, params.cabin_class.value), on_dismiss)

    @work(exclusive=False)
    async def _save_watchlist(self, route: str, cabin: CabinClass, price: float) -> None:
        await self._cache.add_to_watchlist(route, cabin, price)
        self._update_status(f"[green]✓ Monitoramento adicionado: {route} @ R${price:,.0f}[/green]")

    def action_toggle_history(self) -> None:
        history_sec = self.query_one("#history-section")
        history_sec.display = not history_sec.display

    def action_help_screen(self) -> None:
        log = self.query_one("#analysis-log", RichLog)
        log.clear()
        help_text = """[bold cyan]╔══════════════════════════════════╗
║     AJUDA - VoePontos Terminal     ║
╚══════════════════════════════════╝[/bold cyan]

[bold]Atalhos do Teclado:[/bold]
  [cyan]Ctrl+B[/cyan]  → Buscar voos e hotéis
  [cyan]Ctrl+L[/cyan]  → Limpar resultados
  [cyan]Ctrl+W[/cyan]  → Adicionar à lista de monitoramento
  [cyan]Ctrl+H[/cyan]  → Mostrar/ocultar histórico
  [cyan]Ctrl+Q[/cyan]  → Sair do terminal
  [cyan]F1[/cyan]      → Esta tela de ajuda

[bold]Códigos IATA Comuns:[/bold]
  [green]GRU[/green] São Paulo   [green]GIG[/green] Rio de Janeiro   [green]BSB[/green] Brasília
  [green]FOR[/green] Fortaleza   [green]REC[/green] Recife           [green]POA[/green] Porto Alegre
  [green]CDG[/green] Paris       [green]LHR[/green] Londres          [green]JFK[/green] Nova York
  [green]MIA[/green] Miami       [green]MAD[/green] Madrid           [green]LIS[/green] Lisboa
  [green]FCO[/green] Roma        [green]AMS[/green] Amsterdam        [green]DXB[/green] Dubai

[bold]Legenda de Preços:[/bold]
  [green]★[/green] Preço assimétrico — oportunidade abaixo do mercado
  [red]↑[/red]  Preço em alta
  [green]↓[/green]  Preço em queda
  [yellow]→[/yellow]  Preço estável

[bold]Configuração:[/bold]
  Copie [cyan].env.example[/cyan] para [cyan].env[/cyan] e configure:
  • [yellow]ANTHROPIC_API_KEY[/yellow] para análise com Claude
  • [yellow]AMADEUS_API_KEY[/yellow] para dados em tempo real
  • Sem configuração → modo DEMO com dados simulados
"""
        log.write(help_text)

    # ─── Helpers ──────────────────────────────────────────────────────────────

    def _update_status(self, msg: str) -> None:
        try:
            status = self.query_one("#status-label", Static)
            status.update(msg)
        except Exception:
            pass

    def watch_is_searching(self, value: bool) -> None:
        btn = self.query_one("#btn-search", Button)
        if value:
            btn.add_class("-loading")
        else:
            btn.remove_class("-loading")
