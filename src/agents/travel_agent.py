"""
Agente de viagem inteligente alimentado por Claude Opus.
Realiza análise qualitativa, detecta preços assimétricos e fornece
recomendações personalizadas em tempo real via streaming.
"""
from __future__ import annotations
import json
from typing import AsyncIterator, Optional
from collections.abc import AsyncGenerator

import anthropic

from src.config import Config
from src.models import (
    FlightOffer, HotelOffer, PriceHistory, SearchParams, SearchResult,
    PriceTrend, CabinClass,
)


_SYSTEM_PROMPT = """Você é um agente especialista em viagens de luxo e economia trabalhando em um terminal profissional de agência de turismo brasileiro.

Suas capacidades:
- Detectar preços assimétricos (oportunidades abaixo do mercado)
- Analisar tendências de preços e padrões sazonais
- Recomendar a melhor janela de compra
- Adaptar recomendações ao perfil e orçamento do cliente
- Identificar combinações voo+hotel com melhor custo-benefício
- Avaliar qualidade das opções além do preço

Formato de resposta:
- Seja direto e objetivo (respostas de 200-400 palavras)
- Use emojis relevantes para destacar pontos chave
- Destaque SEMPRE oportunidades assimétricas com "🔥 ASSIMETRIA"
- Use "✅ RECOMENDAÇÃO" para sua principal sugestão
- Use "⚠️ ATENÇÃO" para alertas importantes
- Cite valores específicos em BRL
- Indique nível de urgência: BAIXO / MÉDIO / ALTO / URGENTE

Lembre-se: O cliente confia em você para economizar dinheiro e maximizar valor."""


class TravelAgent:
    """Agente Claude para análise e recomendações de viagem."""

    def __init__(self) -> None:
        if not Config.has_claude():
            self._client = None
        else:
            self._client = anthropic.AsyncAnthropic(api_key=Config.ANTHROPIC_API_KEY)

    def _build_context(
        self,
        result: SearchResult,
    ) -> str:
        params = result.params
        lines: list[str] = []

        lines.append(f"=== BUSCA DO CLIENTE ===")
        lines.append(f"Rota: {params.origin} → {params.destination}")
        lines.append(f"Ida: {params.departure_date.strftime('%d/%m/%Y')}")
        if params.return_date:
            lines.append(f"Volta: {params.return_date.strftime('%d/%m/%Y')}")
        lines.append(f"Passageiros: {params.adults} adulto(s), {params.children} criança(s)")
        lines.append(f"Cabine: {params.cabin_class.label()}")
        if params.max_budget:
            lines.append(f"Budget máximo: R$ {params.max_budget:,.2f}")
        if params.customer_profile:
            lines.append(f"Perfil/Preferências: {params.customer_profile}")
        lines.append("")

        # Flights
        if result.flights:
            lines.append(f"=== VOOS ENCONTRADOS ({len(result.flights)}) ===")
            for i, f in enumerate(result.flights[:8], 1):
                trend_emoji = {"up": "↑", "down": "↓", "stable": "→", "asymmetric": "★"}.get(
                    f.price_trend.value, "?"
                )
                deal = f" [{f.deal_badge()}]" if f.deal_badge() else ""
                lines.append(
                    f"{i}. {f.main_carrier} {f.outbound[0].flight_number if f.outbound else ''} | "
                    f"{f.price_fmt()} {trend_emoji}{deal} | "
                    f"Paradas: {f.total_stops} | "
                    f"Bagagem: {'✓' if f.baggage_included else '✗'} | "
                    f"Lugares: {f.seats_left} | "
                    f"vs mercado: {f.price_vs_avg_pct:+.1f}%"
                )

            best = result.best_flight
            if best:
                lines.append(f"\nMelhor preço: {best.price_fmt()} ({best.main_carrier})")
            if result.asymmetric_flights:
                lines.append(f"Preços assimétricos detectados: {len(result.asymmetric_flights)} voo(s)")
        else:
            lines.append("Nenhum voo encontrado.")

        lines.append("")

        # Hotels
        if result.hotels:
            lines.append(f"=== HOTÉIS ENCONTRADOS ({len(result.hotels)}) ===")
            for i, h in enumerate(result.hotels[:5], 1):
                lines.append(
                    f"{i}. {h.name} {h.stars_fmt()} | "
                    f"{h.price_fmt()} ({h.nights} noites) | "
                    f"Rating: {h.rating:.1f}/10 | "
                    f"Café: {'✓' if h.breakfast_included else '✗'} | "
                    f"vs mercado: {h.price_vs_avg_pct:+.1f}%"
                )

        # Price history
        if result.price_history and result.price_history.points:
            hist = result.price_history
            lines.append(f"\n=== HISTÓRICO DE PREÇOS (30 dias) ===")
            lines.append(f"Mínimo: R$ {hist.min_price:,.2f}")
            lines.append(f"Médio: R$ {hist.avg_price:,.2f}")
            lines.append(f"Máximo: R$ {hist.max_price:,.2f}")
            lines.append(f"Atual: R$ {hist.current_price:,.2f}")
            trend = hist.trend()
            lines.append(f"Tendência: {trend.value.upper()}")

        return "\n".join(lines)

    async def analyze_streaming(
        self,
        result: SearchResult,
        extra_question: str = "",
    ) -> AsyncGenerator[str, None]:
        """Gera análise qualitativa via streaming do Claude."""

        if not self._client:
            async for chunk in self._fallback_analysis(result):
                yield chunk
            return

        context = self._build_context(result)

        user_msg = context
        if extra_question:
            user_msg += f"\n\n=== PERGUNTA DO CLIENTE ===\n{extra_question}"
        else:
            user_msg += "\n\nFaça uma análise completa: identifique oportunidades, preços assimétricos, recomende a melhor opção e indique urgência de compra."

        try:
            async with self._client.messages.stream(
                model="claude-opus-4-6",
                max_tokens=1024,
                thinking={"type": "adaptive"},
                system=_SYSTEM_PROMPT,
                messages=[{"role": "user", "content": user_msg}],
            ) as stream:
                async for text in stream.text_stream:
                    yield text
        except anthropic.AuthenticationError:
            yield "⚠️ Chave API Claude inválida. Configure ANTHROPIC_API_KEY no arquivo .env\n\n"
            async for chunk in self._fallback_analysis(result):
                yield chunk
        except Exception as e:
            yield f"⚠️ Erro na análise IA: {str(e)[:100]}\n\n"
            async for chunk in self._fallback_analysis(result):
                yield chunk

    async def _fallback_analysis(
        self, result: SearchResult
    ) -> AsyncGenerator[str, None]:
        """Análise local quando Claude não está disponível."""
        params = result.params

        lines: list[str] = []
        lines.append(f"📊 **ANÁLISE AUTOMÁTICA** *(Claude não configurado)*\n\n")
        lines.append(f"🗺️ **Rota:** {params.origin} → {params.destination}\n\n")

        if result.flights:
            best = result.best_flight
            asym = result.asymmetric_flights

            if asym:
                lines.append(
                    f"🔥 **ASSIMETRIA DETECTADA!** {len(asym)} voo(s) com preço abaixo do mercado.\n"
                )
                for f in asym[:2]:
                    lines.append(
                        f"   • {f.main_carrier}: {f.price_fmt()} "
                        f"({f.price_vs_avg_pct:+.1f}% vs mercado)\n"
                    )
                lines.append("\n")

            if best:
                lines.append(f"✅ **RECOMENDAÇÃO:** {best.main_carrier} por {best.price_fmt()}\n")
                if best.price_vs_avg_pct < -8:
                    lines.append(f"   Preço {abs(best.price_vs_avg_pct):.0f}% abaixo da média — excelente oportunidade!\n")
                lines.append("\n")

            lines.append(f"📈 **Resumo do mercado:**\n")
            lines.append(f"   • {len(result.flights)} opções encontradas\n")
            prices = [f.price for f in result.flights]
            lines.append(f"   • Faixa: {min(prices):,.0f} – {max(prices):,.0f} BRL\n")
            lines.append(f"   • Média: {sum(prices)/len(prices):,.0f} BRL\n\n")

        if result.hotels:
            best_hotel = min(result.hotels, key=lambda h: h.total_price)
            lines.append(f"🏨 **Melhor hotel:** {best_hotel.name} ({best_hotel.stars}★)\n")
            lines.append(f"   {best_hotel.price_fmt()} por {best_hotel.nights} noite(s)\n\n")

        if result.price_history:
            hist = result.price_history
            trend = hist.trend()
            if trend == PriceTrend.ASYMMETRIC:
                lines.append(f"⚠️ **ATENÇÃO:** Preço atual abaixo da média histórica — janela de compra favorável!\n")
            elif trend == PriceTrend.UP:
                lines.append(f"⚠️ **ATENÇÃO:** Preços em ALTA. Considere comprar logo!\n")
            else:
                lines.append(f"ℹ️ Preços estáveis no momento.\n")

        lines.append(
            f"\n💡 **Configure ANTHROPIC_API_KEY** para análise avançada com IA."
        )

        # Yield in chunks to simulate streaming
        for line in lines:
            yield line
            import asyncio
            await asyncio.sleep(0.05)

    async def answer_question(
        self,
        question: str,
        result: Optional[SearchResult] = None,
    ) -> AsyncGenerator[str, None]:
        """Responde perguntas do usuário sobre a viagem."""
        if result:
            async for chunk in self.analyze_streaming(result, question):
                yield chunk
        else:
            if not self._client:
                yield "⚠️ Claude não configurado. Adicione ANTHROPIC_API_KEY ao .env para usar o assistente.\n"
                return
            try:
                async with self._client.messages.stream(
                    model="claude-opus-4-6",
                    max_tokens=512,
                    system=_SYSTEM_PROMPT,
                    messages=[{"role": "user", "content": question}],
                ) as stream:
                    async for text in stream.text_stream:
                        yield text
            except Exception as e:
                yield f"⚠️ Erro: {str(e)[:100]}\n"
