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
    # ------------------------------------------------------------------
    # Flask
    # ------------------------------------------------------------------
    SECRET_KEY = os.getenv("SECRET_KEY", "cambiar-en-produccion")
    DEBUG = os.getenv("FLASK_DEBUG", "0") == "1"

    # ------------------------------------------------------------------
    # Base de datos PostgreSQL en Supabase
    # ------------------------------------------------------------------
    DATABASE_URL = os.getenv("DATABASE_URL", "")
    DB_MAX_CONEXIONES = _entero("DB_MAX_CONEXIONES", 5)

    # ------------------------------------------------------------------
    # Reconocimiento facial
    #
    # La decision de identidad se toma sobre la DISTANCIA euclidiana entre
    # codificaciones, que es lo que el algoritmo calcula. 0.6 es el valor de
    # referencia de dlib: por debajo se considera la misma persona.
    #
    # La confianza es una lectura normalizada de esa distancia y se guarda
    # con fines informativos y de reporte. No se usa como criterio de corte.
    # Confundir ambas cosas hacia que el sistema no reconociera a nadie,
    # porque exigir confianza 0.85 equivale a pedir una distancia de 0.09.
    # ------------------------------------------------------------------
    UMBRAL_DISTANCIA = _decimal("UMBRAL_DISTANCIA", 0.60)

    # Ventana en segundos para no duplicar un mismo evento de acceso. Sin
    # ella, una persona parada frente a la camara genera un registro por
    # fotograma, alternando ingreso y salida.
    VENTANA_ANTIREBOTE = _entero("VENTANA_ANTIREBOTE", 30)

    # ------------------------------------------------------------------
    # Deteccion de armas visibles
    # ------------------------------------------------------------------
    MODELO_YOLO = os.getenv("MODELO_YOLO", "modelos/yolov8n-armas.pt")
    UMBRAL_ARMA = _decimal("UMBRAL_ARMA", 0.70)

    # Minutos que una alerta puede permanecer sin atencion antes de escalar
    # al administrador (RF-14).
    MINUTOS_ESCALAMIENTO = _entero("MINUTOS_ESCALAMIENTO", 5)

    # ------------------------------------------------------------------
    # Seguridad de las cuentas
    # ------------------------------------------------------------------
    # Intentos fallidos consecutivos antes de bloquear la cuenta (RNF-04).
    MAX_INTENTOS_FALLIDOS = _entero("MAX_INTENTOS_FALLIDOS", 5)

    # ------------------------------------------------------------------
    # Hardware minimo exigido por el RNF-14
    # ------------------------------------------------------------------
    RESOLUCION_MINIMA_ANCHO = _entero("RESOLUCION_MINIMA_ANCHO", 1280)
    RESOLUCION_MINIMA_ALTO = _entero("RESOLUCION_MINIMA_ALTO", 720)
    LUX_MINIMO = _entero("LUX_MINIMO", 200)
