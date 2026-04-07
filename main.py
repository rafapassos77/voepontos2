#!/usr/bin/env python3
"""
VoePontos – Terminal de Agência de Turismo
Busca em tempo real, detecção de preços assimétricos e análise IA com Claude.

Uso:
    python main.py

Pré-requisitos:
    pip install -r requirements.txt
    cp .env.example .env  # Configure suas chaves API

Modos de operação:
    DEMO  – sem configuração (dados simulados realistas)
    LIVE  – com AMADEUS_API_KEY + AMADEUS_API_SECRET (dados reais)
    IA    – com ANTHROPIC_API_KEY (análise inteligente com Claude Opus)
"""
import sys
import os


def check_dependencies() -> bool:
    missing = []
    for pkg in ["textual", "anthropic", "httpx", "pydantic", "aiosqlite", "dotenv"]:
        try:
            __import__(pkg if pkg != "dotenv" else "dotenv")
        except ImportError:
            missing.append(pkg if pkg != "dotenv" else "python-dotenv")
    if missing:
        print(f"❌ Dependências ausentes: {', '.join(missing)}")
        print(f"   Execute: pip install -r requirements.txt")
        return False
    return True


def print_banner() -> None:
    banner = r"""
  ╔══════════════════════════════════════════════════════╗
  ║                                                      ║
  ║   ✈  VoePontos — Terminal de Agência de Turismo      ║
  ║                                                      ║
  ║   Busca em Tempo Real  |  Preços Assimétricos        ║
  ║   Análise IA com Claude Opus  |  SQLite Cache        ║
  ║                                                      ║
  ╚══════════════════════════════════════════════════════╝
"""
    print(banner)


def main() -> None:
    print_banner()

    if not check_dependencies():
        sys.exit(1)

    # Add project root to path
    sys.path.insert(0, os.path.dirname(__file__))

    from src.config import Config

    # Print startup info
    mode = "DEMO (dados simulados)" if Config.is_demo_mode() else "LIVE (Amadeus API)"
    claude = "✓ Claude ativo" if Config.has_claude() else "✗ Sem Claude (configure ANTHROPIC_API_KEY)"
    print(f"  Modo: {mode}")
    print(f"  IA:   {claude}")
    print(f"  DB:   {Config.DB_PATH}")
    print()

    from src.ui.app import VoePontosApp
    app = VoePontosApp()
    app.run()


if __name__ == "__main__":
    main()
