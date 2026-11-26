# Resultados del entrenamiento de YOLOv8n

Primera versión del modelo de detección de armas visibles, entrenada en Google
Colab con `scripts/entrenar_yolo.ipynb`. Los pesos están en
`modelos/yolov8n-armas.pt`.

## Configuración

| Parámetro | Valor |
|---|---|
| Modelo base | yolov8n (preentrenado en COCO) |
| Dataset | Roboflow Universe, `bartin/guvenlik-sistemi-xsiyk`, versión 5 (CC BY 4.0) |
| Clases | billete, knife, monedero, person, pistol, smartphone, tarjeta |
| Partición | 70 / 20 / 10 por foto original, semilla 42 |
| Imágenes | 8.201 entrenamiento, 2.348 validación, 1.167 prueba (6.060 fotos originales) |
| Épocas | 60 de 60 (patience 15 no se activó) |
| Tamaño de imagen | 640 |
| GPU | Tesla T4 |

La partición se hizo por foto original y no al azar: Roboflow genera copias
aumentadas de cada foto, y repartirlas entre entrenamiento y prueba inflaría
las métricas.

## Métricas sobre el conjunto de prueba

| Clase | Precisión | Exhaustividad | F1 | mAP50 | mAP50-95 |
|---|---|---|---|---|---|
| knife (arma blanca) | 0.948 | 0.954 | 0.951 | 0.977 | 0.659 |
| pistol (arma de fuego) | 0.908 | 0.876 | 0.891 | 0.931 | 0.746 |

mAP50 global de las siete clases: 0.924.

## Lectura

- Sobre este conjunto, el arma blanca no resultó más difícil de detectar que
  la de fuego. Sí tuvo menor exactitud de localización (mAP50-95 de 0.659
  frente a 0.746), coherente con un objeto delgado y alargado.
- El conjunto de prueba proviene de la misma fuente que el de entrenamiento,
  de modo que estas cifras son una cota superior. El desempeño en un punto de
  acceso real se mide con el protocolo A de `docs/pruebas_caja_negra.md`.
- Las clases smartphone, billete, monedero y tarjeta no generan alerta
  (`traducir_etiqueta` las descarta), pero ayudan al modelo a no confundir un
  celular con una pistola.
