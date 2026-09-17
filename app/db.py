"""Conexion a PostgreSQL (Supabase) con un pool sencillo.

Se usa psycopg2 con RealDictCursor para que cada fila llegue como diccionario,
lo que evita acoplar el resto del codigo al orden de las columnas.
"""

from __future__ import annotations

import logging
from contextlib import contextmanager
from typing import Any, Iterator, Optional, Sequence

from .config import Config

log = logging.getLogger(__name__)

_pool = None


def inicializar_pool(dsn: Optional[str] = None) -> None:
    """Crea el pool de conexiones. Se llama una vez al arrancar la aplicacion."""
    global _pool
    if _pool is not None:
        return

    from psycopg2 import pool as pg_pool

    _pool = pg_pool.ThreadedConnectionPool(
        minconn=1,
        maxconn=Config.DB_MAX_CONEXIONES,
        dsn=dsn or Config.DATABASE_URL,
    )
    log.info("Pool de conexiones inicializado")


def cerrar_pool() -> None:
    global _pool
    if _pool is not None:
        _pool.closeall()
        _pool = None


@contextmanager
def conexion() -> Iterator[Any]:
    """Entrega una conexion del pool y la devuelve al terminar.

    Hace commit si el bloque termina bien y rollback si algo falla, de modo
    que un error a mitad de una operacion no deje datos inconsistentes.
    """
    if _pool is None:
        inicializar_pool()

    conn = _pool.getconn()
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        _pool.putconn(conn)


@contextmanager
def cursor() -> Iterator[Any]:
    from psycopg2.extras import RealDictCursor

    with conexion() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            yield cur


def consultar(sql: str, parametros: Sequence[Any] = ()) -> list[dict[str, Any]]:
    """Ejecuta una consulta y devuelve todas las filas."""
    with cursor() as cur:
        cur.execute(sql, parametros)
        if cur.description is None:
            return []
        return [dict(fila) for fila in cur.fetchall()]


def ejecutar(sql: str, parametros: Sequence[Any] = ()) -> int:
    """Ejecuta una sentencia y devuelve el numero de filas afectadas."""
    with cursor() as cur:
        cur.execute(sql, parametros)
        return cur.rowcount
