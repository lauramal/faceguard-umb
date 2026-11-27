# FaceGuard

Sistema web de seguridad para la identificación facial de las personas que
ingresan y la detección de armas visibles o empuñadas en los puntos de acceso
de una institución de educación superior.

Trabajo de grado de Ingeniería de Software (Universidad Manuela Beltrán),
aplicable a cualquier institución de educación superior. El aporte no está en el
reconocimiento facial, que ya existe y se consigue comercialmente, sino en
**integrar en un mismo punto quién entra, si lleva un arma a la vista, y dejar
ambos hechos unidos en un registro consultable**.

---

## Arquitectura

El sistema se reparte en dos equipos, y esa división no es casual.

| Dónde | Qué corre | Por qué |
|---|---|---|
| **Estación de captura** (equipo del punto de acceso) | OpenCV, `face_recognition` (dlib), YOLOv8 | Son las librerías pesadas. Además, así las imágenes de los rostros nunca salen del equipo local |
| **Servidor de aplicación** (plan gratuito) | Flask, numpy, psycopg2 | Solo compara vectores de 128 números y escribe en la base. Cabe en 512 MB de RAM |
| **Supabase** | PostgreSQL y almacenamiento | Base de datos y evidencias |

La estación calcula el *embedding* facial y envía al servidor únicamente ese
vector. Es lo que exige el RNF-11 y lo que refuerza la minimización de datos
frente a la Ley 1581 de 2012.

---

## Demostración rápida

Para ver el sistema funcionando sin cámara ni base de datos: `pip install -r requirements.txt` y `python scripts/demo.py`. Las pruebas corren solas en GitHub (pestaña **Actions**). Detalles en `docs/demostracion.md`.

---

## Instalación

### Servidor de aplicación

```bash
pip install -r requirements.txt
cp .env.example .env          # y complete DATABASE_URL, SECRET_KEY y APP_ENV
psql "$DATABASE_URL" -f db/schema.sql
python run.py
```

Si la base ya existía con la versión anterior del esquema, en lugar de
`schema.sql` aplique la migración:

```bash
psql "$DATABASE_URL" -f db/migraciones/003_correcciones_asesoria.sql
```

En producción (`APP_ENV=produccion`) la aplicación no arranca si `SECRET_KEY`
sigue con el valor por defecto.

### Estación de captura

Cada estación se autentica con la credencial de su cámara. El administrador
la genera una vez (por API con `POST /api/camaras/<id>/credencial`, o por
consola) y se guarda en la estación:

```bash
python scripts/emitir_credencial.py 1        # imprime el token una sola vez
pip install -r requirements-estacion.txt
export FACEGUARD_TOKEN=1.xxxxxxxxxxxx
python scripts/estacion_acceso.py --api https://su-servidor/
```

Sin credencial válida el servidor rechaza eventos y alertas.

> `requirements.txt` **no** incluye dlib ni Ultralytics a propósito. Instalarlos
> en el servidor agota la memoria del plan gratuito.

---

## Estructura

```
app/
  api/            endpoints REST (auth, personas, accesos, alertas, cámaras,
                  usuarios, reportes)
  servicios/      lógica de dominio
    reconocimiento_facial.py   codificación y comparación de rostros
    control_acceso.py          ingreso/salida, antirrebote, no identificados
    deteccion_armas.py         envoltorio de YOLOv8
    alertas.py                 máquina de estados, contexto y detecciones repetidas
    evidencias.py              fotograma de cada alerta (Supabase Storage o carpeta)
    tareas.py                  escalamiento automático en segundo plano
  repositorio.py  única capa que escribe SQL
  seguridad.py    sesiones, roles, bloqueo de cuentas, credenciales de estación
  web.py          panel del guardia y consulta de registros
  db.py           pool de conexiones
db/schema.sql     esquema completo con sus restricciones
db/migraciones/   cambios para bases que ya existían
scripts/          enrolamiento, alta de usuarios, estación de captura
tests/            suite de pruebas
```

---

## Pruebas

```bash
pytest                        # unitarias, con cobertura
TEST_DATABASE_URL=postgresql://usuario:clave@localhost/faceguard_test pytest
```

La suite tiene **337 pruebas** y **93 % de cobertura**: 286 corren sin base de
datos y 51 ejecutan el esquema real sobre PostgreSQL (integración y caja
negra).

> **Use siempre una base aparte para las pruebas.** Empiezan borrando el
> esquema. Por eso se niegan a correr si `TEST_DATABASE_URL` es la misma que
> `DATABASE_URL` o si el nombre de la base no contiene `test` o `prueba`. Las
> de caja negra tampoco se ejecutan contra un servidor que declare
> `APP_ENV=produccion`.

Lo que cubre la caja blanca:

- el rostro se acepta o se rechaza según el umbral de distancia
- el sistema distingue ingreso de salida según el sentido del punto y no
  duplica eventos, ni siquiera con fotogramas simultáneos
- un mismo desconocido se registra una vez, no una por segundo
- la alerta no se salta estados de su ciclo de vida
- la alerta sube sola al administrador cuando nadie la atiende
- una misma arma frente a la cámara no abre alertas repetidas
- la persona del fotograma queda como contexto; el portador solo lo fija el guardia
- el guardia atiende, confirma o descarta alertas y ve su evidencia desde el panel
- una estación sin credencial no puede registrar eventos ni alertas
- cada rol hace solo lo que le corresponde, verificado en cada petición
- no se almacena ningún rostro sin consentimiento
- los datos biométricos se borran al retirar a la persona
- las contraseñas se guardan con PBKDF2 y sal aleatoria

---

## Decisiones que conviene conocer

**La identidad se decide sobre la distancia, no sobre la confianza.** Dos fotos
de la misma persona distan entre 0.30 y 0.55; dos personas distintas, más de
0.60. Ese 0.60 es el umbral. La confianza es una lectura normalizada que se
guarda para el reporte. El 85 % de la hipótesis es la precisión global del
sistema sobre el conjunto de pruebas, no un piso de confianza por comparación.

**Los eventos no identificados se guardan.** `registro_acceso.persona_id`
admite nulo, con una restricción que impide declarar identificado a un evento
sin señalar a quién. El sistema no adivina, pero tampoco olvida: el guardia
verifica después.

**La alerta trae contexto, no culpables.** `alerta_arma` queda unida al evento
de acceso del mismo momento y a la persona identificada en él
(`persona_contexto_id`). Esa persona es información para el guardia: aparecer
en el mismo fotograma que un arma no prueba que se la porte. El portador
(`portador_id`) solo se registra cuando el guardia confirma la alerta después
de ver la imagen, y la base impide registrarlo de otro modo.

**Quien no autoriza su rostro sigue entrando.** Con `metodo = 'credencial'` se
produce el mismo registro. Nadie queda fuera del historial por ejercer su
derecho.

---

## Alcance y limitaciones

- La cámara **solo ve lo que está a la vista**. Un arma dentro de un bolso o
  bajo la ropa no se detecta, y así se declara.
- En el conjunto de prueba del modelo, el arma blanca no resultó más difícil
  de detectar que la de fuego, aunque su caja se ajusta peor (ver
  `docs/resultados_yolo.md`). Esas cifras son una cota superior: el desempeño
  en un punto de acceso real se mide con los protocolos presenciales.
- Las cifras de la literatura provienen de condiciones de laboratorio. El
  desempeño real depende de la resolución de la cámara y de la iluminación, por
  eso el RNF-14 fija un mínimo de 1280 x 720 y 200 lux.
- El servidor en plan gratuito se suspende por inactividad, de modo que el
  arranque en frío puede tardar cerca de un minuto.
