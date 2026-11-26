# Decisiones de arquitectura

Este documento recoge el porqué de las decisiones técnicas del sistema, como
complemento a la documentación formal del capítulo III del trabajo de grado.

## Dónde corre cada cosa

| Equipo | Qué corre | Por qué |
|---|---|---|
| Estación de captura (punto de acceso) | OpenCV, face_recognition (dlib), YOLOv8 | Son las librerías pesadas. Las imágenes de los rostros no salen del equipo |
| Servidor de aplicación (Flask) | API, panel del guardia, comparación de vectores, escalamiento | Solo necesita numpy y psycopg2: cabe en 512 MB (RNF-11) |
| Supabase | PostgreSQL y almacenamiento privado de evidencias | Base de datos gestionada |

La estación calcula la codificación facial y envía al servidor únicamente el
vector de 128 números. Si YOLOv8 detecta un arma, envía el aviso y el
fotograma de esa detección, que es la evidencia que el guardia revisa.

## Por qué face_recognition y no un servicio en la nube

Un servicio en la nube implicaría enviar imágenes de las personas a un
tercero, lo que contradice la minimización que el proyecto asume frente a la
Ley 1581 de 2012. face_recognition corre localmente sobre dlib y devuelve una
codificación de 128 dimensiones que reemplaza a la imagen.

## Por qué la identidad se decide por distancia

La decisión se toma sobre la distancia euclidiana entre codificaciones, con el
umbral de referencia de dlib (0.6). La confianza es una lectura normalizada que
se guarda para los reportes, no un criterio de corte. Un evento que no supera
el umbral no se asigna a la persona más cercana: se registra como no
identificado para que el guardia lo verifique. Asignar la identidad más
parecida produciría registros falsos, peores que la ausencia de registro.

## Por qué la persona del fotograma es contexto y no portadora

Que el sistema reconozca a alguien y detecte un arma en la misma imagen no
significa que esa persona la porte: puede estar al lado de quien la lleva. Por
eso la alerta guarda dos referencias distintas:

- `persona_contexto_id`: la persona identificada en el mismo evento de
  acceso. Se muestra al guardia como información, y solo si el fotograma tenía
  un único rostro.
- `portador_id`: la persona que el guardia confirma como portadora después de
  ver la evidencia. Una restricción de la base impide llenarla si la alerta no
  fue confirmada por un guardia.

## Por qué una misma arma no abre una alerta por fotograma

La estación analiza un fotograma por segundo. Si alguien se queda con un arma
frente a la cámara, sin control habría una alerta por segundo y el guardia
terminaría ignorándolas. La estación espera unos segundos entre avisos del
mismo tipo, y el servidor suma las detecciones repetidas a la alerta abierta
(columna `detecciones`) durante `VENTANA_ALERTA` segundos.

## Por qué las estaciones tienen credencial

Los endpoints que reciben eventos y alertas no pueden quedar abiertos: con
ellos cualquiera podría fabricar un ingreso o una falsa alarma. Cada cámara
tiene una credencial propia (`<camara_id>.<secreto>`). En la base se guarda
solo el resumen SHA-256 del secreto. El punto de acceso se toma de la cámara
autenticada, no de lo que la estación escriba en la petición.

## Por qué el rol se lee de la base en cada petición

La sesión guarda solo el identificador del usuario. Si el administrador
bloquea una cuenta o le cambia el rol, el cambio rige en la siguiente petición
y no cuando la persona cierre sesión.

## Por qué el escalamiento corre solo

Un hilo del servidor revisa cada minuto las alertas que llevan más de
`MINUTOS_ESCALAMIENTO` sin atención y las sube al administrador. Como el plan
gratuito suspende el servidor sin tráfico, el escalamiento también se revisa
cada vez que alguien abre el panel o consulta las alertas. La operación es
idempotente: una alerta escalada no vuelve a escalar.

## Por qué ingreso o salida depende del punto

Un punto de acceso declara su sentido: `entrada`, `salida` o `mixto`. En los
dos primeros el evento queda fijado por el punto. En un punto mixto se alterna
con el último evento de la persona, salvo que ese ingreso sea más viejo que
`HORAS_JORNADA_MAXIMA`: entonces la salida se perdió y el evento nuevo es un
ingreso. La comprobación de la ventana antirrebote y la inserción ocurren en
una transacción con un candado por persona, para que dos fotogramas
simultáneos no dupliquen el registro.

## Por qué el repositorio se inyecta en los servicios

Los servicios reciben el repositorio como parámetro opcional. En producción
usan el real; en las pruebas, uno en memoria que aplica las mismas reglas que
la base. Sin esa inyección, probar la lógica de decisión exigiría una base de
datos levantada.
