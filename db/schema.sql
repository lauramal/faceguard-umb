-- ============================================================================
-- FaceGuard - Script de generación de la base de datos
-- Motor: PostgreSQL 15 (Supabase)
--
-- Versión 3. Incorpora las correcciones de la asesoría:
--   * El dominio deja de ser "estudiante" y pasa a "persona", para cubrir
--     estudiantes, docentes, personal administrativo y visitantes.
--   * Los eventos de acceso no identificados quedan registrados.
--   * La alerta de arma se vincula al evento de acceso. La persona de ese
--     evento es contexto; el portador solo lo fija el guardia al verificar.
--   * Las detecciones repetidas suman a la alerta abierta en vez de duplicarla.
--   * Cada cámara tiene una credencial para autenticar su estación.
--   * Cada punto de acceso declara su sentido (entrada, salida o mixto).
--   * Se incorpora la bitácora de auditoría.
--   * Los estados de cada tabla coinciden con los diagramas de estados.
--   * Se admite el ingreso con credencial para quien no autorice biometría.
-- ============================================================================

-- ----------------------------------------------------------------------------
-- Institución y puntos de acceso
-- ----------------------------------------------------------------------------

CREATE TABLE institucion (
    id          SERIAL PRIMARY KEY,
    nombre      VARCHAR(120) NOT NULL,
    ciudad      VARCHAR(80),
    -- Días que la institución conserva los registros antes de depurarlos.
    -- Da soporte al requerimiento de retención de datos.
    retencion_dias  INTEGER NOT NULL DEFAULT 180
                    CHECK (retencion_dias BETWEEN 1 AND 3650)
);

CREATE TABLE punto_acceso (
    id              SERIAL PRIMARY KEY,
    institucion_id  INTEGER NOT NULL REFERENCES institucion(id),
    nombre          VARCHAR(80) NOT NULL,
    ubicacion       VARCHAR(150),
    -- Sentido del punto. Un torniquete de solo entrada registra siempre
    -- ingresos; uno de solo salida, siempre salidas. 'mixto' alterna segun
    -- el ultimo evento de la persona.
    sentido         VARCHAR(10) NOT NULL DEFAULT 'mixto'
                    CHECK (sentido IN ('entrada','salida','mixto'))
);

CREATE TABLE camara (
    id                 SERIAL PRIMARY KEY,
    punto_acceso_id    INTEGER NOT NULL REFERENCES punto_acceso(id),
    identificador      VARCHAR(60) NOT NULL,
    tipo               VARCHAR(40),
    -- Resolución y luminancia reales del dispositivo. Permiten contrastar
    -- cada punto de acceso contra el mínimo de hardware exigido y explicar
    -- las diferencias de desempeño entre cámaras.
    resolucion_ancho   INTEGER CHECK (resolucion_ancho > 0),
    resolucion_alto    INTEGER CHECK (resolucion_alto  > 0),
    lux_minimo         INTEGER,
    estado             VARCHAR(20) NOT NULL DEFAULT 'activa'
                       CHECK (estado IN ('activa','inactiva','mantenimiento')),
    -- Credencial de la estacion de captura asociada a esta camara. Se guarda
    -- solo el resumen SHA-256 del secreto; el secreto se entrega una vez al
    -- administrador. Sin ella, el servidor no acepta eventos ni alertas.
    token_hash         CHAR(64),
    UNIQUE (punto_acceso_id, identificador)
);

-- ----------------------------------------------------------------------------
-- Usuarios del sistema y roles
-- ----------------------------------------------------------------------------

CREATE TABLE rol (
    id           SERIAL PRIMARY KEY,
    nombre       VARCHAR(50) NOT NULL UNIQUE,
    descripcion  TEXT,
    -- Permisos del rol. El diagrama de clases declara este atributo, de modo
    -- que la tabla debe conservarlo.
    permisos     JSONB NOT NULL DEFAULT '[]'::jsonb
);

CREATE TABLE usuario (
    id                SERIAL PRIMARY KEY,
    nombre            VARCHAR(100) NOT NULL,
    correo            VARCHAR(120) NOT NULL UNIQUE,
    contrasena_hash   VARCHAR(255) NOT NULL,
    rol_id            INTEGER NOT NULL REFERENCES rol(id),
    -- Reemplaza al booleano "activo". Los cuatro valores son los mismos
    -- estados del diagrama de la clase Usuario.
    estado            VARCHAR(20) NOT NULL DEFAULT 'registrado'
                      CHECK (estado IN ('registrado','activo','bloqueado','inactivo')),
    intentos_fallidos INTEGER NOT NULL DEFAULT 0 CHECK (intentos_fallidos >= 0),
    ultimo_acceso     TIMESTAMP,
    creado_en         TIMESTAMP NOT NULL DEFAULT NOW()
);

-- ----------------------------------------------------------------------------
-- Personas y biometría
-- ----------------------------------------------------------------------------

CREATE TABLE persona (
    id              SERIAL PRIMARY KEY,
    institucion_id  INTEGER NOT NULL REFERENCES institucion(id),
    documento       VARCHAR(30) NOT NULL,
    -- La población del estudio incluye estudiantes, docentes y personal
    -- administrativo, de modo que el dominio no puede llamarse "estudiante".
    tipo_persona    VARCHAR(20) NOT NULL
                    CHECK (tipo_persona IN ('estudiante','docente','administrativo','visitante')),
    nombres         VARCHAR(100) NOT NULL,
    apellidos       VARCHAR(100) NOT NULL,
    correo          VARCHAR(120),
    adscripcion     VARCHAR(120),   -- programa, facultad o dependencia
    estado          VARCHAR(20) NOT NULL DEFAULT 'preinscrito'
                    CHECK (estado IN ('preinscrito','enrolado','activo','suspendido','retirado')),
    -- Consentimiento informado. Quien no autorice el tratamiento biométrico
    -- conserva el derecho de ingresar con su credencial institucional.
    autoriza_biometria    BOOLEAN NOT NULL DEFAULT FALSE,
    fecha_consentimiento  TIMESTAMP,
    creado_en       TIMESTAMP NOT NULL DEFAULT NOW(),
    UNIQUE (institucion_id, documento),
    -- No se puede declarar consentimiento sin registrar su fecha.
    CONSTRAINT consentimiento_fechado
        CHECK (autoriza_biometria = FALSE OR fecha_consentimiento IS NOT NULL)
);

CREATE TABLE codificacion_facial (
    id             SERIAL PRIMARY KEY,
    persona_id     INTEGER NOT NULL REFERENCES persona(id) ON DELETE CASCADE,
    vector         DOUBLE PRECISION[] NOT NULL,   -- embedding de 128 dimensiones
    fecha_captura  TIMESTAMP NOT NULL DEFAULT NOW(),
    activa         BOOLEAN NOT NULL DEFAULT TRUE,
    CONSTRAINT vector_de_128 CHECK (array_length(vector, 1) = 128)
);

-- ----------------------------------------------------------------------------
-- Registros de acceso
-- ----------------------------------------------------------------------------

CREATE TABLE registro_acceso (
    id               SERIAL PRIMARY KEY,
    punto_acceso_id  INTEGER NOT NULL REFERENCES punto_acceso(id),
    camara_id        INTEGER REFERENCES camara(id),
    -- Nulo cuando el sistema no logra identificar a la persona. Ese evento
    -- también debe quedar registrado, porque es el que el guardia verifica.
    persona_id       INTEGER REFERENCES persona(id),
    tipo_evento      VARCHAR(10) NOT NULL CHECK (tipo_evento IN ('ingreso','salida')),
    -- Vía por la que se resolvió el acceso. 'credencial' cubre a quien no
    -- autorizó el tratamiento biométrico.
    metodo           VARCHAR(15) NOT NULL DEFAULT 'facial'
                     CHECK (metodo IN ('facial','credencial','manual')),
    resultado        VARCHAR(20) NOT NULL
                     CHECK (resultado IN ('identificado','no_identificado','verificado_manual','rechazado')),
    fecha_hora       TIMESTAMP NOT NULL DEFAULT NOW(),
    -- Se guardan por separado. La distancia euclidiana es lo que el algoritmo
    -- calcula; la confianza es su lectura normalizada. Confundirlas fue uno de
    -- los errores detectados en la revisión del código.
    distancia        NUMERIC(6,4) CHECK (distancia >= 0),
    confianza        NUMERIC(5,4) CHECK (confianza BETWEEN 0 AND 1),
    -- Evidencia del evento no identificado, para que el guardia lo verifique.
    -- Se depura según institucion.retencion_dias.
    imagen_url       TEXT,
    verificado_por   INTEGER REFERENCES usuario(id),
    fecha_verificacion TIMESTAMP,
    -- Un evento identificado tiene que decir a quién identificó.
    CONSTRAINT identificado_con_persona
        CHECK (resultado <> 'identificado' OR persona_id IS NOT NULL),
    -- Una verificación manual deja constancia de quién la hizo.
    CONSTRAINT verificacion_con_responsable
        CHECK (resultado <> 'verificado_manual' OR verificado_por IS NOT NULL)
);

-- ----------------------------------------------------------------------------
-- Alertas de arma visible
-- ----------------------------------------------------------------------------

CREATE TABLE alerta_arma (
    id                  SERIAL PRIMARY KEY,
    camara_id           INTEGER NOT NULL REFERENCES camara(id),
    punto_acceso_id     INTEGER NOT NULL REFERENCES punto_acceso(id),
    -- La alerta queda unida al evento de acceso que ocurrió en el mismo
    -- momento y a la persona identificada en ese evento. Esa persona es
    -- CONTEXTO, no portadora: aparecer en el mismo fotograma que un arma no
    -- prueba que la lleve. La posesión solo la establece el guardia al
    -- verificar la evidencia, y entonces se registra en portador_id.
    registro_acceso_id  INTEGER REFERENCES registro_acceso(id),
    persona_contexto_id INTEGER REFERENCES persona(id),
    portador_id         INTEGER REFERENCES persona(id),
    tipo_arma           VARCHAR(20) NOT NULL
                        CHECK (tipo_arma IN ('arma_fuego','arma_blanca','indeterminada')),
    confianza           NUMERIC(5,4) NOT NULL CHECK (confianza BETWEEN 0 AND 1),
    -- Fotograma de la detección, para que el guardia verifique si es un arma
    -- visible. Se depura según institucion.retencion_dias.
    imagen_url          TEXT,
    fecha_hora          TIMESTAMP NOT NULL DEFAULT NOW(),
    -- Una misma arma vista en fotogramas seguidos no abre alertas nuevas:
    -- suma detecciones a la alerta abierta y actualiza la última marca.
    detecciones         INTEGER NOT NULL DEFAULT 1 CHECK (detecciones >= 1),
    ultima_deteccion    TIMESTAMP NOT NULL DEFAULT NOW(),
    -- 'escalada' es el estado al que pasa la alerta cuando ningún guardia la
    -- atiende dentro del tiempo definido.
    estado              VARCHAR(20) NOT NULL DEFAULT 'generada'
                        CHECK (estado IN ('generada','notificada','en_atencion','escalada',
                                          'confirmada','falso_positivo','cerrada')),
    atendida_por        INTEGER REFERENCES usuario(id),
    fecha_atencion      TIMESTAMP,
    fecha_escalamiento  TIMESTAMP,
    -- Como termino la alerta. 'cerrada' es el estado final de todas, asi que
    -- el desenlace se guarda aparte para filtrar y hacer seguimiento.
    desenlace           VARCHAR(20)
                        CHECK (desenlace IN ('confirmada','falso_positivo')),
    fecha_cierre        TIMESTAMP,
    CONSTRAINT atencion_con_responsable
        CHECK (estado NOT IN ('en_atencion','confirmada','falso_positivo')
               OR atendida_por IS NOT NULL),
    -- Solo una alerta confirmada por un guardia puede señalar a un portador.
    CONSTRAINT portador_verificado
        CHECK (portador_id IS NULL
               OR (estado IN ('confirmada','cerrada') AND atendida_por IS NOT NULL))
);

-- ----------------------------------------------------------------------------
-- Bitácora de auditoría
-- ----------------------------------------------------------------------------

CREATE TABLE auditoria (
    id          SERIAL PRIMARY KEY,
    usuario_id  INTEGER REFERENCES usuario(id),
    accion      VARCHAR(40) NOT NULL,
    entidad     VARCHAR(40),
    entidad_id  INTEGER,
    detalle     TEXT,
    ip_origen   INET,
    fecha_hora  TIMESTAMP NOT NULL DEFAULT NOW()
);

-- ----------------------------------------------------------------------------
-- Índices
-- ----------------------------------------------------------------------------

CREATE INDEX idx_registro_fecha      ON registro_acceso(fecha_hora);
CREATE INDEX idx_registro_persona    ON registro_acceso(persona_id);
CREATE INDEX idx_registro_resultado  ON registro_acceso(resultado);
CREATE INDEX idx_alerta_fecha        ON alerta_arma(fecha_hora);
CREATE INDEX idx_alerta_estado       ON alerta_arma(estado);
CREATE INDEX idx_alerta_contexto     ON alerta_arma(persona_contexto_id);
CREATE INDEX idx_alerta_portador     ON alerta_arma(portador_id);
CREATE INDEX idx_alerta_abierta     ON alerta_arma(camara_id, tipo_arma, estado);
CREATE INDEX idx_codificacion_persona ON codificacion_facial(persona_id);
CREATE INDEX idx_auditoria_fecha     ON auditoria(fecha_hora);
CREATE INDEX idx_auditoria_usuario   ON auditoria(usuario_id);

-- ----------------------------------------------------------------------------
-- Vista de apoyo: alertas con la persona asociada
-- ----------------------------------------------------------------------------

CREATE VIEW v_alerta_persona AS
SELECT a.id                AS alerta_id,
       a.fecha_hora,
       a.ultima_deteccion,
       a.detecciones,
       a.tipo_arma,
       a.confianza,
       a.estado,
       a.imagen_url,
       a.camara_id,
       a.fecha_escalamiento,
       a.fecha_atencion,
       a.desenlace,
       a.fecha_cierre,
       u.nombre            AS atendida_por_nombre,
       pa.nombre           AS punto_acceso,
       r.id                AS registro_acceso_id,
       r.resultado         AS resultado_identificacion,
       -- Persona identificada en el mismo evento: contexto, no portadora.
       pc.id               AS persona_contexto_id,
       pc.documento        AS contexto_documento,
       pc.nombres          AS contexto_nombres,
       pc.apellidos        AS contexto_apellidos,
       pc.tipo_persona     AS contexto_tipo_persona,
       -- Persona que el guardia confirmó como portadora tras verificar.
       pp.id               AS portador_id,
       pp.nombres          AS portador_nombres,
       pp.apellidos        AS portador_apellidos
FROM alerta_arma a
JOIN punto_acceso pa          ON pa.id = a.punto_acceso_id
LEFT JOIN registro_acceso r   ON r.id  = a.registro_acceso_id
LEFT JOIN persona pc          ON pc.id = a.persona_contexto_id
LEFT JOIN persona pp          ON pp.id = a.portador_id
LEFT JOIN usuario u           ON u.id  = a.atendida_por;

-- ----------------------------------------------------------------------------
-- Datos iniciales
-- ----------------------------------------------------------------------------

INSERT INTO rol (nombre, descripcion, permisos) VALUES
 ('administrador', 'Gestión total del sistema, usuarios y reportes',
  '["persona:crud","usuario:crud","camara:crud","alerta:atender","reporte:generar","auditoria:consultar"]'),
 ('guardia', 'Monitoreo de accesos, verificación manual y atención de alertas',
  '["acceso:consultar","acceso:verificar","alerta:atender"]'),
 ('consulta', 'Acceso de solo lectura a registros y reportes',
  '["acceso:consultar","reporte:generar"]');
