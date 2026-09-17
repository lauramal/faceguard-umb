"""Punto de entrada de FaceGuard UMB.

    python run.py
"""

from app import crear_app
from app.config import Config
from app.db import inicializar_pool

app = crear_app()

if __name__ == "__main__":
    if Config.DATABASE_URL:
        inicializar_pool()
    app.run(host="0.0.0.0", port=5000, debug=Config.DEBUG)
