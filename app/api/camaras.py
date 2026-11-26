"""Gestion de puntos de acceso y camaras (RF-16, CU-08)."""

from __future__ import annotations

from flask import Blueprint, g, jsonify, request

from .. import repositorio
from ..config import Config
from .. import seguridad
from ..seguridad import requiere_rol

bp = Blueprint("camaras", __name__, url_prefix="/api")


@bp.get("/puntos-acceso")
@requiere_rol("administrador", "guardia", "consulta")
def listar_puntos():
    return jsonify({"puntos_acceso": repositorio.listar_puntos_acceso()})


@bp.post("/puntos-acceso")
@requiere_rol("administrador")
def crear_punto():
    cuerpo = request.get_json(silent=True) or {}
    if not cuerpo.get("institucion_id") or not cuerpo.get("nombre"):
        return jsonify({"error": "institucion_id y nombre son obligatorios"}), 400
    try:
        punto_id = repositorio.crear_punto_acceso(
            int(cuerpo["institucion_id"]), cuerpo["nombre"], cuerpo.get("ubicacion"),
            cuerpo.get("sentido", "mixto"),
        )
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400
    repositorio.registrar_auditoria(
        g.usuario["id"], "crear_punto_acceso", "punto_acceso", punto_id
    )
    return jsonify({"id": punto_id}), 201


@bp.get("/camaras")
@requiere_rol("administrador", "guardia", "consulta")
def listar_camaras():
    punto = request.args.get("punto_acceso_id")
    camaras = repositorio.listar_camaras(int(punto) if punto else None)
    # Se marca cual camara queda por debajo del minimo del RNF-14, para que
    # el administrador sepa donde el desempeno declarado no es exigible.
    for c in camaras:
        c["cumple_rnf14"] = bool(
            (c.get("resolucion_ancho") or 0) >= Config.RESOLUCION_MINIMA_ANCHO
            and (c.get("resolucion_alto") or 0) >= Config.RESOLUCION_MINIMA_ALTO
        )
    return jsonify({"camaras": camaras})


@bp.post("/camaras")
@requiere_rol("administrador")
def crear_camara():
    cuerpo = request.get_json(silent=True) or {}
    if not cuerpo.get("punto_acceso_id") or not cuerpo.get("identificador"):
        return jsonify({"error": "punto_acceso_id e identificador son obligatorios"}), 400
    camara_id = repositorio.crear_camara(
        punto_acceso_id=int(cuerpo["punto_acceso_id"]),
        identificador=cuerpo["identificador"],
        tipo=cuerpo.get("tipo"),
        resolucion_ancho=cuerpo.get("resolucion_ancho"),
        resolucion_alto=cuerpo.get("resolucion_alto"),
        lux_minimo=cuerpo.get("lux_minimo"),
    )
    repositorio.registrar_auditoria(
        g.usuario["id"], "crear_camara", "camara", camara_id
    )
    return jsonify({"id": camara_id}), 201


@bp.post("/camaras/<int:camara_id>/credencial")
@requiere_rol("administrador")
def emitir_credencial(camara_id: int):
    """Genera la credencial de la estacion de captura de esta camara.

    El token se muestra UNA sola vez; en la base queda solo su resumen.
    Emitir una credencial nueva invalida la anterior, que es lo que se hace
    si un equipo se pierde o se sospecha que la credencial se filtro.
    """
    if repositorio.obtener_camara(camara_id) is None:
        return jsonify({"error": "camara no encontrada"}), 404
    token, resumen = seguridad.generar_credencial_estacion(camara_id)
    repositorio.asignar_token_camara(camara_id, resumen)
    repositorio.registrar_auditoria(
        g.usuario["id"], "emitir_credencial_estacion", "camara", camara_id
    )
    return jsonify({
        "camara_id": camara_id,
        "token": token,
        "aviso": "Guarde este token en la estacion (FACEGUARD_TOKEN). No se volvera a mostrar.",
    }), 201
