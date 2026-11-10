"""Capa de acceso a datos de FaceGuard.

Concentra todas las consultas SQL contra PostgreSQL (Supabase). El resto de la
aplicacion no escribe SQL, lo que mantiene la separacion que exige el RNF-08 y
permite sustituir este modulo por un doble de prueba durante los tests.

Las tablas y columnas corresponden una a una con el script db/schema.sql
documentado en la seccion 3.6 del trabajo de grado.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Optional

import numpy as np

from .db import consultar, ejecutar
from .servicios.reconocimiento_facial import Candidato


# --------------------------------------------------------------------------
# Personas y codificaciones faciales (P1, CU-01)
# --------------------------------------------------------------------------

def crear_persona(
    institucion_id: int,
    documento: str,
    tipo_persona: str,
    nombres: str,
    apellidos: str,
    correo: Optional[str] = None,
    adscripcion: Optional[str] = None,
    autoriza_biometria: bool = False,
) -> int:
    """Registra una persona. El dominio cubre estudiantes, docentes,
    personal administrativo y visitantes, no solo estudiantes."""
    filas = consultar(
        """
        INSERT INTO persona
            (institucion_id, documento, tipo_persona, nombres, apellidos,
             correo, adscripcion, autoriza_biometria, fecha_consentimiento)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s,
                CASE WHEN %s THEN NOW() ELSE NULL END)
        RETURNING id
        """,
        (institucion_id, documento, tipo_persona, nombres, apellidos,
         correo, adscripcion, autoriza_biometria, autoriza_biometria),
    )
    return filas[0]["id"]


def obtener_persona(persona_id: int) -> Optional[dict[str, Any]]:
    filas = consultar("SELECT * FROM persona WHERE id = %s", (persona_id,))
    return filas[0] if filas else None


def obtener_persona_por_documento(
    institucion_id: int, documento: str
) -> Optional[dict[str, Any]]:
    filas = consultar(
        "SELECT * FROM persona WHERE institucion_id = %s AND documento = %s",
        (institucion_id, documento),
    )
    return filas[0] if filas else None


def listar_personas(
    estado: Optional[str] = None, tipo_persona: Optional[str] = None
) -> list[dict[str, Any]]:
    condiciones, parametros = [], []
    if estado:
        condiciones.append("estado = %s")
        parametros.append(estado)
    if tipo_persona:
        condiciones.append("tipo_persona = %s")
        parametros.append(tipo_persona)
    where = f"WHERE {' AND '.join(condiciones)}" if condiciones else ""
    return consultar(
        f"SELECT * FROM persona {where} ORDER BY apellidos, nombres",
        tuple(parametros),
    )


def actualizar_estado_persona(persona_id: int, estado: str) -> int:
    if estado not in ("preinscrito", "enrolado", "activo", "suspendido", "retirado"):
        raise ValueError(f"estado de persona invalido: {estado}")
    return ejecutar(
        "UPDATE persona SET estado = %s WHERE id = %s", (estado, persona_id)
    )


def guardar_codificacion(persona_id: int, vector: np.ndarray) -> int:
    """Almacena la codificacion facial, nunca la imagen original.

    Guardar el vector en lugar de la fotografia es la medida de minimizacion
    que el capitulo I compromete frente a la Ley 1581 de 2012.

    Solo se admite si la persona autorizo el tratamiento biometrico (RF-01).
    """
    persona = obtener_persona(persona_id)
    if persona is None:
        raise ValueError(f"la persona {persona_id} no existe")
    if not persona["autoriza_biometria"]:
        raise PermissionError(
            "la persona no autorizo el tratamiento de sus datos biometricos"
        )

    filas = consultar(
        """
        INSERT INTO codificacion_facial (persona_id, vector)
        VALUES (%s, %s)
        RETURNING id
        """,
        (persona_id, [float(x) for x in np.asarray(vector).ravel()]),
    )
    ejecutar(
        "UPDATE persona SET estado = 'enrolado' WHERE id = %s AND estado = 'preinscrito'",
        (persona_id,),
    )
    return filas[0]["id"]


def eliminar_codificaciones(persona_id: int) -> int:
    """Borra los datos biometricos de una persona (RF-15).

    El historico de accesos se conserva, porque es informacion institucional,
    pero el dato biometrico desaparece. Es el derecho de supresion de la
    Ley 1581 de 2012.
    """
    return ejecutar(
        "DELETE FROM codificacion_facial WHERE persona_id = %s", (persona_id,)
    )


def cargar_catalogo() -> list[Candidato]:
    """Trae las codificaciones de las personas activas con consentimiento.

    Solo entran al catalogo quienes firmaron el consentimiento informado. Una
    persona suspendida o retirada deja de ser identificable, que es el
    comportamiento descrito en el diagrama de estados de la clase Persona.
    """
    filas = consultar(
        """
        SELECT cf.persona_id, cf.vector
        FROM codificacion_facial cf
        JOIN persona p ON p.id = cf.persona_id
        WHERE cf.activa = TRUE
          AND p.estado IN ('enrolado', 'activo')
          AND p.autoriza_biometria = TRUE
        """
    )
    return [
        Candidato(
            persona_id=f["persona_id"],
            vector=np.asarray(f["vector"], dtype=np.float64),
        )
        for f in filas
    ]


# --------------------------------------------------------------------------
# Registros de acceso (P2, CU-02, CU-05, CU-10, CU-11)
# --------------------------------------------------------------------------

def ultimo_registro(persona_id: int) -> Optional[dict[str, Any]]:
    """Ultimo evento de la persona, con su tipo y su marca de tiempo.

    Devuelve ambos datos porque el tipo decide si el siguiente evento es
    ingreso o salida, y la fecha decide si el evento es un rebote que no debe
    registrarse.
    """
    filas = consultar(
        """
        SELECT id, tipo_evento, fecha_hora
        FROM registro_acceso
        WHERE persona_id = %s
        ORDER BY fecha_hora DESC
        LIMIT 1
        """,
        (persona_id,),
    )
    return filas[0] if filas else None


def registrar_acceso(
    punto_acceso_id: int,
    tipo_evento: str,
    resultado: str,
    persona_id: Optional[int] = None,
    camara_id: Optional[int] = None,
    metodo: str = "facial",
    distancia: Optional[float] = None,
    confianza: Optional[float] = None,
    imagen_url: Optional[str] = None,
) -> int:
    """Inserta un evento de acceso.

    persona_id admite nulo a proposito: los eventos que el sistema no logra
    identificar tambien quedan registrados, con su evidencia, para que el
    guardia los verifique (RF-11).
    """
    if tipo_evento not in ("ingreso", "salida"):
        raise ValueError("tipo_evento debe ser 'ingreso' o 'salida'")
    if resultado not in ("identificado", "no_identificado", "verificado_manual", "rechazado"):
        raise ValueError(f"resultado invalido: {resultado}")
    if resultado == "identificado" and persona_id is None:
        raise ValueError("un evento identificado debe indicar a que persona")
    if metodo not in ("facial", "credencial", "manual"):
        raise ValueError(f"metodo invalido: {metodo}")

    filas = consultar(
        """
        INSERT INTO registro_acceso
            (punto_acceso_id, camara_id, persona_id, tipo_evento, metodo,
             resultado, distancia, confianza, imagen_url)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
        RETURNING id
        """,
        (punto_acceso_id, camara_id, persona_id, tipo_evento, metodo, resultado,
         None if distancia is None else round(float(distancia), 4),
         None if confianza is None else round(float(confianza), 4),
         imagen_url),
    )
    return filas[0]["id"]


def verificar_acceso_manual(
    registro_id: int, usuario_id: int, persona_id: Optional[int], aprobado: bool
) -> int:
    """El guardia resuelve un evento no identificado (RF-12, CU-10)."""
    resultado = "verificado_manual" if aprobado else "rechazado"
    return ejecutar(
        """
        UPDATE registro_acceso
        SET resultado = %s, persona_id = COALESCE(%s, persona_id),
            verificado_por = %s, fecha_verificacion = NOW()
        WHERE id = %s AND resultado = 'no_identificado'
        """,
        (resultado, persona_id, usuario_id, registro_id),
    )


def listar_accesos(
    desde: Optional[datetime] = None,
    hasta: Optional[datetime] = None,
    persona_id: Optional[int] = None,
    punto_acceso_id: Optional[int] = None,
    resultado: Optional[str] = None,
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
    if persona_id is not None:
        condiciones.append("ra.persona_id = %s")
        parametros.append(persona_id)
    if punto_acceso_id is not None:
        condiciones.append("ra.punto_acceso_id = %s")
        parametros.append(punto_acceso_id)
    if resultado is not None:
        condiciones.append("ra.resultado = %s")
        parametros.append(resultado)

    where = f"WHERE {' AND '.join(condiciones)}" if condiciones else ""
    parametros.append(limite)

    return consultar(
        f"""
        SELECT ra.id, ra.fecha_hora, ra.tipo_evento, ra.metodo, ra.resultado,
               ra.distancia, ra.confianza, ra.imagen_url,
               p.documento, p.nombres, p.apellidos, p.tipo_persona,
               pa.nombre AS punto_acceso
        FROM registro_acceso ra
        LEFT JOIN persona p ON p.id = ra.persona_id
        JOIN punto_acceso pa ON pa.id = ra.punto_acceso_id
        {where}
        ORDER BY ra.fecha_hora DESC
        LIMIT %s
        """,
        tuple(parametros),
    )


# --------------------------------------------------------------------------
# Alertas de arma visible (P3, P4)
# --------------------------------------------------------------------------

def crear_alerta(
    camara_id: int,
    punto_acceso_id: int,
    tipo_arma: str,
    confianza: float,
    registro_acceso_id: Optional[int] = None,
    persona_id: Optional[int] = None,
    imagen_url: Optional[str] = None,
) -> int:
    """Crea la alerta unida al evento de acceso y a la persona.

    Esas dos referencias son el aporte central del trabajo: permiten
    responder quien llevaba el arma, no solo donde fue detectada.
    """
    if tipo_arma not in ("arma_fuego", "arma_blanca", "indeterminada"):
        raise ValueError(f"tipo_arma invalido: {tipo_arma}")
    filas = consultar(
        """
        INSERT INTO alerta_arma
            (camara_id, punto_acceso_id, registro_acceso_id, persona_id,
             tipo_arma, confianza, imagen_url)
        VALUES (%s, %s, %s, %s, %s, %s, %s)
        RETURNING id
        """,
        (camara_id, punto_acceso_id, registro_acceso_id, persona_id,
         tipo_arma, round(float(confianza), 4), imagen_url),
    )
    return filas[0]["id"]


def obtener_alerta(alerta_id: int) -> Optional[dict[str, Any]]:
    filas = consultar("SELECT * FROM alerta_arma WHERE id = %s", (alerta_id,))
    return filas[0] if filas else None


def actualizar_estado_alerta(
    alerta_id: int,
    estado: str,
    usuario_id: Optional[int] = None,
    escalada: bool = False,
) -> int:
    campos = ["estado = %s"]
    parametros: list[Any] = [estado]
    if usuario_id is not None:
        campos.append("atendida_por = %s")
        parametros.append(usuario_id)
        campos.append("fecha_atencion = NOW()")
    if escalada:
        campos.append("fecha_escalamiento = NOW()")
    parametros.append(alerta_id)
    return ejecutar(
        f"UPDATE alerta_arma SET {', '.join(campos)} WHERE id = %s",
        tuple(parametros),
    )


def listar_alertas(estado: Optional[str] = None, limite: int = 100) -> list[dict[str, Any]]:
    """Lista alertas con la persona asociada, usando la vista del modelo."""
    if estado:
        return consultar(
            "SELECT * FROM v_alerta_persona WHERE estado = %s "
            "ORDER BY fecha_hora DESC LIMIT %s",
            (estado, limite),
        )
    return consultar(
        "SELECT * FROM v_alerta_persona ORDER BY fecha_hora DESC LIMIT %s",
        (limite,),
    )


def alertas_sin_atender(minutos: int) -> list[dict[str, Any]]:
    """Alertas notificadas que nadie tomo dentro del tiempo definido (RF-14)."""
    return consultar(
        """
        SELECT id, camara_id, punto_acceso_id, persona_id, fecha_hora
        FROM alerta_arma
        WHERE estado IN ('generada', 'notificada')
          AND fecha_hora < NOW() - (%s * INTERVAL '1 minute')
        """,
        (minutos,),
    )


# --------------------------------------------------------------------------
# Usuarios y roles (CU-07, RF-08)
# --------------------------------------------------------------------------

def obtener_usuario_por_correo(correo: str) -> Optional[dict[str, Any]]:
    filas = consultar(
        """
        SELECT u.*, r.nombre AS rol, r.permisos
        FROM usuario u JOIN rol r ON r.id = u.rol_id
        WHERE u.correo = %s
        """,
        (correo,),
    )
    return filas[0] if filas else None


def obtener_usuario(usuario_id: int) -> Optional[dict[str, Any]]:
    filas = consultar(
        """
        SELECT u.*, r.nombre AS rol, r.permisos
        FROM usuario u JOIN rol r ON r.id = u.rol_id
        WHERE u.id = %s
        """,
        (usuario_id,),
    )
    return filas[0] if filas else None


def crear_usuario(
    nombre: str, correo: str, contrasena_hash: str, rol_id: int
) -> int:
    filas = consultar(
        """
        INSERT INTO usuario (nombre, correo, contrasena_hash, rol_id)
        VALUES (%s, %s, %s, %s) RETURNING id
        """,
        (nombre, correo, contrasena_hash, rol_id),
    )
    return filas[0]["id"]


def listar_usuarios() -> list[dict[str, Any]]:
    return consultar(
        """
        SELECT u.id, u.nombre, u.correo, u.estado, u.intentos_fallidos,
               u.ultimo_acceso, r.nombre AS rol
        FROM usuario u JOIN rol r ON r.id = u.rol_id
        ORDER BY u.nombre
        """
    )


def registrar_intento_fallido(usuario_id: int, maximo: int) -> int:
    """Suma un intento fallido y bloquea la cuenta al alcanzar el maximo."""
    return ejecutar(
        """
        UPDATE usuario
        SET intentos_fallidos = intentos_fallidos + 1,
            estado = CASE WHEN intentos_fallidos + 1 >= %s THEN 'bloqueado'
                          ELSE estado END
        WHERE id = %s
        """,
        (maximo, usuario_id),
    )


def reiniciar_intentos(usuario_id: int) -> int:
    return ejecutar(
        """
        UPDATE usuario
        SET intentos_fallidos = 0, ultimo_acceso = NOW(),
            estado = CASE WHEN estado = 'registrado' THEN 'activo' ELSE estado END
        WHERE id = %s
        """,
        (usuario_id,),
    )


def cambiar_estado_usuario(usuario_id: int, estado: str) -> int:
    if estado not in ("registrado", "activo", "bloqueado", "inactivo"):
        raise ValueError(f"estado de usuario invalido: {estado}")
    campos = "estado = %s, intentos_fallidos = 0" if estado == "activo" else "estado = %s"
    return ejecutar(f"UPDATE usuario SET {campos} WHERE id = %s", (estado, usuario_id))


# --------------------------------------------------------------------------
# Puntos de acceso y camaras (CU-08, RF-16)
# --------------------------------------------------------------------------

def listar_puntos_acceso() -> list[dict[str, Any]]:
    return consultar("SELECT * FROM punto_acceso ORDER BY nombre")


def crear_punto_acceso(institucion_id: int, nombre: str, ubicacion: str = None) -> int:
    filas = consultar(
        "INSERT INTO punto_acceso (institucion_id, nombre, ubicacion) "
        "VALUES (%s, %s, %s) RETURNING id",
        (institucion_id, nombre, ubicacion),
    )
    return filas[0]["id"]


def listar_camaras(punto_acceso_id: Optional[int] = None) -> list[dict[str, Any]]:
    if punto_acceso_id is not None:
        return consultar(
            "SELECT * FROM camara WHERE punto_acceso_id = %s ORDER BY identificador",
            (punto_acceso_id,),
        )
    return consultar("SELECT * FROM camara ORDER BY punto_acceso_id, identificador")


def crear_camara(
    punto_acceso_id: int,
    identificador: str,
    tipo: Optional[str] = None,
    resolucion_ancho: Optional[int] = None,
    resolucion_alto: Optional[int] = None,
    lux_minimo: Optional[int] = None,
) -> int:
    filas = consultar(
        """
        INSERT INTO camara (punto_acceso_id, identificador, tipo,
                            resolucion_ancho, resolucion_alto, lux_minimo)
        VALUES (%s, %s, %s, %s, %s, %s) RETURNING id
        """,
        (punto_acceso_id, identificador, tipo, resolucion_ancho,
         resolucion_alto, lux_minimo),
    )
    return filas[0]["id"]


# --------------------------------------------------------------------------
# Bitacora de auditoria (RNF-04, CU-05)
# --------------------------------------------------------------------------

def registrar_auditoria(
    usuario_id: Optional[int],
    accion: str,
    entidad: Optional[str] = None,
    entidad_id: Optional[int] = None,
    detalle: Optional[str] = None,
    ip_origen: Optional[str] = None,
) -> int:
    filas = consultar(
        """
        INSERT INTO auditoria (usuario_id, accion, entidad, entidad_id,
                               detalle, ip_origen)
        VALUES (%s, %s, %s, %s, %s, %s) RETURNING id
        """,
        (usuario_id, accion, entidad, entidad_id, detalle, ip_origen),
    )
    return filas[0]["id"]


def listar_auditoria(limite: int = 200) -> list[dict[str, Any]]:
    return consultar(
        """
        SELECT a.*, u.nombre AS usuario
        FROM auditoria a LEFT JOIN usuario u ON u.id = a.usuario_id
        ORDER BY a.fecha_hora DESC LIMIT %s
        """,
        (limite,),
    )


# --------------------------------------------------------------------------
# Reportes (RF-10). Se generan en el momento, no se persisten.
# --------------------------------------------------------------------------

def resumen_accesos(desde: datetime, hasta: datetime) -> dict[str, Any]:
    filas = consultar(
        """
        SELECT resultado, COUNT(*) AS total
        FROM registro_acceso
        WHERE fecha_hora BETWEEN %s AND %s
        GROUP BY resultado
        """,
        (desde, hasta),
    )
    alertas = consultar(
        """
        SELECT tipo_arma, estado, COUNT(*) AS total
        FROM alerta_arma
        WHERE fecha_hora BETWEEN %s AND %s
        GROUP BY tipo_arma, estado
        """,
        (desde, hasta),
    )
    return {"accesos": filas, "alertas": alertas}
