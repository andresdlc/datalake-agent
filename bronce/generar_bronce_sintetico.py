"""Genera datos SINTÉTICOS (ficticios) de clientes personas naturales y sus cuentas, en 3 cargas
(instantáneas completas) de Bronce, más tablas de referencia. Ningún dato corresponde a personas reales.
- Identificaciones: 10 dígitos que empiezan con '00' (código de provincia inexistente) => claramente ficticias.
- Correos: dominio reservado @ejemplo.test. Teléfonos: prefijo 0990000.
Uso: python bronce/generar_bronce_sintetico.py  (requiere DATABRICKS_HOST / DATABRICKS_TOKEN)
"""
import random, datetime, sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from dbsql import sql

CAT = "workspace"
random.seed(2026)
NOMBRES_M = ["Juan","Carlos","Luis","José","Andrés","Diego","Jorge","Miguel","Pedro","Santiago","Mateo","Daniel","Fernando","Ricardo","Pablo"]
NOMBRES_F = ["María","Ana","Gabriela","Daniela","Carolina","Paola","Andrea","Valeria","Lucía","Fernanda","Sofía","Camila","Verónica","Patricia","Diana"]
APELLIDOS = ["Pérez","González","Rodríguez","Sánchez","Torres","Morales","Castro","Vera","Zambrano","Mendoza","Cedeño","Vásquez","Ortiz","Herrera","Jaramillo","Salazar","Rivera","Mora","Andrade","Paredes"]
PROV = [("01","Azuay","Sierra","Cuenca"),("02","Bolívar","Sierra","Guaranda"),("03","Cañar","Sierra","Azogues"),("04","Carchi","Sierra","Tulcán"),
        ("05","Cotopaxi","Sierra","Latacunga"),("06","Chimborazo","Sierra","Riobamba"),("07","El Oro","Costa","Machala"),("08","Esmeraldas","Costa","Esmeraldas"),
        ("09","Guayas","Costa","Guayaquil"),("10","Imbabura","Sierra","Ibarra"),("11","Loja","Sierra","Loja"),("12","Los Ríos","Costa","Babahoyo"),
        ("13","Manabí","Costa","Portoviejo"),("14","Morona Santiago","Amazonía","Macas"),("15","Napo","Amazonía","Tena"),("16","Pastaza","Amazonía","Puyo"),
        ("17","Pichincha","Sierra","Quito"),("18","Tungurahua","Sierra","Ambato"),("19","Zamora Chinchipe","Amazonía","Zamora"),("20","Galápagos","Insular","Puerto Ayora"),
        ("21","Sucumbíos","Amazonía","Nueva Loja"),("22","Orellana","Amazonía","Francisco de Orellana"),("23","Santo Domingo de los Tsáchilas","Costa","Santo Domingo"),("24","Santa Elena","Costa","Santa Elena")]
PESO_PROV = {"09":30,"17":25,"13":8,"01":6,"07":5,"18":4,"23":4,"12":4}
SEGMENTOS = ["MASIVO"]*6 + ["PREFERENTE"]*3 + ["PREMIUM"]
CALLES = ["Av. Siempre Viva","Calle Ficticia","Av. de Prueba","Calle Ejemplo","Pasaje Demo"]
PRODUCTOS = [("AHO","Cuenta de ahorros","Pasivo"),("CTE","Cuenta corriente","Pasivo"),("PLZ","Depósito a plazo","Pasivo"),("TC","Tarjeta de crédito","Activo"),("CON","Crédito de consumo","Activo")]

def q(v):
    return "NULL" if v is None else ("'" + str(v).replace("'", "''") + "'")

def prov_aleatoria():
    cods = [p[0] for p in PROV]; pesos = [PESO_PROV.get(c, 1) for c in cods]
    return random.choices(PROV, weights=pesos)[0]

def nuevo_cliente(i):
    f = random.random() < 0.5
    nombre = random.choice(NOMBRES_F if f else NOMBRES_M) + " " + random.choice(NOMBRES_F if f else NOMBRES_M)
    p = prov_aleatoria()
    nac = datetime.date(1950,1,1) + datetime.timedelta(days=random.randint(0, 365*55))
    vinc = datetime.date(2005,1,1) + datetime.timedelta(days=random.randint(0, 365*20))
    seg = random.choice(SEGMENTOS)
    c = {"cod_cliente": f"CL{i:06d}", "tipo_identificacion": random.choices(["CED","cedula ","PAS"], [85,10,5])[0],
         "num_identificacion": "00" + "".join(random.choice("0123456789") for _ in range(8)),
         "nombres": nombre, "apellidos": random.choice(APELLIDOS) + " " + random.choice(APELLIDOS),
         "fecha_nacimiento": nac.strftime("%d/%m/%Y"), "genero": "F" if f else "M",
         "estado_civil": random.choice(["SOLTERO","CASADO","DIVORCIADO","UNION LIBRE","VIUDO"]),
         "email": f"cliente{i}@ejemplo.test", "telefono_movil": f"0990000{i % 1000:03d}",
         "cod_provincia": p[0], "ciudad": p[3], "direccion": f"{random.choice(CALLES)} N{random.randint(1,99)}-{random.randint(1,999)}",
         "segmento": random.choice([seg, seg.lower(), " " + seg]), "fecha_vinculacion": vinc.isoformat()}
    # Defectos de calidad típicos de Bronce
    r = random.random()
    if r < 0.02: c["email"] = "sin-correo"
    elif r < 0.04: c["fecha_nacimiento"] = None
    return c

def cuentas_de(cli, n0):
    res = []
    for k in range(random.choices([1,2,3,4],[40,35,18,7])[0]):
        prod = random.choices(PRODUCTOS, [45,15,10,20,10])[0][0]
        saldo = round(random.lognormvariate(7, 1.3), 2)
        res.append({"num_cuenta": f"CT{n0+k:08d}", "cod_cliente": cli, "cod_producto": prod, "estado": "A",
                    "saldo": f"{saldo:.2f}", "fecha_apertura": (datetime.date(2010,1,1)+datetime.timedelta(days=random.randint(0,5400))).isoformat()})
    return res

# --- Carga 1 ---
clientes = {}; cuentas = {}
for i in range(1, 201):
    c = nuevo_cliente(i); clientes[c["cod_cliente"]] = c
    for a in cuentas_de(c["cod_cliente"], i*10): cuentas[a["num_cuenta"]] = a
cargas = {1: (datetime.date(2026,9,30), {k: dict(v) for k,v in clientes.items()}, {k: dict(v) for k,v in cuentas.items()})}
siguiente = 201
eventos = []
for version, fecha, n_cambios, n_altas, n_bajas in [(2, datetime.date(2026,10,31), 20, 10, 2), (3, datetime.date(2026,11,9), 15, 6, 1)]:
    ids = list(clientes)
    for cid in random.sample(ids, n_cambios):
        c = clientes[cid]; tipo = random.choice(["segmento","direccion","email","estado_civil"])
        if tipo == "segmento": c["segmento"] = random.choice(["MASIVO","PREFERENTE","PREMIUM"])
        elif tipo == "direccion":
            p = prov_aleatoria(); c["cod_provincia"], c["ciudad"] = p[0], p[3]
            c["direccion"] = f"{random.choice(CALLES)} N{random.randint(1,99)}-{random.randint(1,999)}"
        elif tipo == "email": c["email"] = f"cliente{cid[2:].lstrip('0')}.nuevo{version}@ejemplo.test"
        else: c["estado_civil"] = random.choice(["SOLTERO","CASADO","DIVORCIADO","UNION LIBRE","VIUDO"])
        eventos.append((version, "cambio", cid, tipo))
    for cid in random.sample([i for i in ids], n_bajas):
        del clientes[cid]; eventos.append((version, "baja", cid, ""))
        for k in [k for k,a in cuentas.items() if a["cod_cliente"] == cid]: cuentas[k]["estado"] = "I"
    for _ in range(n_altas):
        c = nuevo_cliente(siguiente); clientes[c["cod_cliente"]] = c; eventos.append((version, "alta", c["cod_cliente"], ""))
        for a in cuentas_de(c["cod_cliente"], siguiente*10): cuentas[a["num_cuenta"]] = a
        siguiente += 1
    for a in cuentas.values():
        if a["estado"] == "A": a["saldo"] = f"{max(0.0, float(a['saldo']) * random.uniform(0.85, 1.2)):.2f}"
    cargas[version] = (fecha, {k: dict(v) for k,v in clientes.items()}, {k: dict(v) for k,v in cuentas.items()})

# --- DDL ---
for s, com in [("bronce","Capa Bronce: dato crudo tal como llega de la fuente (DEMO, datos sintéticos)"),
               ("referencia","Datos de referencia/maestros gobernados (DEMO)"),
               ("estandares","Estándares, reglas de origen por capa y propuestas del agente de modelado (DEMO)"),
               ("clientes_pn_silver","Capa Silver del dominio clientes personas naturales (DEMO)"),
               ("clientes_pn_gold","Capa Gold del dominio clientes personas naturales (DEMO)")]:
    sql(f"CREATE SCHEMA IF NOT EXISTS {CAT}.{s} COMMENT {q(com)}")

COLS_CLI = ["cod_cliente","tipo_identificacion","num_identificacion","nombres","apellidos","fecha_nacimiento","genero","estado_civil","email","telefono_movil","cod_provincia","ciudad","direccion","segmento","fecha_vinculacion"]
COLS_CTA = ["num_cuenta","cod_cliente","cod_producto","estado","saldo","fecha_apertura"]
sql(f"""CREATE OR REPLACE TABLE {CAT}.bronce.clientes_pn_snapshot (
 {", ".join(c + " STRING" for c in COLS_CLI)}, version_carga INT, fecha_carga DATE)
COMMENT 'Bronce - instantáneas completas de clientes personas naturales tal como llegan del core (DATOS SINTÉTICOS DE DEMO). Una carga por version_carga.'""")
sql(f"""CREATE OR REPLACE TABLE {CAT}.bronce.cuentas_pn_snapshot (
 {", ".join(c + " STRING" for c in COLS_CTA)}, version_carga INT, fecha_carga DATE)
COMMENT 'Bronce - instantáneas completas de cuentas/productos de clientes personas naturales (DATOS SINTÉTICOS DE DEMO).'""")

def insertar(tabla, cols, filas):
    for i in range(0, len(filas), 300):
        vals = ",\n".join("(" + ", ".join(f) + ")" for f in filas[i:i+300])
        sql(f"INSERT INTO {CAT}.bronce.{tabla} ({', '.join(cols)}, version_carga, fecha_carga) VALUES\n{vals}", show=False)

for v, (fecha, cl, ct) in cargas.items():
    insertar("clientes_pn_snapshot", COLS_CLI, [[q(c[k]) for k in COLS_CLI] + [str(v), f"DATE'{fecha}'"] for c in cl.values()])
    insertar("cuentas_pn_snapshot", COLS_CTA, [[q(a[k]) for k in COLS_CTA] + [str(v), f"DATE'{fecha}'"] for a in ct.values()])
    print(f"carga {v} ({fecha}): {len(cl)} clientes, {len(ct)} cuentas")

# --- Referencia ---
sql(f"CREATE OR REPLACE TABLE {CAT}.referencia.provincias (cod_provincia STRING COMMENT 'Código INEC de provincia', nombre_provincia STRING, region STRING) COMMENT 'Catálogo de provincias del Ecuador (dato público de referencia)'")
sql(f"INSERT INTO {CAT}.referencia.provincias VALUES " + ",".join(f"({q(p[0])},{q(p[1])},{q(p[2])})" for p in PROV))
sql(f"CREATE OR REPLACE TABLE {CAT}.referencia.tipos_documento (cod_tipo_documento STRING, descripcion STRING, valores_origen ARRAY<STRING>) COMMENT 'Catálogo de tipos de documento de identidad de personas naturales y su homologación desde los códigos de origen'")
sql(f"""INSERT INTO {CAT}.referencia.tipos_documento VALUES ('CEDULA','Cédula de ciudadanía', array('CED','CEDULA','C')),('PASAPORTE','Pasaporte', array('PAS','PASAPORTE','P'))""")
sql(f"CREATE OR REPLACE TABLE {CAT}.referencia.segmentos (cod_segmento STRING, descripcion STRING, orden INT) COMMENT 'Catálogo de segmentos comerciales de personas naturales'")
sql(f"INSERT INTO {CAT}.referencia.segmentos VALUES ('MASIVO','Segmento masivo',1),('PREFERENTE','Segmento preferente',2),('PREMIUM','Segmento premium',3)")
sql(f"CREATE OR REPLACE TABLE {CAT}.referencia.productos (cod_producto STRING, nombre_producto STRING, tipo_balance STRING) COMMENT 'Catálogo de productos (pasivo/activo)'")
sql(f"INSERT INTO {CAT}.referencia.productos VALUES " + ",".join(f"({q(a)},{q(b)},{q(c)})" for a,b,c in PRODUCTOS))

with open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "eventos_esperados.csv"), "w", encoding="utf-8") as f:
    f.write("version_carga,evento,cod_cliente,atributo\n")
    for e in eventos: f.write(",".join(map(str, e)) + "\n")
print("Eventos esperados:", {t: sum(1 for e in eventos if e[1]==t) for t in ("alta","cambio","baja")})
