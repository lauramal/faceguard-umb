"""Salvaguarda para que las pruebas nunca toquen una base real.

Las pruebas de integracion y de caja negra empiezan con
DROP SCHEMA public CASCADE. Apuntadas por error a la base de produccion,
borrarian todos los registros. Antes de tocar nada se exige que:

1. la base de pruebas no sea la misma que DATABASE_URL, y
2. el nombre de la base contenga "test" o "prueba", lo que obliga a crear una
   base desechable a proposito (por ejemplo faceguard_test).

Si no se cumple, la ejecucion se detiene con un mensaje claro.
"""

from __future__ import annotations

import os
from urllib.parse import urlparse

import pytest

MARCAS = ("test", "prueba")


def nombre_de_base(url: str) -> str:
    return urlparse(url).path.lstrip("/").split("?")[0].lower()


def motivo_de_rechazo(url_pruebas: str, url_aplicacion: str = "") -> str | None:
    """Devuelve por que la base no es apta para pruebas, o None si lo es."""
    if not url_pruebas:
        return "TEST_DATABASE_URL esta vacia"
    if url_aplicacion and url_pruebas.strip() == url_aplicacion.strip():
        return "TEST_DATABASE_URL es la misma base que DATABASE_URL"
    nombre = nombre_de_base(url_pruebas)
    if not any(marca in nombre for marca in MARCAS):
        return (f"la base '{nombre}' no parece desechable: su nombre debe contener "
                f"'test' o 'prueba' (por ejemplo faceguard_test)")
    return None


def exigir_bd_desechable(url_pruebas: str) -> None:
    motivo = motivo_de_rechazo(url_pruebas, os.getenv("DATABASE_URL", ""))
    if motivo:
        pytest.exit(f"Pruebas detenidas para proteger los datos: {motivo}", returncode=4)
