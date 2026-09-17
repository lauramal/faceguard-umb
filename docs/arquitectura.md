# Decisiones de arquitectura

Este documento recoge el porqué de las decisiones técnicas del sistema, como
complemento a la documentación formal del capítulo III del trabajo de grado.

## Por qué face_recognition y no un servicio en la nube

La Tabla 1 del marco teórico compara las alternativas disponibles en Python.
Un servicio en la nube implicaría enviar imágenes de estudiantes a un tercero,
lo que contradice el compromiso de minimización que el proyecto asume frente a
la Ley 1581 de 2012. face_recognition corre localmente sobre dlib y devuelve
una codificación de 128 dimensiones que reemplaza a la imagen.

## Por qué la comparación vive separada de la codificación

`codificar_rostro` necesita dlib. `identificar` solo necesita numpy. Mantener
esas dos operaciones en funciones distintas permite tres cosas:

1. Probar la lógica de identificación sin cámara ni GPU
2. Sustituir el motor de codificación sin tocar la lógica de decisión
3. Medir el tiempo de cada etapa por separado para verificar el RNF-01

## Por qué el umbral de confianza rechaza en lugar de aproximar

Con una confianza por debajo de 0.85 el sistema devuelve `no identificado` y
no escribe ningún registro. La alternativa, asignar la identidad más cercana,
produciría registros falsos que son peores que la ausencia de registro, porque
contaminan la auditoría. El evento dudoso se muestra al guardia, que es quien
verifica. Esa es la forma concreta en que el sistema apoya el rol humano en
lugar de sustituirlo.

## Por qué la alternancia ingreso/salida se calcula y no se configura

El tipo de evento se deduce del último registro del estudiante. No hay
cámaras separadas de entrada y salida, ni el estudiante debe indicar nada.
Es la regla que describe el diagrama de estados de la clase RegistroAcceso.

## Por qué el repositorio se inyecta en el servicio

`procesar_fotograma` recibe el repositorio como parámetro opcional. En
producción usa el real; en las pruebas recibe uno en memoria. Sin esa
inyección, probar la lógica de decisión exigiría una base de datos levantada.

## Pendientes del sprint 3

- Entrenar el modelo YOLOv8 con el dataset de armas y publicar los pesos
- Conectar `DetectorArmas` al flujo de la estación de captura
- Notificación en tiempo real de alertas al panel del guardia
- Exportación de reportes (RF-10)
