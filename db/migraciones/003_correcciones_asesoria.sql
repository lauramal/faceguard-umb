-- Migracion de la version 2 a la 3 del esquema, para una base que ya existe
-- (por ejemplo, el proyecto de Supabase). Una base nueva no la necesita:
-- basta con ejecutar db/schema.sql.
--
--     psql "$DATABASE_URL" -f db/migraciones/003_correcciones_asesoria.sql

BEGIN;

ALTER TABLE punto_acceso
    ADD COLUMN IF NOT EXISTS sentido VARCHAR(10) NOT NULL DEFAULT 'mixto'
        CHECK (sentido IN ('entrada','salida','mixto'));

ALTER TABLE camara ADD COLUMN IF NOT EXISTS token_hash CHAR(64);

DROP VIEW IF EXISTS v_alerta_persona;

ALTER TABLE alerta_arma RENAME COLUMN persona_id TO persona_contexto_id;
ALTER TABLE alerta_arma
    ADD COLUMN IF NOT EXISTS portador_id INTEGER REFERENCES persona(id),
    ADD COLUMN IF NOT EXISTS detecciones INTEGER NOT NULL DEFAULT 1 CHECK (detecciones >= 1),
    ADD COLUMN IF NOT EXISTS ultima_deteccion TIMESTAMP NOT NULL DEFAULT NOW();
UPDATE alerta_arma SET ultima_deteccion = fecha_hora;
ALTER TABLE alerta_arma ADD CONSTRAINT portador_verificado
    CHECK (portador_id IS NULL
           OR (estado IN ('confirmada','cerrada') AND atendida_por IS NOT NULL));

DROP INDEX IF EXISTS idx_alerta_persona;
CREATE INDEX IF NOT EXISTS idx_alerta_contexto ON alerta_arma(persona_contexto_id);
CREATE INDEX IF NOT EXISTS idx_alerta_portador ON alerta_arma(portador_id);
CREATE INDEX IF NOT EXISTS idx_alerta_abierta  ON alerta_arma(camara_id, tipo_arma, estado);

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
       pa.nombre           AS punto_acceso,
       r.id                AS registro_acceso_id,
       r.resultado         AS resultado_identificacion,
       pc.id               AS persona_contexto_id,
       pc.documento        AS contexto_documento,
       pc.nombres          AS contexto_nombres,
       pc.apellidos        AS contexto_apellidos,
       pc.tipo_persona     AS contexto_tipo_persona,
       pp.id               AS portador_id,
       pp.nombres          AS portador_nombres,
       pp.apellidos        AS portador_apellidos
FROM alerta_arma a
JOIN punto_acceso pa          ON pa.id = a.punto_acceso_id
LEFT JOIN registro_acceso r   ON r.id  = a.registro_acceso_id
LEFT JOIN persona pc          ON pc.id = a.persona_contexto_id
LEFT JOIN persona pp          ON pp.id = a.portador_id;

COMMIT;
