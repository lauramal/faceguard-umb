-- Migracion 004: desenlace y fecha de cierre de las alertas, para el
-- seguimiento (filtrar confirmadas y falsos positivos) y el tiempo de atencion.
-- Aplica sobre una base que ya tiene la migracion 003.

BEGIN;

ALTER TABLE alerta_arma
    ADD COLUMN IF NOT EXISTS desenlace VARCHAR(20)
        CHECK (desenlace IN ('confirmada','falso_positivo')),
    ADD COLUMN IF NOT EXISTS fecha_cierre TIMESTAMP;

DROP VIEW IF EXISTS v_alerta_persona;

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

COMMIT;
