# FaceGuard UMB

Sistema web de seguridad para el reconocimiento facial de estudiantes y detección de armas basado en inteligencia artificial en la Universidad Manuela Beltrán.

Trabajo de grado, Ingeniería de Software modalidad virtual.
Autora: Laura Valentina Maldonado Pérez.
Asesora disciplinar: Luisa Graciela Arciniegas Zamora.

## El problema

El control de acceso universitario valida credenciales, no identidades. Un carné leído confirma que alguien presentó una tarjeta válida, no que quien la presentó sea su titular, y ningún control vigente advierte si esa persona ingresa portando un arma.

FaceGuard UMB no reemplaza al personal de seguridad. Le entrega información verificable en el momento en que la necesita. Cuando el sistema no alcanza la confianza mínima para identificar a alguien, no adivina: reporta el intento y deja la verificación al guardia.

## Estado del proyecto

| Sprint | Alcance | Estado |
|---|---|---|
| 0 y 1 | Diagnóstico, arquitectura, modelo de datos y diagramas UML | Completado |
| 2 | Módulo de reconocimiento facial integrado al backend | En curso |
| 3 y 4 | Módulo de detección de armas y plataforma web de consulta | Pendiente |
| 5 | Pruebas, métricas de desempeño e informe de evaluación | Pendiente |

## Arquitectura

```
Estación de captura (OpenCV)
        │  fotograma
        ▼
Backend Flask ──► servicios/reconocimiento_facial.py  (face_recognition + dlib)
        │     └─► servicios/deteccion_armas.py        (YOLOv8, sprint 3)
        │
        ▼
repositorio.py ──► PostgreSQL en Supabase
        │
        ▼
Plataforma web de consulta (panel y registros)
```

La decisión de diseño que sostiene todo lo demás es la separación entre la comparación de codificaciones, que es aritmética pura sobre numpy, y la extracción de la codificación, que sí necesita dlib. Esa frontera permite probar la lógica de identificación sin cámara ni GPU.

## Puesta en marcha

Requiere Python 3.10 o superior y PostgreSQL 15. Para el reconocimiento facial hace falta compilar dlib, que en macOS necesita `cmake`.

```bash
git clone https://github.com/lauramal/faceguard-umb.git
cd faceguard-umb

python -m venv .venv
source .venv/bin/activate          # en Windows: .venv\Scripts\activate

pip install -r requirements.txt

cp .env.example .env                # complete DATABASE_URL y SECRET_KEY
```

Cree el esquema en Supabase:

```bash
psql "$DATABASE_URL" -f db/schema.sql
psql "$DATABASE_URL" -f db/datos_prueba.sql
```

Cree el primer usuario administrador y levante el servidor:

```bash
python scripts/crear_usuario.py "Laura Maldonado" laura@umb.edu.co administrador
python run.py
```

El panel queda en `http://localhost:5000`.

## Uso

**Enrolar a un estudiante.** Requiere que el consentimiento informado esté firmado, porque sin él la aplicación se niega a procesar la imagen.

```bash
python scripts/enrolar.py 202012345
```

**Levantar un punto de acceso.**

```bash
python scripts/estacion_acceso.py 1
```

## API

| Método | Ruta | Descripción | Rol |
|---|---|---|---|
| GET | `/salud` | Estado del servicio | público |
| POST | `/api/accesos/identificar` | Procesa un fotograma y registra el evento | estación |
| GET | `/api/accesos` | Historial con filtros de fecha, estudiante y punto | todos |
| GET | `/api/estudiantes` | Listado de estudiantes | todos |
| POST | `/api/estudiantes` | Crea un estudiante | administrador |
| POST | `/api/estudiantes/<id>/enrolar` | Registra la codificación facial | administrador |
| GET | `/api/alertas` | Alertas de armas | todos |
| POST | `/api/alertas/<id>/cerrar` | Cierra una alerta con trazabilidad | administrador, guardia |

Ejemplo de respuesta de `/api/accesos/identificar`:

```json
{
  "identificado": true,
  "estudiante_id": 12,
  "nombre": "Laura Valentina Maldonado Pérez",
  "tipo_evento": "ingreso",
  "confianza": 0.9412,
  "registro_id": 337,
  "milisegundos": 412.6
}
```

Cuando la confianza no alcanza el umbral:

```json
{
  "identificado": false,
  "confianza": 0.71,
  "motivo": "confianza_insuficiente"
}
```

## Pruebas

```bash
python -m pytest -q
```

Las pruebas cubren la lógica de comparación de codificaciones, la alternancia entre ingreso y salida, el rechazo de rostros desconocidos y el control de acceso por roles en los endpoints. No requieren dlib, cámara ni base de datos.

## Tratamiento de datos personales

Los datos biométricos son datos sensibles según la Ley 1581 de 2012. El sistema aplica estas medidas:

- Solo se almacena la codificación de 128 dimensiones, nunca la fotografía original
- El enrolamiento se rechaza si el consentimiento informado no está firmado
- Las contraseñas se guardan con PBKDF2 y sal aleatoria
- El acceso a la información está restringido por roles
- Ninguna credencial vive en el repositorio; todo se lee de variables de entorno

## Estructura

```
app/
  servicios/reconocimiento_facial.py   codificación e identificación
  servicios/control_acceso.py          orquestación del proceso P2
  servicios/deteccion_armas.py         interfaz de YOLOv8, sprint 3
  api/                                 endpoints REST
  web.py                               plataforma web de consulta
  repositorio.py                       capa de acceso a datos
  seguridad.py                         autenticación y roles
db/schema.sql                          script de la base de datos
scripts/                               enrolamiento y estación de acceso
tests/                                 pruebas unitarias
```

## Licencia

Proyecto académico sin fines comerciales.
