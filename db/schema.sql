-- ============================================================================
-- FaceGuard - Script de generación de la base de datos
-- Motor: PostgreSQL 15 (Supabase)
--
-- Versión 2. Incorpora las correcciones de la asesoría:
--   * El dominio deja de ser "estudiante" y pasa a "persona", para cubrir
--     estudiantes, docentes, personal administrativo y visitantes.
--   * Los eventos de acceso no identificados quedan registrados.
--   * La alerta de arma se vincula a la persona y al evento de acceso.
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
    ubicacion       VARCHAR(150)
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
    id                 SERIAL PRIMARY KEY,
    camara_id          INTEGER NOT NULL REFERENCES camara(id),
    punto_acceso_id    INTEGER NOT NULL REFERENCES punto_acceso(id),
    -- Estas dos columnas son el aporte central del trabajo: la alerta deja de
    -- ser un hecho anónimo de la cámara y queda unida al evento de acceso y a
    -- la persona identificada en ese momento, cuando la hubo.
    registro_acceso_id INTEGER REFERENCES registro_acceso(id),
    persona_id         INTEGER REFERENCES persona(id),
    tipo_arma          VARCHAR(20) NOT NULL
                       CHECK (tipo_arma IN ('arma_fuego','arma_blanca','indeterminada')),
    confianza          NUMERIC(5,4) NOT NULL CHECK (confianza BETWEEN 0 AND 1),
    imagen_url         TEXT,
    fecha_hora         TIMESTAMP NOT NULL DEFAULT NOW(),
    -- 'escalada' faltaba: es el estado al que pasa la alerta cuando ningún
    -- guardia la atiende dentro del tiempo definido.
    estado             VARCHAR(20) NOT NULL DEFAULT 'generada'
                       CHECK (estado IN ('generada','notificada','en_atencion','escalada',
                                         'confirmada','falso_positivo','cerrada')),
    atendida_por       INTEGER REFERENCES usuario(id),
    fecha_atencion     TIMESTAMP,
    fecha_escalamiento TIMESTAMP,
    CONSTRAINT atencion_con_responsable
        CHECK (estado NOT IN ('en_atencion','confirmada','falso_positivo')
               OR atendida_por IS NOT NULL)
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
CREATE INDEX idx_alerta_persona      ON alerta_arma(persona_id);
CREATE INDEX idx_codificacion_persona ON codificacion_facial(persona_id);
CREATE INDEX idx_auditoria_fecha     ON auditoria(fecha_hora);
CREATE INDEX idx_auditoria_usuario   ON auditoria(usuario_id);

-- ----------------------------------------------------------------------------
-- Vista de apoyo: alertas con la persona asociada
-- ----------------------------------------------------------------------------

CREATE VIEW v_alerta_persona AS
SELECT a.id              AS alerta_id,
       a.fecha_hora,
       a.tipo_arma,
       a.confianza,
       a.estado,
       pa.nombre         AS punto_acceso,
       p.id              AS persona_id,
       p.documento,
       p.nombres,
       p.apellidos,
       p.tipo_persona,
       r.id              AS registro_acceso_id,
       r.resultado       AS resultado_identificacion
FROM alerta_arma a
JOIN punto_acceso pa          ON pa.id = a.punto_acceso_id
LEFT JOIN registro_acceso r   ON r.id  = a.registro_acceso_id
LEFT JOIN persona p           ON p.id  = a.persona_id;

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
