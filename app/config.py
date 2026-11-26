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


def _booleano(nombre: str, por_defecto: bool) -> bool:
    valor = os.getenv(nombre)
    if valor is None:
        return por_defecto
    return valor.strip().lower() in ("1", "true", "si", "yes")


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

    # desarrollo, pruebas o produccion. En produccion la aplicacion se niega
    # a arrancar con la clave por defecto, y las pruebas de caja negra se
    # niegan a escribir contra ella.
    APP_ENV = os.getenv("APP_ENV", "desarrollo").strip().lower()

    # ------------------------------------------------------------------
    # Sesiones
    #
    # La cookie no es legible desde JavaScript, no viaja en peticiones de
    # otros sitios (SameSite=Strict, que corta la falsificacion de
    # peticiones) y en produccion solo viaja por HTTPS. La sesion caduca.
    # ------------------------------------------------------------------
    SESSION_COOKIE_HTTPONLY = True
    SESSION_COOKIE_SAMESITE = "Strict"
    SESSION_COOKIE_SECURE = _booleano("SESSION_COOKIE_SECURE", APP_ENV == "produccion")
    HORAS_SESION = _entero("HORAS_SESION", 8)

    # Tamano maximo de una peticion. Cubre el fotograma de evidencia.
    MAX_CONTENT_LENGTH = _entero("MAX_CONTENT_MB", 4) * 1024 * 1024

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

    # Horas tras las cuales un ingreso sin salida se da por cerrado. Si alguien
    # entro ayer y no se registro su salida, el evento de hoy es un ingreso,
    # no una salida.
    HORAS_JORNADA_MAXIMA = _entero("HORAS_JORNADA_MAXIMA", 16)

    # ------------------------------------------------------------------
    # Deteccion de armas visibles
    # ------------------------------------------------------------------
    MODELO_YOLO = os.getenv("MODELO_YOLO", "modelos/yolov8n-armas.pt")
    UMBRAL_ARMA = _decimal("UMBRAL_ARMA", 0.70)

    # Minutos que una alerta puede permanecer sin atencion antes de escalar
    # al administrador (RF-14).
    MINUTOS_ESCALAMIENTO = _entero("MINUTOS_ESCALAMIENTO", 5)

    # El servidor revisa solo, cada cierto numero de segundos, si hay alertas
    # que escalar. No depende de que alguien invoque un endpoint.
    ESCALAMIENTO_AUTOMATICO = _booleano("ESCALAMIENTO_AUTOMATICO", True)
    SEGUNDOS_REVISION_ESCALAMIENTO = _entero("SEGUNDOS_REVISION_ESCALAMIENTO", 60)

    # Segundos durante los cuales una nueva deteccion del mismo tipo de arma en
    # la misma camara se suma a la alerta abierta en lugar de crear otra.
    VENTANA_ALERTA = _entero("VENTANA_ALERTA", 120)

    # ------------------------------------------------------------------
    # Evidencias (fotograma de cada alerta)
    #
    # Si se definen SUPABASE_URL y SUPABASE_SERVICE_KEY se guardan en un
    # bucket privado de Supabase Storage. Si no, en una carpeta local.
    # ------------------------------------------------------------------
    EVIDENCIAS_DIR = os.getenv("EVIDENCIAS_DIR", "evidencias")
    SUPABASE_URL = os.getenv("SUPABASE_URL", "").rstrip("/")
    SUPABASE_SERVICE_KEY = os.getenv("SUPABASE_SERVICE_KEY", "")
    SUPABASE_BUCKET = os.getenv("SUPABASE_BUCKET", "evidencias")

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
