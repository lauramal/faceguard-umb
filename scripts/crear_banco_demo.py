"""Crea el banco de escenas que usa el modo demostracion.

Pasa el modelo YOLOv8 entrenado por las fotos del conjunto de PRUEBA (las que
el modelo no vio al entrenar) y guarda, para cada foto elegida, lo que el
modelo detecto: clase, confianza y caja. La demostracion reproduce despues
esas detecciones reales sin necesidad de instalar PyTorch.

Uso (en Colab o en un equipo con Ultralytics):

    python scripts/crear_banco_demo.py --imagenes RUTA/test/images

Resultado: la carpeta datos_demo/ con imagenes/, detecciones.json y
ATRIBUCION.md. Si se sube al repositorio, la demostracion funciona con fotos
reales en cualquier equipo.

Las fotos provienen del conjunto Guvenlik Sistemi (bartin, Roboflow Universe,
licencia CC BY 4.0), que permite redistribuirlas citando la fuente.
"""

from __future__ import annotations

import argparse
import json
import random
import shutil
import sys
from datetime import date
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RAIZ))

CLASES_ARMA = {"pistol", "knife", "gun", "handgun", "rifle", "firearm", "blade", "machete"}

ATRIBUCION = """# Origen de las fotos

Las imagenes de esta carpeta son una muestra del conjunto de PRUEBA de:

bartin. (s. f.). *Guvenlik Sistemi* (version 5) [Conjunto de datos].
Roboflow Universe. https://universe.roboflow.com/bartin/guvenlik-sistemi-xsiyk

Licencia CC BY 4.0. Se usan sin modificaciones salvo el cambio de tamano.

`detecciones.json` contiene lo que el modelo `modelos/yolov8n-armas.pt`
detecto en cada foto (umbral de exportacion {umbral}). El modo demostracion
aplica despues el umbral del sistema (UMBRAL_ARMA, 0.70 por defecto).

Generado el {fecha} con scripts/crear_banco_demo.py.
"""


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--imagenes", required=True, help="carpeta test/images del dataset")
    parser.add_argument("--modelo", default=str(RAIZ / "modelos" / "yolov8n-armas.pt"))
    parser.add_argument("--salida", default=str(RAIZ / "datos_demo"))
    parser.add_argument("--con-arma", type=int, default=60)
    parser.add_argument("--sin-arma", type=int, default=20)
    parser.add_argument("--lado-maximo", type=int, default=960)
    parser.add_argument("--umbral-exportacion", type=float, default=0.25)
    args = parser.parse_args()

    from PIL import Image
    from ultralytics import YOLO

    random.seed(42)
    modelo = YOLO(args.modelo)
    fotos = sorted(p for p in Path(args.imagenes).glob("*")
                   if p.suffix.lower() in (".jpg", ".jpeg", ".png"))
    if not fotos:
        print("No hay fotos en", args.imagenes)
        return 1

    con_arma, sin_arma = [], []
    for i, ruta in enumerate(fotos, 1):
        r = modelo.predict(str(ruta), conf=args.umbral_exportacion, verbose=False)[0]
        detecciones = [{"clase": r.names[int(c.cls)],
                        "confianza": round(float(c.conf), 3),
                        "caja": [float(v) for v in c.xyxy[0]]} for c in r.boxes]
        hay_arma = any(d["clase"] in CLASES_ARMA and d["confianza"] >= 0.70 for d in detecciones)
        (con_arma if hay_arma else sin_arma).append((ruta, detecciones))
        if i % 100 == 0:
            print(f"  {i}/{len(fotos)} fotos analizadas")

    elegidas = (random.sample(con_arma, min(args.con_arma, len(con_arma)))
                + random.sample(sin_arma, min(args.sin_arma, len(sin_arma))))

    salida = Path(args.salida)
    if (salida / "imagenes").exists():
        shutil.rmtree(salida / "imagenes")
    (salida / "imagenes").mkdir(parents=True)

    indice = {}
    for n, (ruta, detecciones) in enumerate(elegidas, 1):
        imagen = Image.open(ruta).convert("RGB")
        escala = min(1.0, args.lado_maximo / max(imagen.size))
        if escala < 1:
            imagen = imagen.resize((round(imagen.width * escala), round(imagen.height * escala)))
        nombre = f"escena_{n:03d}.jpg"
        imagen.save(salida / "imagenes" / nombre, quality=85)
        indice[nombre] = [{**d, "caja": [round(v * escala, 1) for v in d["caja"]]}
                          for d in detecciones]

    (salida / "detecciones.json").write_text(json.dumps({
        "modelo": Path(args.modelo).name,
        "umbral_exportacion": args.umbral_exportacion,
        "imagenes": indice,
    }, indent=1, ensure_ascii=False), encoding="utf-8")
    (salida / "ATRIBUCION.md").write_text(
        ATRIBUCION.format(umbral=args.umbral_exportacion, fecha=date.today().isoformat()),
        encoding="utf-8")

    print(f"\nBanco creado en {salida}: {len(con_arma)} fotos con arma y "
          f"{len(sin_arma)} sin arma en el conjunto de prueba; se guardaron "
          f"{min(args.con_arma, len(con_arma))} y {min(args.sin_arma, len(sin_arma))}.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
