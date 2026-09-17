"""Fabrica de la aplicacion Flask de FaceGuard UMB."""

from __future__ import annotations

import logging

from flask import Flask, jsonify

from .config import Config

__version__ = "0.2.0"


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
    from .api.estudiantes import bp as bp_estudiantes
    from .web import bp as bp_web

    app.register_blueprint(bp_web)
    app.register_blueprint(bp_accesos)
    app.register_blueprint(bp_alertas)
    app.register_blueprint(bp_estudiantes)

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
