"""Almacenamiento del fotograma de cada alerta (evidencia del incidente).

El guardia necesita ver la imagen para decidir si lo detectado es un arma
visible o un falso positivo. La imagen contiene personas, de modo que se trata
como dato sensible:

* se guarda en un bucket PRIVADO de Supabase Storage o, si no esta
  configurado, en una carpeta local del servidor;
* nunca se publica una URL directa: se sirve a traves del servidor, que exige
  sesion con rol de guardia o administrador y deja constancia en la bitacora;
* se depura segun institucion.retencion_dias.

La ruta que se guarda en alerta_arma.imagen_url indica el medio:
"local:alertas/12.jpg" o "supabase:alertas/12.jpg".
"""

from __future__ import annotations

import io
import urllib.request
from pathlib import Path

from ..config import Config

FORMATOS = {"JPEG": "image/jpeg", "PNG": "image/png"}


class EvidenciaInvalida(ValueError):
    """Lo recibido no es una imagen JPEG o PNG legible."""


def _validar(datos: bytes) -> str:
    from PIL import Image

    try:
        with Image.open(io.BytesIO(datos)) as imagen:
            formato = imagen.format
            imagen.verify()
    except Exception as exc:
        raise EvidenciaInvalida("la evidencia no es una imagen valida") from exc
    if formato not in FORMATOS:
        raise EvidenciaInvalida(f"formato no admitido: {formato}")
    return "jpg" if formato == "JPEG" else "png"


def _usa_supabase() -> bool:
    return bool(Config.SUPABASE_URL and Config.SUPABASE_SERVICE_KEY)


def _url_objeto(nombre: str) -> str:
    return f"{Config.SUPABASE_URL}/storage/v1/object/{Config.SUPABASE_BUCKET}/{nombre}"


def guardar(alerta_id: int, datos: bytes) -> str:
    """Guarda la imagen y devuelve la ruta que se anota en la alerta."""
    extension = _validar(datos)
    nombre = f"alertas/{int(alerta_id)}.{extension}"

    if _usa_supabase():
        peticion = urllib.request.Request(
            _url_objeto(nombre), data=datos, method="POST",
            headers={
                "Authorization": f"Bearer {Config.SUPABASE_SERVICE_KEY}",
                "Content-Type": FORMATOS["JPEG" if extension == "jpg" else "PNG"],
                "x-upsert": "true",
            },
        )
        with urllib.request.urlopen(peticion, timeout=15):
            pass
        return f"supabase:{nombre}"

    destino = Path(Config.EVIDENCIAS_DIR) / nombre
    destino.parent.mkdir(parents=True, exist_ok=True)
    destino.write_bytes(datos)
    return f"local:{nombre}"


def leer(ruta: str) -> tuple[bytes, str]:
    """Devuelve (bytes, tipo MIME) de una evidencia guardada."""
    medio, _, nombre = (ruta or "").partition(":")
    if not nombre or ".." in nombre or nombre.startswith("/"):
        raise FileNotFoundError(ruta)
    tipo = "image/png" if nombre.endswith(".png") else "image/jpeg"

    if medio == "supabase":
        peticion = urllib.request.Request(
            _url_objeto(nombre),
            headers={"Authorization": f"Bearer {Config.SUPABASE_SERVICE_KEY}"},
        )
        with urllib.request.urlopen(peticion, timeout=15) as respuesta:
            return respuesta.read(), tipo
    if medio == "local":
        return (Path(Config.EVIDENCIAS_DIR) / nombre).read_bytes(), tipo
    raise FileNotFoundError(ruta)
