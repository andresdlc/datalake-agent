# Pipeline Silver — dominio clientes personas naturales (DEMO)
# Implementación revisada por un humano a partir de la propuesta del agente de modelado
# (workspace.estandares.propuestas_modelo, capa = 'silver'). Ver salidas/revision_humana.md.
#
# REGLA DE ORIGEN: este archivo solo lee `bronce.*` y `referencia.*` (y tablas Silver del propio pipeline).
from pyspark import pipelines as dp
from pyspark.sql import functions as F

CAT = spark.conf.get("catalogo", "workspace")
BRONCE_CLIENTES = f"{CAT}.bronce.clientes_pn_snapshot"
BRONCE_CUENTAS = f"{CAT}.bronce.cuentas_pn_snapshot"
REF_TIPOS_DOC = f"{CAT}.referencia.tipos_documento"
REF_PROVINCIAS = f"{CAT}.referencia.provincias"
REF_SEGMENTOS = f"{CAT}.referencia.segmentos"
REF_PRODUCTOS = f"{CAT}.referencia.productos"

ATRIBUTOS_RASTREADOS = ["cod_tipo_documento", "num_identificacion", "nombres", "apellidos", "fecha_nacimiento", "genero",
                        "estado_civil", "email", "telefono_movil", "cod_provincia", "ciudad", "direccion", "cod_segmento"]

def clientes_estandarizados(df_bronce):
    """Estandariza una instantánea de clientes de Bronce y la homologa con referencia."""
    td = spark.read.table(REF_TIPOS_DOC).select("cod_tipo_documento", F.explode("valores_origen").alias("valor_origen"))
    pv = spark.read.table(REF_PROVINCIAS).select("cod_provincia", "nombre_provincia", "region")
    sg = spark.read.table(REF_SEGMENTOS).select(F.col("cod_segmento").alias("_seg_ref"))
    c = (df_bronce
         .withColumn("_tipo", F.upper(F.trim("tipo_identificacion")))
         .withColumn("_seg", F.upper(F.trim("segmento"))))
    out = (c.join(td, c["_tipo"] == td["valor_origen"], "left")
            .join(pv, "cod_provincia", "left")
            .join(sg, c["_seg"] == sg["_seg_ref"], "left")
            .select(
                F.trim("cod_cliente").alias("cod_cliente"),
                F.col("cod_tipo_documento"),
                F.trim("num_identificacion").alias("num_identificacion"),
                F.initcap(F.trim("nombres")).alias("nombres"),
                F.initcap(F.trim("apellidos")).alias("apellidos"),
                F.to_date("fecha_nacimiento", "dd/MM/yyyy").alias("fecha_nacimiento"),
                F.upper(F.trim("genero")).alias("genero"),
                F.upper(F.trim("estado_civil")).alias("estado_civil"),
                F.when(F.lower(F.trim("email")).rlike(r"^[^@\s]+@[^@\s]+\.[a-z]+$"), F.lower(F.trim("email"))).alias("email"),
                F.trim("telefono_movil").alias("telefono_movil"),
                F.col("cod_provincia"), F.col("nombre_provincia"), F.col("region"),
                F.initcap(F.trim("ciudad")).alias("ciudad"),
                F.trim("direccion").alias("direccion"),
                F.col("_seg_ref").alias("cod_segmento"),
                F.to_date("fecha_vinculacion", "yyyy-MM-dd").alias("fecha_vinculacion"),
                F.col("version_carga"), F.col("fecha_carga")))
    return out.withColumn("hash_atributos", F.sha2(F.concat_ws("||", *[F.coalesce(F.col(a).cast("string"), F.lit("")) for a in ATRIBUTOS_RASTREADOS]), 256))

# ---------------------------------------------------------------- 1. Calidad de la última carga
@dp.materialized_view(
    name="clientes_pn_carga_validada",
    comment="Silver - última instantánea de clientes personas naturales estandarizada y validada (control de calidad previo al SCD2).")
@dp.expect_or_fail("clave_no_nula", "cod_cliente IS NOT NULL")
@dp.expect("tipo_documento_homologado", "cod_tipo_documento IS NOT NULL")
@dp.expect("segmento_homologado", "cod_segmento IS NOT NULL")
@dp.expect("provincia_homologada", "nombre_provincia IS NOT NULL")
@dp.expect("email_formato_valido", "email IS NOT NULL")
@dp.expect("fecha_nacimiento_informada", "fecha_nacimiento IS NOT NULL")
@dp.expect("fecha_vinculacion_valida", "fecha_vinculacion <= current_date()")
def clientes_pn_carga_validada():
    b = spark.read.table(BRONCE_CLIENTES)
    ultima = b.agg(F.max("version_carga")).first()[0]
    return clientes_estandarizados(b.filter(F.col("version_carga") == ultima))

# ---------------------------------------------------------------- 2. Histórico SCD2 desde instantáneas
def siguiente_instantanea(ultima_version):
    """Devuelve (DataFrame, version) de la siguiente carga de Bronce no procesada, o None si está al día."""
    versiones = sorted(r[0] for r in spark.read.table(BRONCE_CLIENTES).select("version_carga").distinct().collect())
    pendientes = [v for v in versiones if ultima_version is None or v > ultima_version]
    if not pendientes:
        return None
    v = pendientes[0]
    return (clientes_estandarizados(spark.read.table(BRONCE_CLIENTES).filter(F.col("version_carga") == v)), v)

dp.create_streaming_table(
    name="clientes_pn_historico",
    comment="Silver SCD2 - clientes personas naturales desde instantáneas completas de Bronce. __START_AT/__END_AT = version_carga; vigente: __END_AT IS NULL. Un cliente ausente en una carga queda cerrado (baja).",
)
# Nota: AUTO CDC FROM SNAPSHOT no admite expectations en la tabla destino; la calidad se controla en
# clientes_pn_carga_validada (antes) y en chk_clientes_pn_vigencias (después).
dp.create_auto_cdc_from_snapshot_flow(
    target="clientes_pn_historico",
    source=siguiente_instantanea,
    keys=["cod_cliente"],
    stored_as_scd_type=2,
    track_history_column_list=ATRIBUTOS_RASTREADOS,
)

# ---------------------------------------------------------------- 3. Cuentas vigentes (última carga)
@dp.materialized_view(
    name="cuentas_pn",
    comment="Silver - cuentas y productos de clientes personas naturales según la última instantánea de Bronce, homologados con referencia.productos.")
@dp.expect_or_fail("clave_no_nula", "num_cuenta IS NOT NULL AND cod_cliente IS NOT NULL")
@dp.expect_or_drop("saldo_valido", "saldo IS NOT NULL AND saldo >= 0")
@dp.expect("producto_homologado", "nombre_producto IS NOT NULL")
@dp.expect("estado_valido", "estado IN ('ACTIVA', 'INACTIVA')")
def cuentas_pn():
    b = spark.read.table(BRONCE_CUENTAS)
    ultima = b.agg(F.max("version_carga")).first()[0]
    pr = spark.read.table(REF_PRODUCTOS)
    return (b.filter(F.col("version_carga") == ultima).join(pr, "cod_producto", "left")
             .select(F.trim("num_cuenta").alias("num_cuenta"), F.trim("cod_cliente").alias("cod_cliente"),
                     "cod_producto", "nombre_producto", "tipo_balance",
                     F.when(F.upper(F.trim("estado")) == "A", "ACTIVA").when(F.upper(F.trim("estado")) == "I", "INACTIVA").alias("estado"),
                     F.expr("try_cast(replace(saldo, ',', '.') AS DECIMAL(18,2))").alias("saldo"),
                     F.to_date("fecha_apertura", "yyyy-MM-dd").alias("fecha_apertura"),
                     "version_carga", "fecha_carga"))

# ---------------------------------------------------------------- 4. Control de consistencia SCD2
@dp.materialized_view(
    name="chk_clientes_pn_vigencias",
    comment="Silver - control: como máximo una versión vigente por cliente y vigencias sin traslape.")
@dp.expect_or_fail("clave_no_nula", "cod_cliente IS NOT NULL")
@dp.expect_or_fail("una_vigente_por_cliente", "versiones_vigentes <= 1")
@dp.expect_or_fail("vigencia_coherente", "vigencias_invertidas = 0")
def chk_clientes_pn_vigencias():
    h = spark.read.table("clientes_pn_historico")
    return h.groupBy("cod_cliente").agg(
        F.count("*").alias("versiones"),
        F.sum(F.when(F.col("__END_AT").isNull(), 1).otherwise(0)).alias("versiones_vigentes"),
        F.sum(F.when(F.col("__END_AT") <= F.col("__START_AT"), 1).otherwise(0)).alias("vigencias_invertidas"))
