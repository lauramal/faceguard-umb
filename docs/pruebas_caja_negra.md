# Protocolo de pruebas de caja negra

Las pruebas de caja negra miran el sistema desde afuera, sin conocer el código,
igual que lo haría una persona usándolo. Este documento recoge las nueve que
exige la asesoría y dice cuáles están automatizadas y cuáles hay que ejecutar
en presencia física.

---

## Resumen

| # | Prueba | Cómo se ejecuta | Estado |
|---|---|---|---|
| 1 | Persona registrada pasa y queda registrada | Automatizada | `tests/test_caja_negra.py` |
| 2 | Persona no registrada avisa al guardia | Automatizada | `tests/test_caja_negra.py` |
| 3 | Arma de juguete genera alerta | **Presencial** | Protocolo A |
| 4 | Celular, sombrilla o mano NO generan alerta | **Presencial** | Protocolo B |
| 5 | Usuario sin permiso no atiende alertas | Automatizada | `tests/test_caja_negra.py` |
| 6 | Varios intentos fallidos bloquean la cuenta | Automatizada | `tests/test_caja_negra.py` |
| 7 | Exportar reporte funciona | Automatizada | `tests/test_caja_negra.py` |
| 8 | Tiempos: 3 s rostro, 2 s armas | Mixta | Automatizada + Protocolo C |
| 9 | SUS da 68 o más | **Presencial** | Protocolo D |

---

## Ejecutar las automatizadas

```bash
# contra el servidor desplegado
export FACEGUARD_URL=https://su-servidor.onrender.com
export TEST_DATABASE_URL=postgresql://usuario:clave@host:5432/base
pytest tests/test_caja_negra.py --no-cov -v

# o en local, sin despliegue (levanta la app sola)
export TEST_DATABASE_URL=postgresql://usuario:clave@localhost:5432/faceguard_test
pytest tests/test_caja_negra.py --no-cov -v
```

> Si apunta a Render, **ábralo en el navegador primero**. El plan gratuito
> suspende el servicio por inactividad y el primer arranque tarda cerca de un
> minuto, lo que haría fallar las pruebas por tiempo de espera.

---

## Protocolo A. Detección de un arma visible

**Qué se verifica:** que el sistema genere una alerta cuando alguien exhibe o
empuña un arma frente a la cámara.

**Materiales:** una réplica o arma de juguete que se parezca a una pistola, y
un cuchillo de cocina romo. Avise al personal del lugar antes de la prueba.

**Pasos**

1. Deje corriendo la estación de captura: `python scripts/estacion_acceso.py 1 --api <URL>`
2. Abra el panel web en otra pantalla, con sesión de guardia
3. Una persona se ubica frente a la cámara **con el arma a la vista**, a unos 2 metros
4. Observe la consola de la estación y el panel

**Qué debe pasar**

- la consola imprime `ALERTA: arma_fuego (0.xx)` o `arma_blanca`
- la alerta aparece en el panel en estado *notificada*
- la alerta muestra **el nombre de la persona**, no solo la cámara

**Qué registrar**

| Intento | Tipo de arma | Distancia | ¿Alertó? | Confianza | Segundos |
|---|---|---|---|---|---|
| 1 | pistola | 2 m | | | |
| 2 | pistola | 4 m | | | |
| 3 | cuchillo | 2 m | | | |
| 4 | cuchillo | 4 m | | | |

Repita cada escenario cinco veces. La tasa de acierto por tipo de arma va al
Capítulo IV.

> Es esperable que el cuchillo falle más que la pistola. **Repórtelo tal cual**:
> confirma lo que el documento ya anticipa y le da seriedad al trabajo.

---

## Protocolo B. Objetos que NO deben alarmar

**Qué se verifica:** que el sistema no genere falsas alarmas. Esta es la
prueba más importante del módulo, porque un guardia que recibe avisos
equivocados termina por ignorarlos todos.

**Materiales:** un celular, una sombrilla o paraguas, una billetera, un
control remoto, y la mano en forma de pistola.

**Pasos**

1. Con la estación corriendo, muestre cada objeto frente a la cámara durante
   diez segundos
2. Anote si aparece alguna alerta

**Qué debe pasar:** ninguna alerta, en ningún caso.

| Objeto | Intentos | Falsas alarmas |
|---|---|---|
| Celular | 5 | |
| Sombrilla | 5 | |
| Billetera | 5 | |
| Control remoto | 5 | |
| Mano en forma de pistola | 5 | |

**Si hay falsas alarmas:** suba `UMBRAL_ARMA` en el `.env` (por ejemplo de
0.70 a 0.80) y repita. Si persisten, agregue fotos de esos objetos al dataset
como ejemplos negativos y reentrene.

---

## Protocolo C. Tiempos en el equipo real

**Qué se verifica:** el RNF-01 (tres segundos para el rostro) y el RNF-02 (dos
segundos para las armas), medidos **en la estación de captura**, que es donde
realmente corren los modelos.

```bash
python scripts/medir_tiempos.py --api <URL> --repeticiones 30
```

El script mide por separado la codificación facial, la detección de armas y la
respuesta del servidor, y dice si cada requisito se cumple.

> Las pruebas automatizadas miden solo la parte del servidor, que es rápida
> porque solo compara vectores. El tiempo que importa para el requisito es el
> total, y ese se mide aquí.

---

## Protocolo D. Cuestionario SUS

**Qué se verifica:** el RNF-05, que fija una meta de 68 puntos o más.

**Participantes:** entre cinco y ocho personas del perfil de usuario real,
idealmente personal de seguridad. Nunca la autora del trabajo.

**Pasos**

1. Déle a cada participante tres tareas concretas, sin explicarle cómo:
   - consultar quién ingresó ayer entre las 8 y las 10 de la mañana
   - atender una alerta y cerrarla como falso positivo
   - exportar el reporte del último mes
2. Observe sin intervenir. Anote dónde se traba
3. Al terminar, aplique el cuestionario de abajo
4. Calcule el puntaje: `python scripts/sus.py respuestas.csv`

**Las diez afirmaciones**, cada una de 1 (muy en desacuerdo) a 5 (muy de acuerdo):

1. Creo que usaría este sistema con frecuencia
2. El sistema me pareció innecesariamente complejo
3. Pensé que el sistema era fácil de usar
4. Creo que necesitaría ayuda técnica para poder usar este sistema
5. Las funciones del sistema están bien integradas
6. Pensé que había demasiada inconsistencia en el sistema
7. Imagino que la mayoría aprendería a usar este sistema muy rápido
8. Encontré el sistema muy incómodo de usar
9. Me sentí muy seguro usando el sistema
10. Necesité aprender muchas cosas antes de poder usar el sistema

**Interpretación del puntaje**

| Puntaje | Lectura |
|---|---|
| 80 o más | Excelente |
| 68 a 79 | Por encima del promedio. **Cumple el RNF-05** |
| 51 a 67 | Por debajo del promedio |
| 50 o menos | Deficiente, hay que rediseñar |

---

## Evidencia que debe quedar

Para la sustentación conviene guardar:

- la salida completa de `pytest tests/test_caja_negra.py -v`
- las tablas de los protocolos A y B, llenas a mano
- la salida de `scripts/medir_tiempos.py`
- el CSV de respuestas del SUS y el puntaje calculado
- fotos o video de la prueba presencial
