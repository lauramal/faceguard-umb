"""Endpoints del control de acceso (CU-02, CU-05, CU-10, CU-11)."""

from __future__ import annotations

from datetime import datetime

import numpy as np
from flask import Blueprint, g, jsonify, request

from .. import repositorio
from ..seguridad import requiere_rol
from ..servicios.control_acceso import (
    procesar_codificacion, procesar_fotograma, registrar_con_credencial,
)
from .personas import decodificar_imagen

bp = Blueprint("accesos", __name__, url_prefix="/api/accesos")


@bp.post("/evento")
def registrar_evento():
    """Via principal: la estacion envia la codificacion ya calculada.

    El servidor nunca ve la imagen del rostro ni necesita dlib, solo numpy
    para comparar los 128 numeros contra el catalogo (RNF-11).
    """
    cuerpo = request.get_json(silent=True) or {}
    codificacion = cuerpo.get("codificacion")
    punto_acceso_id = cuerpo.get("punto_acceso_id")

    if not punto_acceso_id:
        return jsonify({"error": "falta el campo punto_acceso_id"}), 400
    if not isinstance(codificacion, list) or len(codificacion) != 128:
        return jsonify({"error": "codificacion debe ser una lista de 128 numeros"}), 400

    try:
        vector = np.asarray(codificacion, dtype=np.float64)
    except (TypeError, ValueError):
        return jsonify({"error": "la codificacion contiene valores no numericos"}), 400

    resultado = procesar_codificacion(
        vector,
        int(punto_acceso_id),
        camara_id=cuerpo.get("camara_id"),
        imagen_url=cuerpo.get("imagen_url"),
    )
    return jsonify(resultado.a_dict()), 200


@bp.post("/identificar")
def identificar_y_registrar():
    """Via auxiliar: recibe el fotograma y hace todo en el servidor.

    Solo sirve en el montaje de demostracion donde la estacion y el backend
    corren en el mismo equipo, porque requiere dlib. En el servidor
    desplegado se usa /api/accesos/evento.
    """
    cuerpo = request.get_json(silent=True) or {}
    imagen_b64 = cuerpo.get("imagen")
    punto_acceso_id = cuerpo.get("punto_acceso_id")

    if not imagen_b64:
        return jsonify({"error": "falta el campo imagen"}), 400
    if not punto_acceso_id:
        return jsonify({"error": "falta el campo punto_acceso_id"}), 400

    try:
        imagen = decodificar_imagen(imagen_b64)
    except Exception:
        return jsonify({"error": "la imagen no pudo decodificarse"}), 400

    resultado = procesar_fotograma(
        imagen,
        int(punto_acceso_id),
        camara_id=cuerpo.get("camara_id"),
        imagen_url=cuerpo.get("imagen_url"),
    )
    return jsonify(resultado.a_dict()), 200


@bp.post("/credencial")
@requiere_rol("administrador", "guardia")
def ingreso_con_credencial():
    """Ingreso de quien no autorizo el tratamiento biometrico (RF-13)."""
    cuerpo = request.get_json(silent=True) or {}
    if not cuerpo.get("persona_id") or not cuerpo.get("punto_acceso_id"):
        return jsonify({"error": "persona_id y punto_acceso_id son obligatorios"}), 400

    resultado = registrar_con_credencial(
        int(cuerpo["persona_id"]), int(cuerpo["punto_acceso_id"])
    )
    if not resultado.identificado:
        return jsonify(resultado.a_dict()), 404

    repositorio.registrar_auditoria(
        g.usuario["id"], "ingreso_credencial", "registro_acceso",
        resultado.registro_id,
    )
    return jsonify(resultado.a_dict()), 201


@bp.post("/<int:registro_id>/verificar")
@requiere_rol("administrador", "guardia")
def verificar(registro_id: int):
    """El guardia resuelve un evento no identificado (RF-12, CU-10)."""
    cuerpo = request.get_json(silent=True) or {}
    aprobado = bool(cuerpo.get("aprobado", True))
    persona_id = cuerpo.get("persona_id")

    filas = repositorio.verificar_acceso_manual(
        registro_id, g.usuario["id"],
        int(persona_id) if persona_id else None, aprobado,
    )
    if not filas:
        return jsonify({"error": "el registro no existe o ya fue verificado"}), 404

    repositorio.registrar_auditoria(
        g.usuario["id"], "verificar_acceso", "registro_acceso", registro_id,
        "aprobado" if aprobado else "rechazado",
    )
    return jsonify({
        "registro_id": registro_id,
        "resultado": "verificado_manual" if aprobado else "rechazado",
    })


@bp.get("")
@requiere_rol("administrador", "guardia", "consulta")
def historial():
    """Historial de accesos con filtros por fecha, persona y punto (RF-09)."""

    def fecha(nombre: str):
        valor = request.args.get(nombre)
        if not valor:
            return None
        try:
            return datetime.fromisoformat(valor)
        except ValueError:
            return None

    def entero(nombre: str):
        return int(request.args[nombre]) if request.args.get(nombre) else None

    registros = repositorio.listar_accesos(
        desde=fecha("desde"),
        hasta=fecha("hasta"),
        persona_id=entero("persona_id"),
        punto_acceso_id=entero("punto_acceso_id"),
        resultado=request.args.get("resultado"),
        limite=min(int(request.args.get("limite", 200)), 1000),
    )
    repositorio.registrar_auditoria(
        g.usuario["id"], "consulta_historial", "registro_acceso", None,
        request.query_string.decode() or "sin filtros",
    )
    return jsonify({"total": len(registros), "registros": registros})
