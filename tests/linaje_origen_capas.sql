-- tests/linaje_origen_capas.sql — control de reglas de origen con el LINAJE de Unity Catalog (DEMO).
-- Dos niveles:
--   a) tabla -> tabla: lecturas directas registradas hacia tablas Silver/Gold.
--   b) pipeline -> tabla leída: todo lo que lee cada pipeline, según la capa del pipeline
--      (cubre AUTO CDC FROM SNAPSHOT con función, donde el linaje no registra tabla destino).
-- Veredicto por fila; violaciones = filas con 'FAIL'. Horas en UTC.
WITH lin AS (
  SELECT l.*, coalesce(source_table_schema, '') AS esq_origen
  FROM system.access.table_lineage l
  WHERE event_date >= current_date() - INTERVAL 7 DAYS
    AND (source_table_full_name IS NOT NULL OR source_path IS NOT NULL)
),
nivel_tabla AS (
  SELECT 'tabla' AS nivel,
         CASE WHEN target_table_schema LIKE '%\_silver' THEN 'silver' ELSE 'gold' END AS capa,
         target_table_full_name AS destino,
         coalesce(source_table_full_name, source_path) AS origen, esq_origen, event_time
  FROM lin
  WHERE target_table_catalog = 'workspace'
    AND (target_table_schema LIKE '%\_silver' OR target_table_schema LIKE '%\_gold')
    AND coalesce(source_table_full_name, '') <> target_table_full_name
),
nivel_pipeline AS (
  SELECT 'pipeline' AS nivel, p.capa, concat('pipeline ', p.nombre) AS destino,
         coalesce(source_table_full_name, source_path) AS origen, esq_origen, event_time
  FROM lin JOIN workspace.estandares.pipelines_por_capa p
    ON lin.entity_metadata.dlt_pipeline_info.dlt_pipeline_id = p.pipeline_id
),
todo AS (SELECT * FROM nivel_tabla UNION ALL SELECT * FROM nivel_pipeline)
SELECT nivel, capa, destino, origen,
       CASE WHEN capa = 'silver' AND (esq_origen IN ('bronce', 'referencia') OR esq_origen LIKE '%\_silver') THEN 'PASS'
            WHEN capa = 'gold'   AND (esq_origen LIKE '%\_silver' OR esq_origen LIKE '%\_gold')             THEN 'PASS'
            ELSE 'FAIL' END AS veredicto,
       max(event_time) AS ultimo_evento_utc, count(*) AS eventos
FROM todo
GROUP BY ALL
ORDER BY veredicto, nivel, destino, origen
