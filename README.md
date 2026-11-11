# FaceGuard

Sistema web de seguridad para la identificación facial de las personas que
ingresan y la detección de armas visibles o empuñadas en los puntos de acceso
de una institución de educación superior.

Trabajo de grado de Ingeniería de Software. El aporte no está en el
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

## Instalación

### Servidor de aplicación

```bash
pip install -r requirements.txt
cp .env.example .env          # y complete DATABASE_URL y SECRET_KEY
psql "$DATABASE_URL" -f db/schema.sql
python run.py
```

### Estación de captura

```bash
pip install -r requirements-estacion.txt
python scripts/estacion_acceso.py 1 --api https://su-servidor/
```

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
    alertas.py                 máquina de estados y escalamiento
  repositorio.py  única capa que escribe SQL
  seguridad.py    autenticación, roles, bloqueo de cuentas
  db.py           pool de conexiones
db/schema.sql     esquema completo con sus restricciones
scripts/          enrolamiento, alta de usuarios, estación de captura
tests/            suite de pruebas
```

---

## Pruebas

```bash
pytest                        # unitarias, con cobertura
TEST_DATABASE_URL=postgresql://... pytest    # añade las de integración
```

La suite tiene **233 pruebas** y **92 % de cobertura**. Las de integración
ejecutan el esquema real sobre PostgreSQL y verifican que las restricciones de
la base se comporten como afirma el documento.

Lo que cubre la caja blanca:

- el rostro se acepta o se rechaza según el umbral de distancia
- el sistema distingue ingreso de salida y no repite eventos dentro de la ventana
- la alerta no se salta estados de su ciclo de vida
- la alerta sube al administrador cuando nadie la atiende
- cada rol hace solo lo que le corresponde
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

**La alerta conoce a la persona.** `alerta_arma` referencia al evento de acceso
y a la persona, que es lo que permite responder quién portaba el arma y no solo
dónde fue detectada.

**Quien no autoriza su rostro sigue entrando.** Con `metodo = 'credencial'` se
produce el mismo registro. Nadie queda fuera del historial por ejercer su
derecho.

---

## Alcance y limitaciones

- La cámara **solo ve lo que está a la vista**. Un arma dentro de un bolso o
  bajo la ropa no se detecta, y así se declara.
- Las armas blancas son considerablemente más difíciles de detectar que las de
  fuego.
- Las cifras de la literatura provienen de condiciones de laboratorio. El
  desempeño real depende de la resolución de la cámara y de la iluminación, por
  eso el RNF-14 fija un mínimo de 1280 x 720 y 200 lux.
- El servidor en plan gratuito se suspende por inactividad, de modo que el
  arranque en frío puede tardar cerca de un minuto.
