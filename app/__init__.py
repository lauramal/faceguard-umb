"""Fabrica de la aplicacion Flask de FaceGuard."""

from __future__ import annotations

import logging
from urllib.parse import urlparse

from flask import Flask, jsonify, request

from .config import Config

__version__ = "0.4.0"

CLAVE_POR_DEFECTO = "cambiar-en-produccion"
METODOS_QUE_MODIFICAN = ("POST", "PUT", "PATCH", "DELETE")


def crear_app(config: type[Config] = Config) -> Flask:
    app = Flask(__name__)
    app.config.from_object(config)
    app.secret_key = config.SECRET_KEY

    from . import seguridad

    app.permanent_session_lifetime = seguridad.duracion_sesion()

    logging.basicConfig(
        level=logging.DEBUG if config.DEBUG else logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    log = logging.getLogger(__name__)

    if config.SECRET_KEY == CLAVE_POR_DEFECTO:
        if config.APP_ENV == "produccion":
            raise RuntimeError(
                "SECRET_KEY no esta configurada. En produccion la aplicacion no "
                "arranca con la clave por defecto, porque con ella cualquiera "
                "podria fabricar una sesion valida."
            )
        log.warning("SECRET_KEY por defecto: valida solo para desarrollo")

    from .api.accesos import bp as bp_accesos
    from .api.alertas import bp as bp_alertas
    from .api.auth import bp as bp_auth
    from .api.camaras import bp as bp_camaras
    from .api.personas import bp as bp_personas
    from .api.reportes import bp as bp_reportes
    from .api.usuarios import bp as bp_usuarios
    from .web import bp as bp_web

    for bp in (bp_web, bp_auth, bp_personas, bp_accesos, bp_alertas,
               bp_camaras, bp_usuarios, bp_reportes):
        app.register_blueprint(bp)

    @app.before_request
    def mismo_origen():
        """Rechaza operaciones de escritura que llegan desde otro sitio.

        Complementa la cookie SameSite=Strict: si el navegador declara un
        origen y no es este servidor, la peticion no se procesa.
        """
        if request.method not in METODOS_QUE_MODIFICAN:
            return None
        origen = request.headers.get("Origin")
        if origen and urlparse(origen).netloc != request.host:
            return jsonify({"error": "origen no permitido"}), 403
        return None

    @app.after_request
    def cabeceras_de_seguridad(respuesta):
        respuesta.headers.setdefault("X-Content-Type-Options", "nosniff")
        respuesta.headers.setdefault("X-Frame-Options", "DENY")
        respuesta.headers.setdefault("Referrer-Policy", "same-origin")
        return respuesta

    @app.context_processor
    def variables_de_plantilla():
        return {"csrf_token": seguridad.token_csrf}

    @app.get("/salud")
    def salud():
        return jsonify({
            "estado": "ok", "version": __version__, "entorno": config.APP_ENV,
        })

    @app.errorhandler(404)
    def no_encontrado(_):
        return jsonify({"error": "recurso no encontrado"}), 404

    @app.errorhandler(413)
    def demasiado_grande(_):
        return jsonify({"error": "la peticion supera el tamano permitido"}), 413

    @app.errorhandler(500)
    def error_interno(_):
        return jsonify({"error": "error interno del servidor"}), 500

    if config.ESCALAMIENTO_AUTOMATICO and not getattr(config, "TESTING", False):
        from .servicios.tareas import iniciar_escalamiento_automatico

        iniciar_escalamiento_automatico(app, config.SEGUNDOS_REVISION_ESCALAMIENTO)

    return app
