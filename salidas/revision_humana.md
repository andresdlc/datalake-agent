# Revisión humana de la propuesta del agente (DEMO)

Propuesta revisada: `20261110T220949-7eaff2` (modelo `databricks-gpt-oss-120b`), estado `IMPLEMENTADA_CON_AJUSTES`.
Una primera corrida con `databricks-meta-llama-3-3-70b-instruct` produjo un modelo pobre (una sola tabla Silver con
`SELECT *`): quedó como `DESCARTADA`. Una tercera corrida (job de orquestación) quedó `PENDIENTE_REVISION`.

## Lo que se aceptó tal cual
- Tablas Silver `clientes_pn_historico` (SCD2 desde instantáneas, clave `cod_cliente`) y `cuentas_pn` (vigente de la última carga).
- Homologación con `referencia.tipos_documento`, `referencia.provincias`, `referencia.segmentos`, `referencia.productos`.
- Gold `cliente_360` (un registro por cliente vigente) y `kpi_segmento_provincia` (segmento x provincia), leyendo solo Silver/Gold.
- Clasificación de columnas por `sensibilidad_pii`.

## Ajustes del revisor
| Hallazgo en la propuesta | Ajuste implementado |
| --- | --- |
| `fecha_vinculacion` y `fecha_apertura` parseadas como `dd/MM/yyyy` (en Bronce vienen `yyyy-MM-dd`) | Formato corregido |
| El hash de atributos incluía solo 5 columnas (no detectaba cambios de correo, dirección o estado civil) | Hash y `track_history` sobre los 13 atributos de negocio |
| El SQL incluía `__START_AT` / `__END_AT` calculados a mano | Se dejan a `AUTO CDC FROM SNAPSHOT` |
| Expectations con subconsultas (`IN (SELECT ...)`), no soportadas | Reemplazadas por banderas de homologación (`... IS NOT NULL` tras el LEFT JOIN) |
| Expectations sobre la tabla SCD2 | No soportadas con `FROM SNAPSHOT`: se movieron a `clientes_pn_carga_validada` y `chk_clientes_pn_vigencias` |
| Gold filtraba `estado = 'ACTIVO'` en el WHERE de un LEFT JOIN (perdía clientes sin cuentas; Silver usa 'A') | Silver homologa a `ACTIVA`/`INACTIVA`; Gold agrega cuentas activas en una CTE antes del LEFT JOIN |
| Gold exponía `fecha_vinculacion` sin derivados y no separaba pasivos/activos | Se agregan edad, rango de edad, antigüedad, saldos pasivos/activos y número de productos; sin nombres, documento, correo, teléfono ni dirección |
| Sin indicador de movimientos de cartera | Se agrega `kpi_movimientos_cartera` (altas, cambios, bajas por carga) desde el histórico SCD2 |
