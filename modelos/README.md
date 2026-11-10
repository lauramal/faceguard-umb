# Pesos del modelo de detección de armas

Aquí va `yolov8n-armas.pt`, el modelo entrenado con
`scripts/entrenar_yolo.ipynb` en Google Colab.

El archivo pesa unos 6 MB, así que cabe en el repositorio sin problema. Si
llega a crecer por encima de los 100 MB (solo pasaría con `yolov8m` o mayor),
use Git LFS o publíquelo como *release* de GitHub.

## Cómo apuntar la estación al modelo

En el `.env` de la estación de captura:

```
MODELO_YOLO=modelos/yolov8n-armas.pt
UMBRAL_ARMA=0.70
```

## Clases que debe producir el modelo

`DetectorArmas` traduce las etiquetas del dataset al vocabulario de la base de
datos mediante el mapa `EQUIVALENCIAS` de `app/servicios/deteccion_armas.py`.
Ya reconoce las variantes más comunes:

| Etiqueta del dataset | Tipo en el sistema |
|---|---|
| pistol, gun, handgun, rifle, firearm | `arma_fuego` |
| knife, blade, machete | `arma_blanca` |

Si su dataset usa otros nombres, agréguelos a ese mapa. Cualquier clase que no
esté allí se descarta, que es justamente lo que evita que un celular o una
sombrilla generen una alerta.
