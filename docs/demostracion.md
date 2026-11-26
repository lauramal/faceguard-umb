# Cómo demostrar que FaceGuard funciona

Hay tres formas, de la más sencilla a la más completa. Las dos primeras no
necesitan cámara, base de datos ni un computador potente.

## 1. Las pruebas automáticas en GitHub (no hay que instalar nada)

Cada vez que se sube un cambio, GitHub ejecuta las 325 pruebas del proyecto,
incluidas las de integración y caja negra contra un PostgreSQL real que crea
para la ocasión.

1. Abra el repositorio en GitHub y entre a la pestaña **Actions**.
2. Abra la ejecución más reciente del flujo **Pruebas**.
3. Una marca verde significa que todas las pruebas pasaron. Dentro se ve la
   lista completa y el porcentaje de cobertura.

Si quiere volver a ejecutarlas delante de la asesora: **Actions → Pruebas →
Run workflow**.

## 2. El sistema funcionando, en modo demostración

Levanta el servidor y el panel reales con una base en memoria y una estación
de captura simulada que, cada pocos segundos, envía ingresos, personas
desconocidas y detecciones de arma con su fotograma, por HTTP y con la
credencial de la cámara, igual que la estación real.

**Sin instalar nada (GitHub Codespaces):** en el repositorio, botón verde
**Code → Codespaces → Create codespace on main**. En la terminal que se abre:

```bash
pip install -r requirements.txt
python scripts/demo.py
```

Codespaces muestra un aviso para abrir el puerto 5000 en el navegador.

**En un computador con Python 3.11 o 3.12:** los mismos dos comandos, y abrir
http://localhost:5000.

Usuarios de la demostración:

| Rol | Correo | Contraseña |
|---|---|---|
| Guardia | guardia@demo.edu | Guardia-2026 |
| Administrador | admin@demo.edu | Admin-2026 |
| Consulta | consulta@demo.edu | Consulta-2026 |

Guion sugerido para mostrarle a la asesora (unos 5 minutos):

1. Entrar como **guardia**. Ver cómo llegan solos los ingresos y salidas, y
   cómo una persona desconocida queda registrada como *no identificada*.
2. Esperar una alerta de arma. Mostrar que la persona aparece como
   **contexto**, no como portadora, y que el contador de **detecciones** sube
   sin abrir alertas nuevas.
3. Pulsar **Ver evidencia**, luego **Atender**, y cerrar con **Confirmar
   arma** (marcando al portador) o **Descartar: falso positivo**.
4. Dejar una alerta sin atender un minuto: pasa sola a **escalada** y sube al
   principio de la lista.
5. Salir y entrar como **consulta**: ve las alertas pero no puede atenderlas.
   Ir a **Registros** y filtrar el historial.

La franja amarilla deja claro que los datos son de ejemplo. **Las cifras de
la demostración no son resultados de evaluación.** Los resultados del trabajo
salen de los protocolos de `docs/pruebas_caja_negra.md`.

## 3. Con cámara real

Requiere la base en Supabase, el servidor desplegado y la estación de captura
con `requirements-estacion.txt` (dlib y YOLOv8). Ver el README, sección
Instalación, y los protocolos A a E de `docs/pruebas_caja_negra.md`.
