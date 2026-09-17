"""Crea un usuario del panel con su contrasena hasheada.

Uso:
    python scripts/crear_usuario.py "Nombre Apellido" correo@umb.edu.co guardia

La contrasena se pide por consola y no queda en el historial de comandos ni
se almacena en claro en ningun momento.
"""

from __future__ import annotations

import getpass
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.db import consultar, inicializar_pool  # noqa: E402
from app.seguridad import hashear  # noqa: E402

ROLES = ("administrador", "guardia", "consulta")


def main() -> int:
    if len(sys.argv) != 4:
        print(__doc__)
        return 1

    nombre, correo, rol = sys.argv[1], sys.argv[2], sys.argv[3]
    if rol not in ROLES:
        print(f"El rol debe ser uno de: {', '.join(ROLES)}")
        return 1

    contrasena = getpass.getpass("Contrasena: ")
    if len(contrasena) < 8:
        print("La contrasena debe tener al menos 8 caracteres")
        return 1
    if contrasena != getpass.getpass("Confirme la contrasena: "):
        print("Las contrasenas no coinciden")
        return 1

    inicializar_pool()
    filas = consultar(
        """
        INSERT INTO usuario (nombre, correo, contrasena_hash, rol_id)
        VALUES (%s, %s, %s, (SELECT id FROM rol WHERE nombre = %s))
        RETURNING id
        """,
        (nombre, correo, hashear(contrasena), rol),
    )
    print(f"Usuario creado con id {filas[0]['id']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
