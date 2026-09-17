"""Capa de acceso a datos de FaceGuard UMB.

Concentra todas las consultas SQL contra PostgreSQL (Supabase). El resto de la
aplicacion no escribe SQL, lo que mantiene la separacion que exige el RNF-08 y
permite sustituir este modulo por un doble de prueba durante los tests.

Las tablas y columnas corresponden una a una con el script db/schema.sql
documentado en la seccion 3.6 del trabajo de grado.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Iterable, Optional

import numpy as np

from .db import consultar, ejecutar
from .servicios.reconocimiento_facial import Candidato


# --------------------------------------------------------------------------
# Estudiantes y codificaciones faciales (P1, CU-01)
# --------------------------------------------------------------------------

def crear_estudiante(
    codigo: str,
    nombres: str,
    apellidos: str,
    correo: Optional[str] = None,
    programa: Optional[str] = None,
    consentimiento_firmado: bool = False,
) -> int:
    filas = consultar(
        """
        INSERT INTO estudiante
            (codigo, nombres, apellidos, correo, programa, consentimiento_firmado)
        VALUES (%s, %s, %s, %s, %s, %s)
        RETURNING id
        """,
        (codigo, nombres, apellidos, correo, programa, consentimiento_firmado),
    )
    return filas[0]["id"]


def obtener_estudiante(estudiante_id: int) -> Optional[dict[str, Any]]:
    filas = consultar("SELECT * FROM estudiante WHERE id = %s", (estudiante_id,))
    return filas[0] if filas else None


def obtener_estudiante_por_codigo(codigo: str) -> Optional[dict[str, Any]]:
    filas = consultar("SELECT * FROM estudiante WHERE codigo = %s", (codigo,))
    return filas[0] if filas else None


def listar_estudiantes(estado: Optional[str] = None) -> list[dict[str, Any]]:
    if estado:
        return consultar(
            "SELECT * FROM estudiante WHERE estado = %s ORDER BY apellidos, nombres",
            (estado,),
        )
    return consultar("SELECT * FROM estudiante ORDER BY apellidos, nombres")


def guardar_codificacion(estudiante_id: int, vector: np.ndarray) -> int:
    """Almacena la codificacion facial, nunca la imagen original.

    Guardar el vector en lugar de la fotografia es la medida de minimizacion
    que el capitulo I compromete frente a la Ley 1581 de 2012.
    """
    filas = consultar(
        """
        INSERT INTO codificacion_facial (estudiante_id, vector)
        VALUES (%s, %s)
        RETURNING id
        """,
        (estudiante_id, [float(x) for x in np.asarray(vector).ravel()]),
    )
    return filas[0]["id"]


def cargar_catalogo() -> list[Candidato]:
    """Trae las codificaciones de los estudiantes activos con consentimiento.

    Solo entran al catalogo quienes firmaron el consentimiento informado. Un
    estudiante suspendido o retirado deja de ser identificable, que es el
    comportamiento descrito en el diagrama de estados de la clase Estudiante.
    """
    filas = consultar(
        """
        SELECT cf.estudiante_id, cf.vector
        FROM codificacion_facial cf
        JOIN estudiante e ON e.id = cf.estudiante_id
        WHERE e.estado = 'activo' AND e.consentimiento_firmado = TRUE
        """
    )
    return [
        Candidato(
            estudiante_id=f["estudiante_id"],
            vector=np.asarray(f["vector"], dtype=np.float64),
        )
        for f in filas
    ]


# --------------------------------------------------------------------------
# Registros de acceso (P2, CU-02, CU-05)
# --------------------------------------------------------------------------

def ultimo_evento(estudiante_id: int) -> Optional[str]:
    filas = consultar(
        """
        SELECT tipo_evento FROM registro_acceso
        WHERE estudiante_id = %s
        ORDER BY fecha_hora DESC
        LIMIT 1
        """,
        (estudiante_id,),
    )
    return filas[0]["tipo_evento"] if filas else None


def registrar_acceso(
    estudiante_id: int,
    punto_acceso_id: int,
    tipo_evento: str,
    confianza: float,
) -> int:
    if tipo_evento not in ("ingreso", "salida"):
        raise ValueError("tipo_evento debe ser 'ingreso' o 'salida'")
    filas = consultar(
        """
        INSERT INTO registro_acceso
            (estudiante_id, punto_acceso_id, tipo_evento, confianza)
        VALUES (%s, %s, %s, %s)
        RETURNING id
        """,
        (estudiante_id, punto_acceso_id, tipo_evento, round(float(confianza), 4)),
    )
    return filas[0]["id"]


def listar_accesos(
    desde: Optional[datetime] = None,
    hasta: Optional[datetime] = None,
    estudiante_id: Optional[int] = None,
    punto_acceso_id: Optional[int] = None,
    limite: int = 200,
) -> list[dict[str, Any]]:
    """Consulta del historial con los filtros que pide el RF-09."""
    condiciones: list[str] = []
    parametros: list[Any] = []

    if desde is not None:
        condiciones.append("ra.fecha_hora >= %s")
        parametros.append(desde)
    if hasta is not None:
        condiciones.append("ra.fecha_hora <= %s")
        parametros.append(hasta)
    if estudiante_id is not None:
        condiciones.append("ra.estudiante_id = %s")
        parametros.append(estudiante_id)
    if punto_acceso_id is not None:
        condiciones.append("ra.punto_acceso_id = %s")
        parametros.append(punto_acceso_id)

    where = f"WHERE {' AND '.join(condiciones)}" if condiciones else ""
    parametros.append(limite)

    return consultar(
        f"""
        SELECT ra.id, ra.fecha_hora, ra.tipo_evento, ra.confianza,
               e.codigo, e.nombres, e.apellidos,
               pa.nombre AS punto_acceso
        FROM registro_acceso ra
        JOIN estudiante e ON e.id = ra.estudiante_id
        JOIN punto_acceso pa ON pa.id = ra.punto_acceso_id
        {where}
        ORDER BY ra.fecha_hora DESC
        LIMIT %s
        """,
        tuple(parametros),
    )


# --------------------------------------------------------------------------
# Alertas de armas (P3, P4) - se completa en el sprint 3
# --------------------------------------------------------------------------

def crear_alerta(
    camara_id: int,
    tipo_arma: str,
    confianza: float,
    imagen_url: Optional[str] = None,
) -> int:
    filas = consultar(
        """
        INSERT INTO alerta_arma (camara_id, tipo_arma, confianza, imagen_url)
        VALUES (%s, %s, %s, %s)
        RETURNING id
        """,
        (camara_id, tipo_arma, round(float(confianza), 4), imagen_url),
    )
    return filas[0]["id"]


def listar_alertas(estado: Optional[str] = None) -> list[dict[str, Any]]:
    if estado:
        return consultar(
            "SELECT * FROM alerta_arma WHERE estado = %s ORDER BY fecha_hora DESC",
            (estado,),
        )
    return consultar("SELECT * FROM alerta_arma ORDER BY fecha_hora DESC LIMIT 100")


def cerrar_alerta(alerta_id: int, usuario_id: int, estado: str) -> None:
    if estado not in ("confirmada", "falso_positivo"):
        raise ValueError("estado debe ser 'confirmada' o 'falso_positivo'")
    ejecutar(
        "UPDATE alerta_arma SET estado = %s, atendida_por = %s WHERE id = %s",
        (estado, usuario_id, alerta_id),
    )


# --------------------------------------------------------------------------
# Usuarios y roles (CU-07, RF-08)
# --------------------------------------------------------------------------

def obtener_usuario_por_correo(correo: str) -> Optional[dict[str, Any]]:
    filas = consultar(
        """
        SELECT u.*, r.nombre AS rol
        FROM usuario u JOIN rol r ON r.id = u.rol_id
        WHERE u.correo = %s AND u.activo = TRUE
        """,
        (correo,),
    )
    return filas[0] if filas else None


def listar_puntos_acceso() -> list[dict[str, Any]]:
    return consultar("SELECT * FROM punto_acceso ORDER BY nombre")
