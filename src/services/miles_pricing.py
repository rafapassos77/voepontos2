"""
MilesPricingEngine — converte milhas para reais usando coeficientes por companhia.

Regras:
- Prioridade: by_value_type (TipoValor) > by_miles_type (TipoMilhas) > default
- Fórmula: ValorMilhas = (Milhas / 1000) × Coeficiente
           ValorFinal  = ValorMilhas + TaxaEmbarque + TaxaResgate
- Normalização case-insensitive para tolerar variações da API.
- Coeficientes recarregáveis em runtime via reload().
"""
from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Optional


DEFAULT_CONFIG_PATH = Path(__file__).resolve().parents[2] / "config" / "coefficients.json"


@dataclass
class PricingResult:
    """Resultado da conversão milhas → R$ com memória de cálculo."""
    estimated_brl: float              # total estimado (milhas convertidas + taxas)
    miles_converted_brl: float        # apenas parte das milhas
    fees_brl: float                   # taxa embarque + taxa resgate
    coefficient: float                # coef aplicado (R$ por milheiro)
    coefficient_source: str           # "by_value_type:PO", "by_miles_type:...", "default" ou "NOT_CONFIGURED"
    coefficient_configured: bool      # False se faltou coeficiente
    calc_memory: str                  # fórmula textual para auditoria
    miles_total: float


class MilesPricingEngine:
    """Engine de precificação de passagens em milhas."""

    def __init__(self, config_path: Optional[str | Path] = None) -> None:
        self._config_path = Path(config_path) if config_path else DEFAULT_CONFIG_PATH
        self._config: dict = {"companies": {}}
        self.reload()

    def reload(self) -> dict:
        """Recarrega coeficientes do disco. Retorna resumo do que foi carregado."""
        if self._config_path.is_file():
            try:
                with open(self._config_path, "r", encoding="utf-8") as f:
                    self._config = json.load(f)
            except (json.JSONDecodeError, OSError) as exc:
                self._config = {"companies": {}, "_error": str(exc)}
        else:
            self._config = {"companies": {}}
        return {
            "path": str(self._config_path),
            "companies_loaded": list(self._config.get("companies", {}).keys()),
            "version": self._config.get("_meta", {}).get("version"),
        }

    @property
    def config(self) -> dict:
        return self._config

    @staticmethod
    def _normalize(s: str) -> str:
        return (s or "").strip().upper()

    def _find_company_entry(self, company: str) -> Optional[dict]:
        """Procura a entrada de uma companhia (tolerante a sinônimos)."""
        key = self._normalize(company)
        companies = self._config.get("companies", {})
        normalized_map = {self._normalize(k): v for k, v in companies.items()}

        # Exact match
        if key in normalized_map:
            return normalized_map[key]

        # Try with " AIRLINES" suffix
        for candidate in (f"{key} AIRLINES", key.replace(" AIRLINES", "")):
            if candidate in normalized_map:
                return normalized_map[candidate]

        # Fuzzy prefix match (e.g., "AMERICAN" matches "AMERICAN AIRLINES")
        for norm_key, entry in normalized_map.items():
            if norm_key.startswith(key) or key.startswith(norm_key):
                return entry

        return None

    def get_coefficient(
        self,
        company: str,
        miles_type: str = "",
        value_type: str = "",
    ) -> tuple[Optional[float], str]:
        """Resolve o coeficiente aplicável. Retorna (valor, fonte)."""
        entry = self._find_company_entry(company)
        if entry is None:
            return None, "NOT_CONFIGURED"

        mt = self._normalize(miles_type)
        vt = self._normalize(value_type)

        # Prioridade 1: by_value_type
        by_vt = entry.get("by_value_type", {}) or {}
        for k, v in by_vt.items():
            if self._normalize(k) == vt and vt:
                return float(v), f"by_value_type:{k}"

        # Prioridade 2: by_miles_type
        by_mt = entry.get("by_miles_type", {}) or {}
        for k, v in by_mt.items():
            if self._normalize(k) == mt and mt:
                return float(v), f"by_miles_type:{k}"

        # Prioridade 3: default
        if "default" in entry:
            return float(entry["default"]), "default"

        return None, "NOT_CONFIGURED"

    def price_miles(
        self,
        company: str,
        miles_total: float,
        fee_embarque: float = 0.0,
        fee_resgate: float = 0.0,
        miles_type: str = "",
        value_type: str = "",
    ) -> PricingResult:
        """Calcula o valor estimado em R$ para uma oferta em milhas."""
        fees = round(float(fee_embarque) + float(fee_resgate), 2)

        if not miles_total or miles_total <= 0:
            return PricingResult(
                estimated_brl=fees,
                miles_converted_brl=0.0,
                fees_brl=fees,
                coefficient=0.0,
                coefficient_source="NO_MILES",
                coefficient_configured=False,
                calc_memory=f"Sem milhas no retorno — apenas taxas: R$ {fees:,.2f}",
                miles_total=0.0,
            )

        coef, source = self.get_coefficient(company, miles_type, value_type)

        if coef is None:
            return PricingResult(
                estimated_brl=0.0,
                miles_converted_brl=0.0,
                fees_brl=fees,
                coefficient=0.0,
                coefficient_source=source,
                coefficient_configured=False,
                calc_memory=(
                    f"⚠ Coeficiente não configurado para '{company}'. "
                    f"Configure em config/coefficients.json e chame POST /api/coefficients/reload."
                ),
                miles_total=float(miles_total),
            )

        miles_brl = round((miles_total / 1000.0) * coef, 2)
        total = round(miles_brl + fees, 2)

        memory = (
            f"({miles_total:,.0f} pts ÷ 1000) × R$ {coef:.2f} [{source}] "
            f"= R$ {miles_brl:,.2f}  +  Taxas R$ {fees:,.2f}  "
            f"=  R$ {total:,.2f}"
        )

        return PricingResult(
            estimated_brl=total,
            miles_converted_brl=miles_brl,
            fees_brl=fees,
            coefficient=float(coef),
            coefficient_source=source,
            coefficient_configured=True,
            calc_memory=memory,
            miles_total=float(miles_total),
        )


# Singleton — compartilhado entre TUI, web e BuscaMilhas client
_engine: Optional[MilesPricingEngine] = None


def get_engine() -> MilesPricingEngine:
    global _engine
    if _engine is None:
        _engine = MilesPricingEngine()
    return _engine


def reload_engine() -> dict:
    """Recarrega os coeficientes sem reiniciar o servidor."""
    return get_engine().reload()
