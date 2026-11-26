"""Genera la credencial de la estacion de captura de una camara.

Alternativa por consola al endpoint POST /api/camaras/<id>/credencial, util
la primera vez, cuando todavia no hay un administrador con sesion.

    python scripts/emitir_credencial.py 1

Imprime el token una sola vez. En la base queda solo su resumen SHA-256.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app import repositorio, seguridad   # noqa: E402


def main() -> int:
    if len(sys.argv) != 2 or not sys.argv[1].isdigit():
        print(__doc__)
        return 2
    camara_id = int(sys.argv[1])
    if repositorio.obtener_camara(camara_id) is None:
        print(f"No existe la camara {camara_id}")
        return 1
    token, resumen = seguridad.generar_credencial_estacion(camara_id)
    repositorio.asignar_token_camara(camara_id, resumen)
    repositorio.registrar_auditoria(None, "emitir_credencial_estacion", "camara", camara_id,
                                    "emitida por consola")
    print("Credencial de la estacion (guardela como FACEGUARD_TOKEN):")
    print(token)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
