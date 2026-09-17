"""Endpoints del control de acceso (CU-02 y CU-05)."""

from __future__ import annotations

import base64
import io
from datetime import datetime

import numpy as np
from flask import Blueprint, jsonify, request

from .. import repositorio
from ..seguridad import requiere_rol
from ..servicios.control_acceso import procesar_fotograma

bp = Blueprint("accesos", __name__, url_prefix="/api/accesos")


def _decodificar_imagen(datos_base64: str) -> np.ndarray:
    """Convierte la imagen que envia la estacion de captura en un arreglo RGB."""
    from PIL import Image

    if "," in datos_base64:  # data:image/jpeg;base64,....
        datos_base64 = datos_base64.split(",", 1)[1]

    binario = base64.b64decode(datos_base64)
    imagen = Image.open(io.BytesIO(binario)).convert("RGB")
    return np.asarray(imagen)


@bp.post("/identificar")
def identificar_y_registrar():
    """Recibe un fotograma del punto de acceso y registra el evento.

    Este es el endpoint que consume la estacion de captura. Responde siempre,
    incluso cuando no logra identificar a nadie, para que el panel del guardia
    pueda mostrar el intento fallido.
    """
    cuerpo = request.get_json(silent=True) or {}

    imagen_b64 = cuerpo.get("imagen")
    punto_acceso_id = cuerpo.get("punto_acceso_id")

    if not imagen_b64:
        return jsonify({"error": "falta el campo imagen"}), 400
    if not punto_acceso_id:
        return jsonify({"error": "falta el campo punto_acceso_id"}), 400

    try:
        imagen = _decodificar_imagen(imagen_b64)
    except Exception:
        return jsonify({"error": "la imagen no pudo decodificarse"}), 400

    resultado = procesar_fotograma(imagen, int(punto_acceso_id))
    return jsonify(resultado.a_dict()), 200


@bp.get("")
@requiere_rol("administrador", "guardia", "consulta")
def historial():
    """Historial de accesos con filtros por fecha, estudiante y punto (RF-09)."""

    def fecha(nombre: str):
        valor = request.args.get(nombre)
        if not valor:
            return None
        try:
            return datetime.fromisoformat(valor)
        except ValueError:
            return None

    entero = lambda n: int(request.args[n]) if request.args.get(n) else None

    registros = repositorio.listar_accesos(
        desde=fecha("desde"),
        hasta=fecha("hasta"),
        estudiante_id=entero("estudiante_id"),
        punto_acceso_id=entero("punto_acceso_id"),
        limite=min(int(request.args.get("limite", 200)), 1000),
    )
    return jsonify({"total": len(registros), "registros": registros})
