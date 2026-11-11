# Estándar de modelado (DEMO) — dominio clientes personas naturales (clientes_pn)

## Nombres
- `snake_case`, en español, sin tildes ni ñ en identificadores.
- Esquemas: `bronce`, `referencia`, `<dominio>_silver`, `<dominio>_gold`.
- Silver: `<entidad>_historico` (SCD2), `<entidad>` (vigente/SCD1), `chk_<control>` (controles).
- Gold: `dim_<entidad>`, `fact_<hecho>`, `<producto>_360`, `kpi_<tema>`.

## Silver
- Tipos estándar: fechas `DATE`, importes `DECIMAL(18,2)`, códigos `STRING` en mayúsculas sin espacios.
- Homologar códigos con `referencia.*` (tipos de documento, segmentos, provincias, productos).
- Histórico SCD2 desde instantáneas completas de Bronce con `AUTO CDC FROM SNAPSHOT` (las claves ausentes
  en una carga se cierran como bajas). Columnas de vigencia `__START_AT` / `__END_AT`.
- Expectations: FAIL para clave nula; DROP para registros inutilizables; WARN para calidad mejorable.
- Comentario en tabla y columnas; etiqueta `sensibilidad_pii` en cada columna
  (`identificador`, `contacto`, `financiero`, `ninguna`).

## Gold
- Grano explícito por tabla; KPIs documentados (fórmula, fuente Silver).
- Solo lee Silver u otras Gold (ver `reglas_origen_capas.yml`).
