"""Evaluacion del modelo de deteccion de armas (objetivo especifico 5).

Produce las cifras que van al Capitulo IV, separadas por tipo de arma, porque
el documento afirma que las armas blancas son mas dificiles de detectar que
las de fuego y esa afirmacion hay que sostenerla con numeros propios.

Mide tres cosas:

1. Precision, exhaustividad y F1 por clase sobre el conjunto de prueba.
2. Tiempo de inferencia en CPU, que es donde corre la estacion de captura
   (RNF-02).
3. Falsos positivos sobre una carpeta de objetos que NO son armas, que es el
   riesgo real del modulo: un guardia que recibe avisos equivocados termina
   por ignorarlos todos.

Uso:
    python scripts/evaluar_modelo.py --modelo modelos/yolov8n-armas.pt \
        --datos dataset/data.yaml --negativos pruebas/negativos/
"""

from __future__ import annotations

import argparse
import json
import statistics
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.config import Config                                   # noqa: E402
from app.servicios.deteccion_armas import traducir_etiqueta     # noqa: E402

EXTENSIONES = (".jpg", ".jpeg", ".png", ".bmp", ".webp")


def argumentos():
    parser = argparse.ArgumentParser(description="Evaluacion del modelo de armas")
    parser.add_argument("--modelo", default=Config.MODELO_YOLO)
    parser.add_argument("--datos", help="ruta al data.yaml del dataset")
    parser.add_argument("--negativos", help="carpeta con objetos que no son armas")
    parser.add_argument("--umbral", type=float, default=Config.UMBRAL_ARMA)
    parser.add_argument("--repeticiones", type=int, default=20)
    parser.add_argument("--salida", default="evaluacion_modelo.json")
    return parser.parse_args()


def cargar(ruta: str):
    try:
        from ultralytics import YOLO
    except ImportError:
        print("Ultralytics no esta instalado. Ejecute:")
        print("    pip install -r requirements-estacion.txt")
        raise SystemExit(1)

    if not Path(ruta).exists():
        print(f"No se encontro el modelo en {ruta}.")
        print("Entrene primero con scripts/entrenar_yolo.ipynb en Google Colab.")
        raise SystemExit(1)
    return YOLO(ruta)


def metricas_por_clase(modelo, data_yaml: str) -> dict:
    """Precision, exhaustividad y F1 de cada clase sobre el conjunto de prueba."""
    print("\n== Metricas por clase ==")
    resultado = modelo.val(data=data_yaml, split="test", verbose=False)

    filas = {}
    print(f"{'Clase':<22}{'Precision':>11}{'Exhaustiv.':>12}{'F1':>8}{'mAP50':>9}")
    print("-" * 62)
    for indice, clase in resultado.names.items():
        # class_result devuelve (precision, exhaustividad, AP50, AP50-95).
        # box.maps es AP50-95 por clase: no se debe rotular como mAP50.
        p, r, ap50, _ = resultado.box.class_result(indice)
        f1 = 2 * p * r / (p + r) if (p + r) else 0.0
        filas[clase] = {
            "tipo_en_el_sistema": traducir_etiqueta(clase),
            "precision": round(float(p), 4),
            "exhaustividad": round(float(r), 4),
            "f1": round(float(f1), 4),
            "map50": round(float(ap50), 4),
        }
        print(f"{clase:<22}{p:>11.3f}{r:>12.3f}{f1:>8.3f}{ap50:>9.3f}")

    print("-" * 62)
    print(f"{'Global (mAP50)':<22}{'':>11}{'':>12}{'':>8}{resultado.box.map50:>9.3f}")

    # El documento sostiene que las armas blancas son mas dificiles. Se verifica.
    blancas = [v["f1"] for k, v in filas.items()
               if v["tipo_en_el_sistema"] == "arma_blanca"]
    fuego = [v["f1"] for k, v in filas.items()
             if v["tipo_en_el_sistema"] == "arma_fuego"]
    if blancas and fuego:
        print(f"\nF1 medio en armas blancas: {statistics.mean(blancas):.3f}")
        print(f"F1 medio en armas de fuego: {statistics.mean(fuego):.3f}")
        if statistics.mean(blancas) < statistics.mean(fuego):
            print("Confirma lo que afirma el documento: el arma blanca es mas dificil.")
        else:
            print("ATENCION: aqui el arma blanca NO resulto mas dificil.")
            print("Ajuste esa afirmacion del documento o explique por que difiere.")

    return {
        "por_clase": filas,
        "map50_global": round(float(resultado.box.map50), 4),
    }


def tiempo_en_cpu(modelo, repeticiones: int) -> dict:
    """El RNF-02 se mide en CPU, que es donde corre la estacion de captura."""
    import numpy as np

    print("\n== Tiempo de inferencia en CPU ==")
    fotograma = np.random.randint(
        0, 255,
        (Config.RESOLUCION_MINIMA_ALTO, Config.RESOLUCION_MINIMA_ANCHO, 3),
        dtype=np.uint8,
    )
    modelo.predict(fotograma, device="cpu", verbose=False)   # descarta la primera

    tiempos = []
    for _ in range(repeticiones):
        inicio = time.perf_counter()
        modelo.predict(fotograma, device="cpu", verbose=False)
        tiempos.append((time.perf_counter() - inicio) * 1000)

    datos = {
        "mediana_ms": round(statistics.median(tiempos), 1),
        "maximo_ms": round(max(tiempos), 1),
        "minimo_ms": round(min(tiempos), 1),
        "limite_rnf02_ms": 2000,
        "cumple_rnf02": max(tiempos) < 2000,
    }
    print(f"Resolucion probada: {Config.RESOLUCION_MINIMA_ANCHO}"
          f"x{Config.RESOLUCION_MINIMA_ALTO}")
    print(f"Mediana: {datos['mediana_ms']} ms")
    print(f"Maximo:  {datos['maximo_ms']} ms")
    print(f"RNF-02 (menos de 2000 ms): "
          f"{'CUMPLE' if datos['cumple_rnf02'] else 'NO CUMPLE'}")
    return datos


def falsos_positivos(modelo, carpeta: str, umbral: float) -> dict:
    """Ningun objeto cotidiano debe generar una alerta."""
    print("\n== Falsos positivos sobre objetos que no son armas ==")
    ruta = Path(carpeta)
    imagenes = [p for p in sorted(ruta.rglob("*")) if p.suffix.lower() in EXTENSIONES]
    if not imagenes:
        print(f"No hay imagenes en {carpeta}")
        return {"evaluadas": 0}

    fallos = []
    for imagen in imagenes:
        salida = modelo.predict(str(imagen), conf=umbral, verbose=False)[0]
        detecciones = [
            (salida.names[int(c.cls)], round(float(c.conf), 3))
            for c in salida.boxes
            if traducir_etiqueta(salida.names[int(c.cls)]) is not None
        ]
        if detecciones:
            fallos.append({"imagen": imagen.name, "detecciones": detecciones})
            print(f"  FALSO POSITIVO  {imagen.name}: {detecciones}")
        else:
            print(f"  correcto        {imagen.name}")

    tasa = len(fallos) / len(imagenes)
    print(f"\nFalsos positivos: {len(fallos)} de {len(imagenes)} "
          f"({tasa:.1%}) con umbral {umbral}")
    if fallos:
        print("Suba UMBRAL_ARMA o anada estas imagenes como negativos y reentrene.")

    return {
        "evaluadas": len(imagenes),
        "falsos_positivos": len(fallos),
        "tasa": round(tasa, 4),
        "umbral": umbral,
        "detalle": fallos,
    }


def main() -> int:
    args = argumentos()
    modelo = cargar(args.modelo)

    informe = {
        "modelo": args.modelo,
        "umbral_confianza": args.umbral,
        "fecha": time.strftime("%Y-%m-%d %H:%M"),
    }

    if args.datos:
        informe["metricas"] = metricas_por_clase(modelo, args.datos)
    else:
        print("Sin --datos no se calculan las metricas por clase.")

    informe["rendimiento"] = tiempo_en_cpu(modelo, args.repeticiones)

    if args.negativos:
        informe["negativos"] = falsos_positivos(modelo, args.negativos, args.umbral)
    else:
        print("\nSin --negativos no se evaluan los falsos positivos.")

    Path(args.salida).write_text(
        json.dumps(informe, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    print(f"\nInforme guardado en {args.salida}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
