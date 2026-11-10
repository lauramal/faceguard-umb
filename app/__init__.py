"""Fabrica de la aplicacion Flask de FaceGuard."""

from __future__ import annotations

import logging

from flask import Flask, jsonify

from .config import Config

__version__ = "0.3.0"


def crear_app(config: type[Config] = Config) -> Flask:
    app = Flask(__name__)
    app.config.from_object(config)
    app.secret_key = config.SECRET_KEY

    logging.basicConfig(
        level=logging.DEBUG if config.DEBUG else logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )

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

    @app.get("/salud")
    def salud():
        return jsonify({"estado": "ok", "version": __version__})

    @app.errorhandler(404)
    def no_encontrado(_):
        return jsonify({"error": "recurso no encontrado"}), 404

    @app.errorhandler(500)
    def error_interno(_):
        return jsonify({"error": "error interno del servidor"}), 500

    return app
