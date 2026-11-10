"""Gestion de personas y enrolamiento facial (CU-01, CU-08, CU-12)."""

from __future__ import annotations

import base64
import io

import numpy as np
from flask import Blueprint, g, jsonify, request

from .. import repositorio
from ..seguridad import requiere_rol

bp = Blueprint("personas", __name__, url_prefix="/api/personas")

TIPOS = ("estudiante", "docente", "administrativo", "visitante")


def decodificar_imagen(datos_base64: str) -> np.ndarray:
    """Convierte la imagen que envia el cliente en un arreglo RGB."""
    from PIL import Image

    if "," in datos_base64:          # data:image/jpeg;base64,....
        datos_base64 = datos_base64.split(",", 1)[1]
    binario = base64.b64decode(datos_base64)
    imagen = Image.open(io.BytesIO(binario)).convert("RGB")
    return np.asarray(imagen)


@bp.get("")
@requiere_rol("administrador", "guardia", "consulta")
def listar():
    return jsonify({
        "personas": repositorio.listar_personas(
            estado=request.args.get("estado"),
            tipo_persona=request.args.get("tipo_persona"),
        )
    })


@bp.post("")
@requiere_rol("administrador")
def crear():
    cuerpo = request.get_json(silent=True) or {}
    faltan = [c for c in ("institucion_id", "documento", "tipo_persona",
                          "nombres", "apellidos") if not cuerpo.get(c)]
    if faltan:
        return jsonify({"error": f"faltan campos: {', '.join(faltan)}"}), 400
    if cuerpo["tipo_persona"] not in TIPOS:
        return jsonify({"error": f"tipo_persona debe ser uno de {TIPOS}"}), 400

    persona_id = repositorio.crear_persona(
        institucion_id=int(cuerpo["institucion_id"]),
        documento=str(cuerpo["documento"]),
        tipo_persona=cuerpo["tipo_persona"],
        nombres=cuerpo["nombres"],
        apellidos=cuerpo["apellidos"],
        correo=cuerpo.get("correo"),
        adscripcion=cuerpo.get("adscripcion"),
        autoriza_biometria=bool(cuerpo.get("autoriza_biometria", False)),
    )
    repositorio.registrar_auditoria(
        g.usuario["id"], "crear_persona", "persona", persona_id
    )
    return jsonify({"id": persona_id}), 201


@bp.get("/<int:persona_id>")
@requiere_rol("administrador", "guardia", "consulta")
def detalle(persona_id: int):
    persona = repositorio.obtener_persona(persona_id)
    if persona is None:
        return jsonify({"error": "persona no encontrada"}), 404
    return jsonify(persona)


@bp.post("/<int:persona_id>/enrolar")
@requiere_rol("administrador")
def enrolar(persona_id: int):
    """Captura la codificacion facial de la persona (CU-01).

    Si la persona no autorizo el tratamiento biometrico, el repositorio
    rechaza la operacion y el endpoint responde 409.
    """
    from ..servicios.reconocimiento_facial import (
        RostroNoDetectado, VariosRostros, codificar_rostro,
        promediar_codificaciones,
    )

    cuerpo = request.get_json(silent=True) or {}
    imagenes = cuerpo.get("imagenes") or ([cuerpo["imagen"]] if cuerpo.get("imagen") else [])
    if not imagenes:
        return jsonify({"error": "se requiere al menos una imagen"}), 400

    try:
        codificaciones = [
            codificar_rostro(decodificar_imagen(img), estricto=True)
            for img in imagenes
        ]
    except RostroNoDetectado:
        return jsonify({"error": "no se detecto ningun rostro"}), 400
    except VariosRostros:
        return jsonify({"error": "la imagen contiene mas de un rostro"}), 400
    except Exception:
        return jsonify({"error": "la imagen no pudo procesarse"}), 400

    vector = promediar_codificaciones(codificaciones)

    try:
        codificacion_id = repositorio.guardar_codificacion(persona_id, vector)
    except PermissionError as exc:
        return jsonify({"error": str(exc)}), 409
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 404

    repositorio.registrar_auditoria(
        g.usuario["id"], "enrolar_persona", "persona", persona_id,
        f"{len(codificaciones)} capturas",
    )
    return jsonify({"codificacion_id": codificacion_id}), 201


@bp.delete("/<int:persona_id>/biometria")
@requiere_rol("administrador")
def eliminar_biometria(persona_id: int):
    """Derecho de supresion de datos biometricos (RF-15, CU-12).

    Elimina las codificaciones y conserva el historico de accesos, que es
    informacion institucional y no dato biometrico.
    """
    if repositorio.obtener_persona(persona_id) is None:
        return jsonify({"error": "persona no encontrada"}), 404

    borradas = repositorio.eliminar_codificaciones(persona_id)
    repositorio.registrar_auditoria(
        g.usuario["id"], "eliminar_biometria", "persona", persona_id,
        f"{borradas} codificaciones eliminadas",
    )
    return jsonify({"persona_id": persona_id, "codificaciones_eliminadas": borradas})


@bp.patch("/<int:persona_id>/estado")
@requiere_rol("administrador")
def cambiar_estado(persona_id: int):
    cuerpo = request.get_json(silent=True) or {}
    estado = cuerpo.get("estado")
    try:
        filas = repositorio.actualizar_estado_persona(persona_id, estado)
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400
    if not filas:
        return jsonify({"error": "persona no encontrada"}), 404

    # Al retirar a alguien se eliminan sus datos biometricos (RF-15).
    if estado == "retirado":
        repositorio.eliminar_codificaciones(persona_id)

    repositorio.registrar_auditoria(
        g.usuario["id"], "cambiar_estado_persona", "persona", persona_id, estado
    )
    return jsonify({"persona_id": persona_id, "estado": estado})
