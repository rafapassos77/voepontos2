#!/usr/bin/env python3
"""
Ponto de entrada do servidor web VoePontos.
Uso: python run_web.py
Acesse: http://localhost:8000
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        "src.web.server:app",
        reload=True,
        port=8000,
        host="0.0.0.0",
        log_level="info",
    )
