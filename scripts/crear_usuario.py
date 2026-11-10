"""Crea un usuario del sistema con su rol (CU-07).

Uso:
    python scripts/crear_usuario.py --nombre "Ana Ruiz" \
        --correo ana@institucion.edu --rol administrador
"""

from __future__ import annotations

import argparse
import getpass
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app import repositorio          # noqa: E402
from app.db import consultar, inicializar_pool   # noqa: E402
from app.seguridad import hashear    # noqa: E402


def argumentos():
    parser = argparse.ArgumentParser(description="Alta de usuario del sistema")
    parser.add_argument("--nombre", required=True)
    parser.add_argument("--correo", required=True)
    parser.add_argument("--rol", required=True,
                        choices=("administrador", "guardia", "consulta"))
    return parser.parse_args()


def main() -> int:
    args = argumentos()
    inicializar_pool()

    if repositorio.obtener_usuario_por_correo(args.correo):
        print(f"Ya existe un usuario con el correo {args.correo}")
        return 1

    filas = consultar("SELECT id FROM rol WHERE nombre = %s", (args.rol,))
    if not filas:
        print(f"El rol {args.rol} no existe en la base de datos")
        return 1

    contrasena = getpass.getpass("Contrasena: ")
    if contrasena != getpass.getpass("Confirme la contrasena: "):
        print("Las contrasenas no coinciden")
        return 1
    if len(contrasena) < 8:
        print("La contrasena debe tener al menos 8 caracteres")
        return 1

    usuario_id = repositorio.crear_usuario(
        nombre=args.nombre, correo=args.correo,
        contrasena_hash=hashear(contrasena), rol_id=filas[0]["id"],
    )
    print(f"Usuario {usuario_id} creado con rol {args.rol}.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
