"""Endpoints de estudiantes y enrolamiento facial (CU-01, CU-08)."""

from __future__ import annotations

import base64
import io

import numpy as np
from flask import Blueprint, jsonify, request

from .. import repositorio
from ..seguridad import requiere_rol
from ..servicios.reconocimiento_facial import (
    RostroNoDetectado,
    VariosRostros,
    codificar_rostro,
    promediar_codificaciones,
)

bp = Blueprint("estudiantes", __name__, url_prefix="/api/estudiantes")


def _decodificar(imagen_b64: str) -> np.ndarray:
    from PIL import Image

    if "," in imagen_b64:
        imagen_b64 = imagen_b64.split(",", 1)[1]
    binario = base64.b64decode(imagen_b64)
    return np.asarray(Image.open(io.BytesIO(binario)).convert("RGB"))


@bp.get("")
@requiere_rol("administrador", "guardia", "consulta")
def listar():
    return jsonify(repositorio.listar_estudiantes(request.args.get("estado")))


@bp.post("")
@requiere_rol("administrador")
def crear():
    cuerpo = request.get_json(silent=True) or {}

    faltantes = [c for c in ("codigo", "nombres", "apellidos") if not cuerpo.get(c)]
    if faltantes:
        return jsonify({"error": f"faltan campos: {', '.join(faltantes)}"}), 400

    if repositorio.obtener_estudiante_por_codigo(cuerpo["codigo"]):
        return jsonify({"error": "ya existe un estudiante con ese codigo"}), 409

    estudiante_id = repositorio.crear_estudiante(
        codigo=cuerpo["codigo"],
        nombres=cuerpo["nombres"],
        apellidos=cuerpo["apellidos"],
        correo=cuerpo.get("correo"),
        programa=cuerpo.get("programa"),
        consentimiento_firmado=bool(cuerpo.get("consentimiento_firmado", False)),
    )
    return jsonify({"id": estudiante_id}), 201


@bp.post("/<int:estudiante_id>/enrolar")
@requiere_rol("administrador")
def enrolar(estudiante_id: int):
    """Captura la codificacion facial del estudiante.

    Exige el consentimiento informado firmado antes de procesar cualquier
    imagen, que es la condicion que impone la Ley 1581 de 2012 sobre datos
    biometricos. Ademas guarda solo el vector resultante, nunca las fotos.
    """
    estudiante = repositorio.obtener_estudiante(estudiante_id)
    if estudiante is None:
        return jsonify({"error": "el estudiante no existe"}), 404
    if not estudiante["consentimiento_firmado"]:
        return jsonify({"error": "el estudiante no ha firmado el consentimiento"}), 403

    cuerpo = request.get_json(silent=True) or {}
    imagenes = cuerpo.get("imagenes") or []
    if not imagenes:
        return jsonify({"error": "se requiere al menos una imagen"}), 400

    codificaciones = []
    errores = []
    for indice, imagen_b64 in enumerate(imagenes):
        try:
            codificaciones.append(codificar_rostro(_decodificar(imagen_b64)))
        except RostroNoDetectado:
            errores.append({"imagen": indice, "motivo": "sin_rostro"})
        except VariosRostros:
            errores.append({"imagen": indice, "motivo": "varios_rostros"})
        except Exception:
            errores.append({"imagen": indice, "motivo": "imagen_invalida"})

    if not codificaciones:
        return jsonify({"error": "ninguna imagen sirvio", "detalle": errores}), 422

    vector = promediar_codificaciones(codificaciones)
    codificacion_id = repositorio.guardar_codificacion(estudiante_id, vector)

    return jsonify(
        {
            "codificacion_id": codificacion_id,
            "imagenes_procesadas": len(codificaciones),
            "imagenes_descartadas": errores,
        }
    ), 201
