# Piloto: IA que genera modelos Silver y Gold desde Bronce (DEMO en workspace de prueba)

Demo funcional de la arquitectura de la guía de implementación v1.1, en un workspace **de prueba** de Databricks
(AWS, catálogo `workspace`). Dominio: **clientes personas naturales** (`clientes_pn`) de "el banco".
**Todos los datos son sintéticos**: identificaciones de 10 dígitos que empiezan con `00` (código de provincia
inexistente), correos `@ejemplo.test` y teléfonos `0990000xxx`.

## Qué hay en el workspace
| Capa | Objeto | Qué es |
| --- | --- | --- |
| Bronce | `workspace.bronce.clientes_pn_snapshot`, `workspace.bronce.cuentas_pn_snapshot` | 3 instantáneas completas (`version_carga` 1, 2 y 3) con altas, cambios y bajas |
| Referencia | `workspace.referencia.provincias`, `tipos_documento`, `segmentos`, `productos` | Catálogos gobernados |
| Estándares | `workspace.estandares.propuestas_modelo` | Propuestas JSON del agente IA (estado de revisión) |
| | `workspace.estandares.resultado_control_origen` | Evidencia de los controles de origen por capa |
| | `workspace.estandares.pipelines_por_capa` | Capa de cada pipeline (para el control de linaje) |
| Silver | `workspace.clientes_pn_silver.clientes_pn_historico` | SCD2 con `AUTO CDC FROM SNAPSHOT` (`__START_AT`/`__END_AT` = versión de carga) |
| | `clientes_pn_carga_validada`, `cuentas_pn`, `chk_clientes_pn_vigencias` | Última carga validada, cuentas vigentes, control SCD2 |
| Gold | `workspace.clientes_pn_gold.cliente_360`, `kpi_segmento_provincia`, `kpi_movimientos_cartera` | Vista 360, KPIs por segmento y provincia, altas/cambios/bajas por carga |

Código en el workspace: `/Workspace/Users/delacuadra.andres@gmail.com/piloto_ia_silver_gold/`
- Pipelines: `piloto_ia_silver_clientes_pn` y `piloto_ia_gold_clientes_pn` (serverless, Lakeflow Declarative Pipelines).
- Job: `piloto_ia_clientes_pn_orquestacion` = agente IA → Silver → Gold → control de reglas de origen.

## Reglas de origen por capa (obligatorias)
- **Silver** lee solo de `bronce`, otras `*_silver` y `referencia`. Nunca de la fuente ni de Gold.
- **Gold** lee solo de `*_silver` y `*_gold`. Nunca de `bronce` ni de `referencia`.
Definidas en `estandares/reglas_origen_capas.yml`; las aplican el agente (instrucciones + scorer con reintento),
el control estático (`tests/verificar_origen_capas.py`, con 4 casos negativos que deben fallar) y el control
de linaje (`tests/linaje_origen_capas.sql` sobre `system.access.table_lineage`).

## Cómo ejecutarlo
1. **Todo junto (recomendado):** en el workspace, Jobs & Pipelines → `piloto_ia_clientes_pn_orquestacion` → *Run now*.
2. **Paso a paso desde una terminal** (con `DATABRICKS_HOST` y `DATABRICKS_TOKEN` definidos y `pip install databricks-sdk pyyaml`):
   ```bash
   python bronce/generar_bronce_sintetico.py        # (re)crea Bronce y referencia — REEMPLAZA las tablas de Bronce
   python src/agente/agente_modelado.py             # agente IA: propuestas en estandares.propuestas_modelo y salidas/
   ./correr_pipeline.sh <id_pipeline_silver>        # Silver (SCD2 + expectations)
   ./correr_pipeline.sh <id_pipeline_gold>          # Gold
   python tests/verificar_origen_capas.py --propuestas   # control estático PASS/FAIL
   python dbsql.py tests/linaje_origen_capas.sql         # control de linaje en tablas de sistema (latencia ~10-20 min)
   python tests/linaje_api.py                            # mismo control vía API de linaje (sin latencia)
   ```
   Si se regenera Bronce, hacer *full refresh* del pipeline Silver (el SCD2 guarda la última versión procesada).
3. **Bundle (DAB):** `databricks bundle validate -t dev`. `deploy` crearía copias con prefijo de desarrollo; en el
   banco el despliegue a qa/prod va solo por GitHub Actions con aprobación.

## Estructura local
- `bronce/` generador de datos sintéticos y `eventos_esperados.csv`
- `estandares/` reglas de origen (YAML) y estándar de modelado
- `src/agente/` agente de modelado · `src/silver/` · `src/gold/` código de los pipelines
- `notebooks/` notebooks del job · `tests/` controles y casos negativos · `resources/` definiciones (JSON creadas, YAML del bundle)
- `salidas/` paquete de contexto, propuestas, revisión humana y resultados
- `dbsql.py`, `correr_pipeline.sh` utilidades locales

## Límites de la demo
- Workspace de prueba en AWS, no Azure; un solo catálogo (`workspace`) en vez de un catálogo por entorno.
- No se crearon etiquetas gobernadas, máscaras ABAC, MLflow tracing/evaluación, ni PR automática en GitHub.
- La propuesta del agente se revisó e implementó a mano (ver `salidas/revision_humana.md`): el agente no despliega.
