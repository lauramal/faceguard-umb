"""Configuracion de la aplicacion, leida de variables de entorno.

Ninguna credencial queda escrita en el codigo. El archivo .env no se versiona
y .env.example documenta que variables hacen falta.
"""

from __future__ import annotations

import os

from dotenv import load_dotenv

load_dotenv()


def _entero(nombre: str, por_defecto: int) -> int:
    try:
        return int(os.getenv(nombre, por_defecto))
    except ValueError:
        return por_defecto


def _decimal(nombre: str, por_defecto: float) -> float:
    try:
        return float(os.getenv(nombre, por_defecto))
    except ValueError:
        return por_defecto


class Config:
    # Flask
    SECRET_KEY = os.getenv("SECRET_KEY", "cambiar-en-produccion")
    DEBUG = os.getenv("FLASK_DEBUG", "0") == "1"

    # Base de datos PostgreSQL en Supabase
    DATABASE_URL = os.getenv("DATABASE_URL", "")
    DB_MAX_CONEXIONES = _entero("DB_MAX_CONEXIONES", 5)

    # Reconocimiento facial
    UMBRAL_CONFIANZA = _decimal("UMBRAL_CONFIANZA", 0.85)
    UMBRAL_DISTANCIA = _decimal("UMBRAL_DISTANCIA", 0.60)

    # Deteccion de armas (sprint 3)
    MODELO_YOLO = os.getenv("MODELO_YOLO", "modelos/yolov8n-armas.pt")
    UMBRAL_ARMA = _decimal("UMBRAL_ARMA", 0.70)

    # Ventana en segundos para no duplicar un mismo evento de acceso
    VENTANA_ANTIREBOTE = _entero("VENTANA_ANTIREBOTE", 30)
