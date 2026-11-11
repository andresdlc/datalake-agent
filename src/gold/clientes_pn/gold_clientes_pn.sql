-- Pipeline Gold — dominio clientes personas naturales (DEMO)
-- Implementación revisada por un humano a partir de la propuesta del agente (capa = 'gold').
-- REGLA DE ORIGEN: Gold solo lee `*_silver` y `*_gold`. Nunca `bronce` ni `referencia`.

CREATE OR REFRESH MATERIALIZED VIEW cliente_360 (
  CONSTRAINT clave_no_nula      EXPECT (cod_cliente IS NOT NULL) ON VIOLATION FAIL UPDATE,
  CONSTRAINT saldos_no_negativos EXPECT (saldo_pasivos >= 0 AND saldo_activos >= 0),
  CONSTRAINT segmento_informado EXPECT (cod_segmento IS NOT NULL),
  CONSTRAINT edad_razonable     EXPECT (edad IS NULL OR edad BETWEEN 18 AND 110)
)
COMMENT 'Gold - vista 360 del cliente persona natural vigente: perfil no identificable + agregados de productos activos. Grano: un registro por cliente vigente.'
AS
WITH cuentas AS (
  SELECT cod_cliente,
         count(*)                                                   AS num_productos_activos,
         count_if(tipo_balance = 'Pasivo')                          AS num_productos_pasivo,
         count_if(tipo_balance = 'Activo')                          AS num_productos_activo,
         CAST(sum(CASE WHEN tipo_balance = 'Pasivo' THEN saldo ELSE 0 END) AS DECIMAL(18,2)) AS saldo_pasivos,
         CAST(sum(CASE WHEN tipo_balance = 'Activo' THEN saldo ELSE 0 END) AS DECIMAL(18,2)) AS saldo_activos
  FROM workspace.clientes_pn_silver.cuentas_pn
  WHERE estado = 'ACTIVA'
  GROUP BY cod_cliente
)
SELECT c.cod_cliente,
       c.cod_tipo_documento,
       c.cod_segmento,
       c.genero,
       c.estado_civil,
       floor(months_between(current_date(), c.fecha_nacimiento) / 12)  AS edad,
       CASE WHEN c.fecha_nacimiento IS NULL THEN 'SIN DATO'
            WHEN floor(months_between(current_date(), c.fecha_nacimiento) / 12) < 30 THEN '18-29'
            WHEN floor(months_between(current_date(), c.fecha_nacimiento) / 12) < 45 THEN '30-44'
            WHEN floor(months_between(current_date(), c.fecha_nacimiento) / 12) < 60 THEN '45-59'
            ELSE '60+' END                                              AS rango_edad,
       c.cod_provincia, c.nombre_provincia, c.region, c.ciudad,
       c.fecha_vinculacion,
       floor(months_between(current_date(), c.fecha_vinculacion) / 12) AS antiguedad_anios,
       c.email IS NOT NULL                                              AS tiene_email_valido,
       coalesce(q.num_productos_activos, 0) AS num_productos_activos,
       coalesce(q.num_productos_pasivo, 0)  AS num_productos_pasivo,
       coalesce(q.num_productos_activo, 0)  AS num_productos_activo,
       coalesce(q.saldo_pasivos, 0)         AS saldo_pasivos,
       coalesce(q.saldo_activos, 0)         AS saldo_activos,
       c.__START_AT                          AS version_desde
FROM workspace.clientes_pn_silver.clientes_pn_historico c
LEFT JOIN cuentas q ON q.cod_cliente = c.cod_cliente
WHERE c.__END_AT IS NULL;

CREATE OR REFRESH MATERIALIZED VIEW kpi_segmento_provincia (
  CONSTRAINT clientes_positivos EXPECT (num_clientes > 0) ON VIOLATION FAIL UPDATE
)
COMMENT 'Gold - KPIs por segmento y provincia (grano: segmento x provincia). num_clientes = count(cliente vigente); saldo_pasivos_total = sum(saldo_pasivos); saldo_pasivos_promedio = avg(saldo_pasivos); pct_con_credito = clientes con producto activo de tipo Activo / num_clientes.'
AS
SELECT cod_segmento, cod_provincia, nombre_provincia, region,
       count(*)                                         AS num_clientes,
       CAST(sum(saldo_pasivos) AS DECIMAL(18,2))        AS saldo_pasivos_total,
       CAST(avg(saldo_pasivos) AS DECIMAL(18,2))        AS saldo_pasivos_promedio,
       CAST(sum(saldo_activos) AS DECIMAL(18,2))        AS saldo_activos_total,
       round(avg(num_productos_activos), 2)             AS productos_promedio,
       round(count_if(num_productos_activo > 0) / count(*), 4) AS pct_con_credito
FROM cliente_360
GROUP BY cod_segmento, cod_provincia, nombre_provincia, region;

CREATE OR REFRESH MATERIALIZED VIEW kpi_movimientos_cartera (
  CONSTRAINT version_informada EXPECT (version_carga IS NOT NULL) ON VIOLATION FAIL UPDATE
)
COMMENT 'Gold - movimientos de la cartera de clientes por carga (altas, bajas y cambios), calculados desde el histórico SCD2 de Silver. Grano: una fila por version_carga.'
AS
WITH h AS (
  SELECT cod_cliente, __START_AT AS desde, __END_AT AS hasta,
         min(__START_AT) OVER (PARTITION BY cod_cliente)                     AS primera,
         lead(__START_AT) OVER (PARTITION BY cod_cliente ORDER BY __START_AT) AS siguiente
  FROM workspace.clientes_pn_silver.clientes_pn_historico),
versiones AS (SELECT desde AS version_carga FROM h UNION SELECT hasta FROM h WHERE hasta IS NOT NULL)
SELECT v.version_carga,
       count_if(h.desde <= v.version_carga AND (h.hasta IS NULL OR h.hasta > v.version_carga)) AS clientes_vigentes,
       count_if(h.desde = v.version_carga AND h.primera = v.version_carga)                     AS altas,
       count_if(h.desde = v.version_carga AND h.primera < v.version_carga)                     AS cambios,
       count_if(h.hasta = v.version_carga AND h.siguiente IS NULL)                             AS bajas
FROM versiones v CROSS JOIN h
GROUP BY v.version_carga;
