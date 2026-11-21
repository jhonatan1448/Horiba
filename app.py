"""
Sistema de Análisis y Registro - HORIBA LAQUAtwin
Monitoreo de pH, CE, NO3, K, Ca y Na en Agua de Riego, Solución de Suelo y Savia (ECP).

Ejecutar localmente:   streamlit run app.py
Desplegar:             Streamlit Community Cloud (share.streamlit.io) apuntando a este repo.
"""
import io
import re
from datetime import date
from pathlib import Path

import pandas as pd
import plotly.express as px
import streamlit as st

# ==========================================
# CONFIGURACIÓN
# ==========================================
st.set_page_config(page_title="Monitoreo Agrícola - HORIBA LAQUAtwin", page_icon="🌱", layout="wide")

BASE_DIR = Path(__file__).parent
DB_FILE = BASE_DIR / "datos_horiba_tomate.csv"
RANGOS_FILE = BASE_DIR / "rangos_referencia.csv"

MATRICES = ["Agua de Riego", "Solución de Suelo", "Savia (ECP)"]
ETAPAS = ["Todas", "Inicial / Enraizamiento", "Vegetativa / Desarrollo", "Productiva / Llenado"]
COLUMNAS_DATOS = ["Fecha", "Lote", "Matriz", "Etapa", "pH", "EC_dS_m",
                  "NO3_ppm", "K_ppm", "Ca_ppm", "Na_ppm", "Notas"]

# Parámetro del histórico -> (columna en tabla de rangos, etiqueta para mostrar)
PARAMETROS = {
    "pH": ("pH Óptimo", "pH"),
    "EC_dS_m": ("CE (dS/m)", "CE (dS/m)"),
    "NO3_ppm": ("Nitrato (NO3⁻) ppm", "Nitrato NO3⁻ (ppm)"),
    "K_ppm": ("Potasio (K⁺) ppm", "Potasio K⁺ (ppm)"),
    "Ca_ppm": ("Calcio (Ca²⁺) ppm", "Calcio Ca²⁺ (ppm)"),
    "Na_ppm": ("Sodio (Na⁺) ppm", "Sodio Na⁺ (ppm)"),
}

# Iones para el gráfico de torta
IONES = {"Ca_ppm": "Calcio (Ca²⁺)", "K_ppm": "Potasio (K⁺)", "Na_ppm": "Sodio (Na⁺)", "NO3_ppm": "Nitrato (NO3⁻)"}
# Peso equivalente (g/eq) = masa molar / carga  ->  meq/L = ppm / peso equivalente
PESO_EQUIVALENTE = {"Ca_ppm": 20.04, "K_ppm": 39.10, "Na_ppm": 22.99, "NO3_ppm": 62.00}
COLORES_IONES = {"Calcio (Ca²⁺)": "#4C78A8", "Potasio (K⁺)": "#F58518",
                 "Sodio (Na⁺)": "#E45756", "Nitrato (NO3⁻)": "#54A24B"}

RANGOS_INICIALES = pd.DataFrame({
    "Matriz / Recurso": ["Agua de Riego", "Solución de Suelo", "Savia (ECP)", "Savia (ECP)", "Savia (ECP)"],
    "Etapa Fenológica": ["Todas", "Todas", "Inicial / Enraizamiento", "Vegetativa / Desarrollo", "Productiva / Llenado"],
    "pH Óptimo": ["5.5 - 6.5", "5.8 - 6.8", "5.4 - 6.0", "5.4 - 6.2", "5.6 - 6.2"],
    "CE (dS/m)": ["< 1.0", "1.5 - 2.5", "12 - 15", "12 - 15", "12 - 15"],
    "Nitrato (NO3⁻) ppm": ["10 - 50", "100 - 200", "4000 - 5000", "3000 - 3500", "2500 - 3500"],
    "Potasio (K⁺) ppm": ["10 - 30", "150 - 250", "2000 - 2500", "6000 - 8000", "3500 - 5000"],
    "Calcio (Ca²⁺) ppm": ["40 - 80", "100 - 180", "1500 - 2000", "1000 - 1500", "1000 - 1500"],
    # Sodio: se evalúa como máximo tolerable (no hay mínimo). Ajusta según tu criterio.
    "Sodio (Na⁺) ppm": ["< 50", "< 100", "< 200", "< 200", "< 200"],
})


# ==========================================
# FUNCIONES DE DATOS
# ==========================================
def normalizar_datos(df: pd.DataFrame) -> pd.DataFrame:
    """Garantiza columnas y tipos correctos (también para CSV antiguos o importados)."""
    df = df.copy()
    for col in COLUMNAS_DATOS:
        if col not in df.columns:
            df[col] = "Todas" if col == "Etapa" else None
    df = df[COLUMNAS_DATOS]
    df["Fecha"] = pd.to_datetime(df["Fecha"], errors="coerce")
    for col in PARAMETROS:
        df[col] = pd.to_numeric(df[col], errors="coerce")
    for col in ["Lote", "Matriz", "Etapa", "Notas"]:
        df[col] = df[col].fillna("").astype(str)
    return df.dropna(subset=["Fecha"]).reset_index(drop=True)


# ------------------------------------------
# ALMACENAMIENTO: Google Sheets (permanente) o CSV local (respaldo)
# ------------------------------------------
# Si en los "Secrets" de Streamlit existen [gcp_service_account] y spreadsheet = "...",
# los datos se guardan en Google Sheets. Si no, se usan archivos CSV locales.
HOJA_DATOS, HOJA_RANGOS = "datos", "rangos"


def sheets_configurado() -> bool:
    try:
        return "gcp_service_account" in st.secrets and "spreadsheet" in st.secrets
    except Exception:          # no existe secrets.toml
        return False


@st.cache_resource(show_spinner=False)
def abrir_libro():
    import gspread
    cliente = gspread.service_account_from_dict(dict(st.secrets["gcp_service_account"]))
    ref = str(st.secrets["spreadsheet"]).strip()
    return cliente.open_by_url(ref) if ref.startswith("http") else cliente.open_by_key(ref)


def obtener_hoja(nombre: str):
    import gspread
    libro = abrir_libro()
    try:
        return libro.worksheet(nombre)
    except gspread.WorksheetNotFound:
        return libro.add_worksheet(title=nombre, rows=1000, cols=20)


@st.cache_data(ttl=600, show_spinner="Leyendo Google Sheets…")
def leer_hoja(nombre: str) -> pd.DataFrame:
    valores = obtener_hoja(nombre).get_all_values(value_render_option="UNFORMATTED_VALUE")
    if not valores or not valores[0] or not any(valores[0]):
        return pd.DataFrame()
    return pd.DataFrame(valores[1:], columns=valores[0]).replace("", None)


def escribir_hoja(nombre: str, df: pd.DataFrame) -> None:
    df = df.copy()
    for col in df.columns:
        if pd.api.types.is_datetime64_any_dtype(df[col]):
            df[col] = df[col].dt.strftime("%Y-%m-%d")
    filas = df.astype(object).where(df.notna(), "").values.tolist()
    hoja = obtener_hoja(nombre)
    hoja.clear()
    hoja.update(values=[list(df.columns)] + filas, range_name="A1", value_input_option="RAW")
    leer_hoja.clear()


USAR_SHEETS = sheets_configurado()
ERROR_SHEETS = None
if USAR_SHEETS:
    try:
        abrir_libro()
    except Exception as e:  # credenciales o permisos incorrectos
        USAR_SHEETS, ERROR_SHEETS = False, e


def cargar_datos() -> pd.DataFrame:
    if USAR_SHEETS:
        df = leer_hoja(HOJA_DATOS)
    else:
        df = pd.read_csv(DB_FILE) if DB_FILE.exists() else pd.DataFrame()
    return normalizar_datos(df if not df.empty else pd.DataFrame(columns=COLUMNAS_DATOS))


def guardar_datos(df: pd.DataFrame) -> None:
    df = normalizar_datos(df)
    if USAR_SHEETS:
        escribir_hoja(HOJA_DATOS, df)
    else:
        df.to_csv(DB_FILE, index=False)


def cargar_rangos() -> pd.DataFrame:
    if USAR_SHEETS:
        df = leer_hoja(HOJA_RANGOS)
    else:
        df = pd.read_csv(RANGOS_FILE, dtype=str) if RANGOS_FILE.exists() else pd.DataFrame()
    # Si no existe o es de una versión anterior (p. ej. sin columna de Sodio), se usan los valores por defecto.
    if not df.empty and list(df.columns) == list(RANGOS_INICIALES.columns):
        return df.astype(str).replace({"None": "-", "nan": "-"})
    guardar_rangos(RANGOS_INICIALES)
    return RANGOS_INICIALES.copy()


def guardar_rangos(df: pd.DataFrame) -> None:
    df = df.fillna("-").astype(str)
    if USAR_SHEETS:
        escribir_hoja(HOJA_RANGOS, df)
    else:
        df.to_csv(RANGOS_FILE, index=False)


def parsear_rango(texto) -> tuple:
    """Convierte '5.5 - 6.5', '< 1.0', '> 2', '-' en (mín, máx). None = sin límite."""
    if texto is None or pd.isna(texto):
        return None, None
    t = str(texto).strip().replace(",", ".")
    nums = [float(n) for n in re.findall(r"\d+(?:\.\d+)?", t)]
    if not nums:
        return None, None
    if t.startswith("<"):
        return None, nums[0]
    if t.startswith(">"):
        return nums[0], None
    if len(nums) >= 2:
        return min(nums[0], nums[1]), max(nums[0], nums[1])
    return nums[0], nums[0]


def buscar_rango(df_rangos: pd.DataFrame, matriz: str, etapa: str, parametro: str) -> tuple:
    """Busca el rango para matriz+etapa; si no existe, usa la fila 'Todas' de esa matriz."""
    col = PARAMETROS[parametro][0]
    if col is None or col not in df_rangos.columns:
        return None, None
    filas = df_rangos[df_rangos["Matriz / Recurso"] == matriz]
    fila = filas[filas["Etapa Fenológica"] == etapa]
    if fila.empty:
        fila = filas[filas["Etapa Fenológica"] == "Todas"]
    if fila.empty:
        return None, None
    return parsear_rango(fila.iloc[0][col])


def evaluar(valor, minimo, maximo) -> str:
    if valor is None or pd.isna(valor) or (minimo is None and maximo is None):
        return "⚪ Sin rango"
    if minimo is not None and valor < minimo:
        return "🔵 Bajo"
    if maximo is not None and valor > maximo:
        return "🔴 Alto"
    return "🟢 Óptimo"


def tabla_diagnostico(muestra: pd.Series, df_rangos: pd.DataFrame) -> pd.DataFrame:
    filas = []
    for param, (_, etiqueta) in PARAMETROS.items():
        mn, mx = buscar_rango(df_rangos, muestra["Matriz"], muestra["Etapa"], param)
        if mn is None and mx is None:
            rango_txt = "-"
        elif mn is None:
            rango_txt = f"< {mx:g}"
        elif mx is None:
            rango_txt = f"> {mn:g}"
        else:
            rango_txt = f"{mn:g} - {mx:g}"
        filas.append({"Parámetro": etiqueta, "Medido": muestra[param],
                      "Rango": rango_txt, "Estado": evaluar(muestra[param], mn, mx)})
    return pd.DataFrame(filas)


def a_excel(hojas: dict) -> bytes:
    buffer = io.BytesIO()
    with pd.ExcelWriter(buffer, engine="openpyxl") as writer:
        for nombre, df in hojas.items():
            df.to_excel(writer, index=False, sheet_name=nombre[:31])
    return buffer.getvalue()


# ==========================================
# MOTOR DE INTERPRETACIÓN (lenguaje sencillo)
# ==========================================
# MENSAJES[parámetro][grupo de matriz][estado] = (qué significa, qué hacer)
# grupo: "agua", "suelo", "savia". Estado: "Bajo" / "Alto".
MENSAJES = {
    "pH": {
        "agua": {
            "Bajo": ("El agua está más ácida de lo recomendado.",
                     "Revisa la dosis de ácido si estás acidificando el agua; puede corroer equipos y goteros."),
            "Alto": ("El agua está alcalina. Probablemente tiene bicarbonatos, que bloquean hierro, fósforo, "
                     "manganeso y zinc y tapan goteros.",
                     "Considera acidificar el agua de riego (ácido nítrico o fosfórico) para bajar el pH al rango óptimo."),
        },
        "suelo": {
            "Bajo": ("El suelo está ácido: el calcio y el magnesio se aprovechan peor y puede haber toxicidad "
                     "por manganeso o aluminio.",
                     "Revisa si estás usando muchas fuentes de amonio o ácidos; evalúa una enmienda (cal) con tu agrónomo."),
            "Alto": ("El suelo está alcalino: hierro, manganeso, zinc y fósforo se bloquean y la planta puede "
                     "mostrar hojas nuevas amarillas.",
                     "Acidifica el agua de riego y usa fertilizantes de reacción ácida; vigila los micronutrientes."),
        },
        "savia": {
            "Bajo": ("La savia está más ácida de lo normal. Suele asociarse a falta de cationes (potasio, calcio, "
                     "magnesio) o a exceso de amonio, y a mayor sensibilidad a hongos.",
                     "Revisa el aporte de K, Ca y Mg y reduce las fuentes amoniacales si las usas."),
            "Alto": ("La savia está menos ácida de lo normal. Puede indicar exceso de cationes o estrés de la planta.",
                     "Revisa si hay exceso de potasio o calcio en la fertilización y el estado hídrico del cultivo."),
        },
    },
    "EC_dS_m": {
        "agua": {
            "Alto": ("El agua trae muchas sales. Eso suma salinidad al suelo en cada riego.",
                     "Aplica riegos con fracción de lavado (drenaje), y descuenta las sales del agua al calcular la fertilización."),
            "Bajo": ("El agua tiene muy pocas sales (es un agua 'blanda').",
                     "Normalmente no es problema; asegúrate de aportar calcio y magnesio con la fertilización."),
        },
        "suelo": {
            "Alto": ("Hay demasiadas sales en la zona de raíces. La planta absorbe agua con dificultad; en tomate "
                     "aumenta el riesgo de pudrición apical y frutos pequeños.",
                     "Aumenta el volumen o la frecuencia de riego para lavar sales y reduce la concentración de la fertirrigación."),
            "Bajo": ("Hay pocos nutrientes disponibles en la zona de raíces.",
                     "Aumenta la concentración de la fertirrigación o revisa si estás regando en exceso (lavando nutrientes)."),
        },
        "savia": {
            "Alto": ("La savia está muy concentrada. Puede indicar estrés hídrico o exceso de fertilización.",
                     "Revisa la humedad del suelo, el riego en horas de calor y la CE de la solución de suelo."),
            "Bajo": ("La savia está diluida: la planta tiene pocos solutos o está muy hidratada.",
                     "Revisa si hay exceso de riego o una nutrición general baja."),
        },
    },
    "NO3_ppm": {
        "agua": {
            "Alto": ("El agua ya trae nitrógeno (nitratos).", "Descuenta ese nitrógeno del plan de fertilización para no sobrefertilizar."),
            "Bajo": ("El agua trae poco nitrato. Es lo normal.", "Ninguna acción necesaria."),
        },
        "suelo": {
            "Alto": ("Hay exceso de nitrógeno disponible en el suelo.", "Reduce el nitrógeno en la fertirrigación y vigila la salinidad."),
            "Bajo": ("Hay poco nitrógeno disponible para las raíces.", "Aumenta el aporte de nitrógeno nítrico en la fertirrigación."),
        },
        "savia": {
            "Alto": ("La planta tiene exceso de nitrógeno: crece mucho en hojas y tallos, se vuelve más tierna "
                     "(más plagas y enfermedades) y puede retrasar el cuajado y la maduración.",
                     "Reduce el nitrógeno en la fertirrigación, sobre todo si el cultivo está en etapa productiva."),
            "Bajo": ("La planta tiene poco nitrógeno. Puede verse amarillamiento general de las hojas viejas "
                     "y crecimiento lento.",
                     "Aumenta el aporte de nitrógeno (preferiblemente nítrico) y vuelve a medir en 1 semana."),
        },
    },
    "K_ppm": {
        "agua": {
            "Alto": ("El agua trae potasio.", "Descuéntalo del plan de fertilización."),
            "Bajo": ("El agua trae poco potasio. Es lo normal.", "Ninguna acción necesaria."),
        },
        "suelo": {
            "Alto": ("Hay exceso de potasio en el suelo; compite con la absorción de calcio y magnesio.",
                     "Reduce el potasio en la fertirrigación y vigila calcio y magnesio."),
            "Bajo": ("Hay poco potasio disponible para las raíces.", "Aumenta el aporte de potasio en la fertirrigación."),
        },
        "savia": {
            "Alto": ("La planta tiene exceso de potasio. Compite con el calcio y el magnesio, y puede inducir "
                     "deficiencia de magnesio o pudrición apical.",
                     "Reduce el potasio y revisa el equilibrio con calcio y magnesio."),
            "Bajo": ("La planta tiene poco potasio. En tomate afecta el color, el sabor (grados Brix), el "
                     "tamaño del fruto y la maduración uniforme.",
                     "Aumenta el aporte de potasio, especialmente desde el inicio del llenado de frutos."),
        },
    },
    "Ca_ppm": {
        "agua": {
            "Alto": ("El agua es dura (tiene mucho calcio); puede formar incrustaciones en goteros.",
                     "Descuenta ese calcio de la fertilización y considera acidificar para evitar taponamientos."),
            "Bajo": ("El agua trae poco calcio.", "Asegúrate de aportar calcio con la fertilización."),
        },
        "suelo": {
            "Alto": ("Hay exceso de calcio en el suelo; puede limitar la absorción de potasio y magnesio.",
                     "Reduce las fuentes de calcio y vigila potasio y magnesio."),
            "Bajo": ("Hay poco calcio disponible para las raíces.", "Aumenta el aporte de calcio (por ejemplo, nitrato de calcio)."),
        },
        "savia": {
            "Alto": ("La planta tiene calcio de sobra; puede competir con potasio y magnesio.",
                     "Revisa si se puede reducir el calcio y vigila los niveles de K y Mg."),
            "Bajo": ("La planta tiene poco calcio. En tomate es la causa principal de la pudrición apical "
                     "(mancha negra en la punta del fruto).",
                     "Aumenta el calcio, mantén riegos regulares (sin secar el suelo), evita la CE alta y la humedad "
                     "relativa muy alta; considera aplicaciones foliares de calcio."),
        },
    },
    "Na_ppm": {
        "agua": {
            "Alto": ("El agua trae mucho sodio. Con el tiempo daña la estructura del suelo y desplaza al potasio y al calcio.",
                     "Busca otra fuente de agua o mézclala; aplica riegos de lavado y aporta calcio."),
        },
        "suelo": {
            "Alto": ("Se está acumulando sodio en el suelo; aumenta la salinidad y compite con potasio y calcio.",
                     "Aplica riegos de lavado con buen drenaje, aporta calcio y evita fertilizantes con sodio."),
        },
        "savia": {
            "Alto": ("La planta está absorbiendo mucho sodio, lo que indica estrés salino y desplaza al potasio.",
                     "Revisa el sodio del agua y del suelo, haz riegos de lavado y refuerza el potasio y el calcio."),
        },
    },
}

NOMBRE_CORTO = {"pH": "pH", "EC_dS_m": "CE", "NO3_ppm": "Nitrato", "K_ppm": "Potasio",
                "Ca_ppm": "Calcio", "Na_ppm": "Sodio"}


def grupo_matriz(matriz: str) -> str:
    return {"Agua de Riego": "agua", "Solución de Suelo": "suelo"}.get(matriz, "savia")


def intensidad(valor, mn, mx) -> str:
    """'ligeramente' si está a menos del 15 % del límite; 'muy' si se pasa más del 50 %."""
    limite = mn if (mn is not None and valor < mn) else mx
    if not limite:
        return ""
    desvio = abs(valor - limite) / limite
    return "ligeramente " if desvio < 0.15 else ("muy " if desvio > 0.5 else "")


def interpretar(muestra: pd.Series, df_rangos: pd.DataFrame, df_hist: pd.DataFrame) -> dict:
    """Devuelve un resumen + lista de hallazgos con significado y acción en lenguaje sencillo."""
    grupo = grupo_matriz(muestra["Matriz"])
    hallazgos, optimos, sin_rango = [], [], []

    for param in PARAMETROS:
        valor = muestra.get(param)
        if valor is None or pd.isna(valor):
            continue
        mn, mx = buscar_rango(df_rangos, muestra["Matriz"], muestra["Etapa"], param)
        estado = evaluar(valor, mn, mx)
        nombre = NOMBRE_CORTO[param]
        if "Óptimo" in estado:
            optimos.append(nombre)
        elif "Sin rango" in estado:
            sin_rango.append(nombre)
        else:
            clave = "Bajo" if "Bajo" in estado else "Alto"
            texto = MENSAJES.get(param, {}).get(grupo, {}).get(clave)
            significado, accion = texto if texto else ("Valor fuera del rango de referencia.", "Revísalo con tu agrónomo.")
            ref = f"< {mx:g}" if mn is None else (f"> {mn:g}" if mx is None else f"{mn:g} - {mx:g}")
            hallazgos.append({
                "nivel": "error" if intensidad(valor, mn, mx) != "ligeramente " else "warning",
                "titulo": f"{nombre} {intensidad(valor, mn, mx)}{clave.lower()} ({valor:g} · óptimo {ref})",
                "significado": significado, "accion": accion})

    # --- Relaciones entre nutrientes (en savia) ---
    if grupo == "savia":
        k, ca = muestra.get("K_ppm"), muestra.get("Ca_ppm")
        mn_k, mx_k = buscar_rango(df_rangos, muestra["Matriz"], muestra["Etapa"], "K_ppm")
        mn_ca, mx_ca = buscar_rango(df_rangos, muestra["Matriz"], muestra["Etapa"], "Ca_ppm")
        if all(v is not None and pd.notna(v) for v in [k, ca]) and ca > 0 and None not in [mn_k, mx_k, mn_ca, mx_ca]:
            rel = k / ca
            rel_ref = ((mn_k + mx_k) / 2) / ((mn_ca + mx_ca) / 2)   # relación esperada según TUS rangos
            if rel > rel_ref * 1.5:
                hallazgos.append({
                    "nivel": "warning",
                    "titulo": f"Desbalance K/Ca: {rel:.1f} (esperado ≈ {rel_ref:.1f})",
                    "significado": "Hay mucho potasio en proporción al calcio. Incluso si cada uno estuviera en rango, "
                                   "esta relación aumenta el riesgo de pudrición apical.",
                    "accion": "Equilibra la fertilización: menos potasio o más calcio."})
            elif rel < rel_ref / 1.5:
                hallazgos.append({
                    "nivel": "warning",
                    "titulo": f"Desbalance K/Ca: {rel:.1f} (esperado ≈ {rel_ref:.1f})",
                    "significado": "Hay poco potasio en proporción al calcio; puede afectar la calidad y el llenado del fruto.",
                    "accion": "Equilibra la fertilización: más potasio o menos calcio."})
            # Riesgo de magnesio (indicador indirecto: no mide Mg)
            if k > mx_k or rel > rel_ref * 1.5:
                hallazgos.append({
                    "nivel": "info",
                    "titulo": "Posible riesgo de deficiencia de magnesio",
                    "significado": "El exceso de potasio compite con el magnesio. Este equipo no mide Mg, "
                                   "así que esto es solo una alerta, no un diagnóstico.",
                    "accion": "Revisa las hojas viejas (amarillamiento entre nervaduras) y confirma con un análisis de Mg."})

    # --- Comparación con la muestra anterior del mismo lote y matriz ---
    cambios = []
    prev = df_hist[(df_hist["Lote"] == muestra["Lote"]) & (df_hist["Matriz"] == muestra["Matriz"]) &
                   (df_hist["Fecha"] < pd.Timestamp(muestra["Fecha"]))].sort_values("Fecha")
    if not prev.empty:
        anterior = prev.iloc[-1]
        for param in PARAMETROS:
            a, b = anterior.get(param), muestra.get(param)
            if pd.notna(a) and pd.notna(b) and a not in (0, None):
                var = (b - a) / a
                if abs(var) >= 0.20:
                    flecha = "⬆️ subió" if var > 0 else "⬇️ bajó"
                    cambios.append(f"{NOMBRE_CORTO[param]} {flecha} {abs(var):.0%} (de {a:g} a {b:g})")
        fecha_anterior = anterior["Fecha"]
    else:
        fecha_anterior = None

    n_prob = sum(1 for h in hallazgos if h["nivel"] in ("error", "warning"))
    if n_prob == 0:
        resumen = ("success", "✅ Muestra en buen estado: todos los parámetros con rango están dentro del óptimo.")
    elif n_prob <= 2:
        resumen = ("warning", f"⚠️ Atención: {n_prob} punto(s) requieren ajuste. Revisa las recomendaciones.")
    else:
        resumen = ("error", f"🚨 {n_prob} puntos fuera de lo recomendado. Conviene corregir la fertirrigación pronto.")

    return {"resumen": resumen, "hallazgos": hallazgos, "optimos": optimos, "sin_rango": sin_rango,
            "cambios": cambios, "fecha_anterior": fecha_anterior}


def informe_texto(muestra: pd.Series, analisis: dict) -> str:
    """Versión en texto plano para descargar o enviar por WhatsApp/correo."""
    lineas = [f"INFORME HORIBA - {muestra['Lote']} | {muestra['Matriz']} | {muestra['Etapa']} | "
              f"{pd.Timestamp(muestra['Fecha']):%d/%m/%Y}", "", analisis["resumen"][1], ""]
    if analisis["optimos"]:
        lineas.append("En rango óptimo: " + ", ".join(analisis["optimos"]))
    for h in analisis["hallazgos"]:
        lineas += ["", f"* {h['titulo']}", f"  Qué significa: {h['significado']}", f"  Qué hacer: {h['accion']}"]
    if analisis["cambios"]:
        lineas += ["", f"Cambios desde el {analisis['fecha_anterior']:%d/%m/%Y}:"] + [f"  - {c}" for c in analisis["cambios"]]
    if muestra.get("Notas"):
        lineas += ["", f"Notas: {muestra['Notas']}"]
    lineas += ["", "Análisis orientativo generado automáticamente. Confirma las decisiones con tu agrónomo."]
    return "\n".join(lineas)


# ==========================================
# TABLERO DE LOTES
# ==========================================
def estado_simple(valor, mn, mx):
    """'Bajo' / 'Óptimo' / 'Alto' / None."""
    e = evaluar(valor, mn, mx)
    for k in ("Bajo", "Óptimo", "Alto"):
        if k in e:
            return k
    return None


def resumen_lotes(df_hist: pd.DataFrame, df_rangos: pd.DataFrame, matriz: str, hoy=None) -> pd.DataFrame:
    """Última muestra de cada lote para una matriz, con semáforo por parámetro."""
    hoy = pd.Timestamp(hoy or date.today())
    df = df_hist[df_hist["Matriz"] == matriz].sort_values("Fecha")
    filas = []
    for lote, grupo in df.groupby("Lote"):
        m = grupo.iloc[-1]
        fila = {"Lote": lote, "Fecha": m["Fecha"], "Días": int((hoy - m["Fecha"]).days), "Etapa": m["Etapa"]}
        n_fuera = 0
        for p in PARAMETROS:
            mn, mx = buscar_rango(df_rangos, matriz, m["Etapa"], p)
            e = evaluar(m[p], mn, mx)
            if pd.isna(m[p]):
                fila[NOMBRE_CORTO[p]] = "—"
            else:
                fila[NOMBRE_CORTO[p]] = f"{e[:1]} {m[p]:g}"
                n_fuera += ("Alto" in e) or ("Bajo" in e)
        fila["Fuera de rango"] = n_fuera
        fila["Estado"] = "🟢 Bien" if n_fuera == 0 else ("🟠 Atención" if n_fuera <= 2 else "🔴 Corregir")
        filas.append(fila)
    if not filas:
        return pd.DataFrame()
    return pd.DataFrame(filas).sort_values(["Fuera de rango", "Días"], ascending=[False, False]).reset_index(drop=True)


# ==========================================
# RELACIÓN AGUA – SUELO – SAVIA
# ==========================================
CAUSAS_ABSORCION = {
    "Ca_ppm": "riego irregular (el suelo se seca entre riegos), CE alta en el suelo, humedad relativa muy alta "
              "(la planta transpira poco y el calcio no sube), exceso de potasio o amonio, o raíces dañadas",
    "K_ppm": "exceso de calcio, magnesio o sodio que compiten con el potasio, suelo frío o encharcado, o raíces dañadas",
    "NO3_ppm": "raíces dañadas o con poco oxígeno (encharcamiento), temperaturas bajas o exceso de cloruros",
}


def muestras_cercanas(df_hist: pd.DataFrame, lote: str, fecha_ref, ventana_dias: int) -> dict:
    """Para cada matriz, la muestra del lote más cercana a la fecha de referencia (dentro de la ventana)."""
    fecha_ref = pd.Timestamp(fecha_ref)
    out = {}
    for matriz in MATRICES:
        d = df_hist[(df_hist["Lote"] == lote) & (df_hist["Matriz"] == matriz)].copy()
        if d.empty:
            continue
        d["dist"] = (d["Fecha"] - fecha_ref).abs().dt.days
        d = d[d["dist"] <= ventana_dias]
        if not d.empty:
            out[matriz] = d.sort_values(["dist", "Fecha"], ascending=[True, False]).iloc[0]
    return out


def indice_optimo(valor, mn, mx):
    """100 = centro del rango óptimo (o el límite, si el rango es solo '< x' o '> x')."""
    if valor is None or pd.isna(valor):
        return None
    ref = (mn + mx) / 2 if (mn is not None and mx is not None) else (mx if mx is not None else mn)
    return round(100 * valor / ref, 1) if ref else None


def interpretar_relacion(muestras: dict, df_rangos: pd.DataFrame) -> list:
    """Reglas que cruzan agua, suelo y savia para indicar de dónde viene el problema."""
    def est(matriz, p):
        m = muestras.get(matriz)
        if m is None or pd.isna(m[p]):
            return None
        return estado_simple(m[p], *buscar_rango(df_rangos, matriz, m["Etapa"], p))

    out = []
    for p in ["Ca_ppm", "K_ppm", "NO3_ppm"]:
        nombre = NOMBRE_CORTO[p]
        s, v = est("Solución de Suelo", p), est("Savia (ECP)", p)
        if s in ("Óptimo", "Alto") and v == "Bajo":
            out.append(("error", f"{nombre}: hay en el suelo, pero no llega a la planta",
                        f"El problema no es la cantidad aplicada sino la absorción. Causas comunes: {CAUSAS_ABSORCION[p]}. "
                        f"Aplicar más {nombre.lower()} al suelo probablemente no lo resuelva; corrige primero la causa."))
        elif s == "Bajo" and v == "Bajo":
            out.append(("error", f"{nombre}: falta en el suelo y en la planta",
                        f"Es un problema de aporte. Aumenta el {nombre.lower()} en la fertirrigación."))
        elif s == "Bajo" and v in ("Óptimo", "Alto"):
            out.append(("warning", f"{nombre}: la planta está bien, pero el suelo se está agotando",
                        f"Ajusta el aporte de {nombre.lower()} ahora, antes de que la deficiencia aparezca en la planta."))
        elif s == "Alto" and v == "Alto":
            out.append(("warning", f"{nombre}: exceso en el suelo y en la planta",
                        f"Se está sobrefertilizando con {nombre.lower()}. Reduce la dosis; ahorras fertilizante."))
        elif s == "Óptimo" and v == "Alto":
            out.append(("info", f"{nombre}: la planta está acumulando",
                        f"El suelo está bien pero la planta tiene de más. Vigila y considera bajar un poco el aporte."))
        elif s == "Óptimo" and v == "Óptimo":
            out.append(("success", f"{nombre}: suelo y planta en equilibrio", "Mantén el manejo actual."))

    a_na, s_na, v_na = est("Agua de Riego", "Na_ppm"), est("Solución de Suelo", "Na_ppm"), est("Savia (ECP)", "Na_ppm")
    if a_na == "Alto":
        txt = "El agua de riego es una fuente de sodio."
        if s_na == "Alto":
            txt += " Ya se está acumulando en el suelo."
        if v_na == "Alto":
            txt += " Y está llegando a la planta (estrés salino)."
        out.append(("error", "Sodio: viene del agua de riego",
                    txt + " Considera mezclar o cambiar la fuente de agua, riegos de lavado y aporte de calcio."))
    elif s_na == "Alto":
        out.append(("warning", "Sodio: se acumula en el suelo sin venir del agua",
                    "Revisa fertilizantes o enmiendas que contengan sodio y el drenaje del suelo."))

    if est("Agua de Riego", "EC_dS_m") == "Alto" and est("Solución de Suelo", "EC_dS_m") == "Alto":
        out.append(("warning", "Sales: el agua está salinizando el suelo",
                    "Aumenta la fracción de lavado (que drene un 15–25 % del riego) y descuenta las sales del agua."))
    if est("Agua de Riego", "pH") == "Alto" and est("Solución de Suelo", "pH") == "Alto":
        out.append(("warning", "pH: el agua alcalina está subiendo el pH del suelo",
                    "Acidifica el agua de riego; mejorará la disponibilidad de hierro, fósforo y micronutrientes."))
    return out


def aporte_agua(muestras: dict) -> list:
    """Cuánto representa lo que trae el agua frente a lo que hay en la solución de suelo."""
    a, s = muestras.get("Agua de Riego"), muestras.get("Solución de Suelo")
    if a is None or s is None:
        return []
    out = []
    for p in ["Ca_ppm", "K_ppm", "NO3_ppm", "Na_ppm"]:
        if pd.notna(a[p]) and pd.notna(s[p]) and s[p] > 0:
            out.append((NOMBRE_CORTO[p], a[p], s[p], 100 * a[p] / s[p]))
    return out


# ==========================================
# ESTADO
# ==========================================
df_historico = cargar_datos()
df_rangos = cargar_rangos()

# Mensajes que sobreviven a st.rerun()
if "aviso" in st.session_state:
    st.toast(st.session_state.pop("aviso"))


def mostrar_analisis(muestra: pd.Series, clave: str) -> None:
    """Dibuja el análisis interpretado de una muestra."""
    analisis = interpretar(muestra, df_rangos, df_historico)
    st.subheader(f"🧠 Análisis: {muestra['Lote']} · {muestra['Matriz']} · {muestra['Etapa']} · "
                 f"{pd.Timestamp(muestra['Fecha']):%d/%m/%Y}")
    tipo, texto = analisis["resumen"]
    getattr(st, tipo)(texto)

    if analisis["optimos"]:
        st.markdown("🟢 **En rango óptimo:** " + ", ".join(analisis["optimos"]))

    iconos = {"error": "🔴", "warning": "🟠", "info": "🔵"}
    for h in analisis["hallazgos"]:
        with st.container(border=True):
            st.markdown(f"**{iconos[h['nivel']]} {h['titulo']}**")
            st.markdown(f"**¿Qué significa?** {h['significado']}")
            st.markdown(f"**¿Qué hacer?** {h['accion']}")

    if analisis["cambios"]:
        st.markdown(f"**📅 Cambios importantes desde el muestreo del {analisis['fecha_anterior']:%d/%m/%Y}:**")
        for c in analisis["cambios"]:
            st.markdown(f"- {c}")
    if analisis["sin_rango"]:
        st.caption("Sin rango de referencia para: " + ", ".join(analisis["sin_rango"]) +
                   ". Puedes agregarlo en la pestaña Rangos.")

    with st.expander("Ver tabla de valores"):
        st.dataframe(tabla_diagnostico(muestra, df_rangos), hide_index=True, width="stretch",
                     column_config={"Medido": st.column_config.NumberColumn(format="%.2f")})

    st.download_button("📄 Descargar informe (texto)", data=informe_texto(muestra, analisis).encode("utf-8"),
                       file_name=f"informe_{muestra['Lote']}_{pd.Timestamp(muestra['Fecha']):%Y%m%d}.txt",
                       mime="text/plain", key=f"dl_{clave}")
    st.caption("ℹ️ Análisis orientativo generado automáticamente a partir de tus rangos de referencia. "
               "Confirma las decisiones de fertilización con tu agrónomo.")

# ==========================================
# BARRA LATERAL: respaldo de datos
# ==========================================
with st.sidebar:
    st.header("💾 Datos")
    if USAR_SHEETS:
        st.success("☁️ Guardando en Google Sheets (permanente)")
        if st.button("🔄 Recargar datos de la hoja", width="stretch"):
            leer_hoja.clear()
            st.rerun()
    elif ERROR_SHEETS is not None:
        st.error(f"No se pudo conectar a Google Sheets: {ERROR_SHEETS}. "
                 "Se están usando archivos temporales: descarga un respaldo antes de cerrar.")
    else:
        st.warning("📁 Guardando en archivos temporales. En Streamlit Cloud se borran al reiniciarse la app: "
                   "descarga un respaldo cada jornada o configura Google Sheets (ver README).")
    st.download_button("📥 Descargar respaldo (CSV)",
                       data=df_historico.to_csv(index=False).encode("utf-8"),
                       file_name=f"respaldo_horiba_{date.today():%Y%m%d}.csv",
                       mime="text/csv", disabled=df_historico.empty, width="stretch")

    archivo = st.file_uploader("📤 Restaurar desde CSV o Excel", type=["csv", "xlsx"])
    if archivo is not None:
        modo = st.radio("¿Cómo restaurar?", ["Agregar al histórico", "Reemplazar histórico"])
        if st.button("Restaurar", type="primary", width="stretch"):
            try:
                nuevo = pd.read_csv(archivo) if archivo.name.endswith(".csv") else pd.read_excel(archivo)
                nuevo = normalizar_datos(nuevo)
                if modo == "Agregar al histórico":
                    nuevo = pd.concat([df_historico, nuevo], ignore_index=True).drop_duplicates()
                guardar_datos(nuevo)
                st.session_state["aviso"] = f"✅ {len(nuevo)} registros en el histórico"
                st.rerun()
            except Exception as e:
                st.error(f"No se pudo leer el archivo: {e}")

    st.divider()
    st.metric("Registros guardados", len(df_historico))
    if not df_historico.empty:
        st.metric("Último muestreo", df_historico["Fecha"].max().strftime("%d/%m/%Y"))

# ==========================================
# ENCABEZADO
# ==========================================
st.title("🌱 Sistema de Análisis y Registro - HORIBA LAQUAtwin")
st.write("Registra y analiza los parámetros químicos de Agua, Suelo y Savia por etapas fenológicas.")

tab_ingreso, tab_tablero, tab_analisis, tab_relacion, tab_graf, tab_hist, tab_rangos = st.tabs(
    ["📥 Nuevo ingreso", "🏠 Tablero de lotes", "🧠 Análisis", "🔗 Agua–Suelo–Savia",
     "📊 Gráficos de tendencia", "📋 Histórico", "🔬 Rangos de referencia"])

COLORES_MATRIZ = {"Agua de Riego": "#4C78A8", "Solución de Suelo": "#9D755D", "Savia (ECP)": "#54A24B"}

# ==========================================
# PESTAÑA: TABLERO DE LOTES
# ==========================================
with tab_tablero:
    st.header("🏠 Tablero de lotes")
    st.caption("Último muestreo de cada lote. Los lotes con más problemas aparecen primero.")
    if df_historico.empty:
        st.info("Aún no hay muestras registradas.")
    else:
        disponibles = [m for m in MATRICES if m in df_historico["Matriz"].unique()]
        matriz_t = st.radio("Matriz", disponibles, horizontal=True, key="matriz_tablero",
                            index=disponibles.index("Savia (ECP)") if "Savia (ECP)" in disponibles else 0)
        dias_alerta = 14
        res = resumen_lotes(df_historico, df_rangos, matriz_t)

        k1, k2, k3, k4, k5 = st.columns(5)
        k1.metric("Lotes", len(res))
        k2.metric("🟢 Bien", int((res["Estado"] == "🟢 Bien").sum()))
        k3.metric("🟠 Atención", int((res["Estado"] == "🟠 Atención").sum()))
        k4.metric("🔴 Corregir", int((res["Estado"] == "🔴 Corregir").sum()))
        k5.metric(f"⏰ Sin medir +{dias_alerta} días", int((res["Días"] > dias_alerta).sum()))

        columnas = st.columns(3)
        for i, fila in res.iterrows():
            with columnas[i % 3].container(border=True):
                st.markdown(f"### {fila['Lote']}")
                st.markdown(f"**{fila['Estado']}** · {fila['Fuera de rango']} fuera de rango")
                hace = "hoy" if fila["Días"] == 0 else f"hace {fila['Días']} días"
                st.caption(f"📅 {fila['Fecha']:%d/%m/%Y} ({hace}) · {fila['Etapa']}")
                if fila["Días"] > dias_alerta:
                    st.caption(f"⏰ Toca volver a medir este lote")
                st.markdown("  \n".join(f"{fila[NOMBRE_CORTO[p]]} · {NOMBRE_CORTO[p]}"
                                        for p in PARAMETROS if fila[NOMBRE_CORTO[p]] != "—"))

        with st.expander("Ver como tabla"):
            st.dataframe(res, hide_index=True, width="stretch",
                         column_config={"Fecha": st.column_config.DateColumn(format="DD/MM/YYYY")})
        st.caption("🟢 óptimo · 🔵 bajo · 🔴 alto · ⚪ sin rango. Para ver qué hacer en cada lote, "
                   "usa la pestaña 🧠 Análisis.")

# ==========================================
# PESTAÑA: RELACIÓN AGUA – SUELO – SAVIA
# ==========================================
with tab_relacion:
    st.header("🔗 Relación Agua – Suelo – Savia")
    st.caption("Compara las tres matrices del mismo lote para saber si un problema viene del agua, "
               "del suelo o de la absorción de la planta.")
    if df_historico.empty:
        st.info("Aún no hay muestras registradas.")
    else:
        r1, r2, r3 = st.columns(3)
        lote_r = r1.selectbox("Lote", sorted(df_historico["Lote"].unique()), key="lote_rel")
        fecha_max = df_historico.loc[df_historico["Lote"] == lote_r, "Fecha"].max().date()
        fecha_r = r2.date_input("Fecha de referencia", fecha_max, format="DD/MM/YYYY", key="fecha_rel")
        ventana = r3.slider("Buscar muestras ± días", 0, 30, 7, key="ventana_rel",
                            help="Las muestras de agua, suelo y savia no siempre se toman el mismo día.")

        muestras = muestras_cercanas(df_historico, lote_r, fecha_r, ventana)
        faltan = [m for m in MATRICES if m not in muestras]

        if not muestras:
            st.warning("No hay muestras de este lote cerca de esa fecha. Amplía la ventana de días.")
        else:
            st.markdown("**Muestras usadas:** " + " · ".join(
                f"{m}: {muestras[m]['Fecha']:%d/%m/%Y}" for m in MATRICES if m in muestras))
            if faltan:
                st.info("Falta: " + ", ".join(faltan) + ". El análisis cruzado es más completo con las tres matrices.")

            # Tabla comparativa
            tabla, barras = [], []
            for p in PARAMETROS:
                fila = {"Parámetro": PARAMETROS[p][1]}
                for m in MATRICES:
                    if m in muestras and pd.notna(muestras[m][p]):
                        mn, mx = buscar_rango(df_rangos, m, muestras[m]["Etapa"], p)
                        fila[m] = f"{evaluar(muestras[m][p], mn, mx)[:1]} {muestras[m][p]:g}"
                        idx = indice_optimo(muestras[m][p], mn, mx)
                        if idx is not None:
                            barras.append({"Parámetro": NOMBRE_CORTO[p], "Matriz": m, "Índice": idx,
                                           "Valor": muestras[m][p]})
                    else:
                        fila[m] = "—"
                tabla.append(fila)
            st.dataframe(pd.DataFrame(tabla), hide_index=True, width="stretch")

            if barras:
                fig_r = px.bar(pd.DataFrame(barras), x="Parámetro", y="Índice", color="Matriz", barmode="group",
                               color_discrete_map=COLORES_MATRIZ, hover_data={"Valor": True},
                               labels={"Índice": "% respecto al óptimo"},
                               title="¿Qué tan cerca del óptimo está cada matriz? (100 = centro del rango)")
                fig_r.add_hline(y=100, line_dash="dash", line_color="green",
                                annotation_text="Óptimo", annotation_position="top left")
                st.plotly_chart(fig_r, width="stretch")
                st.caption("Cada matriz se compara con su propio rango, porque las concentraciones en savia son "
                           "mucho mayores que en el agua o el suelo. Para Sodio y CE del agua, 100 = límite máximo.")

            st.subheader("🧠 Interpretación")
            hallazgos_r = interpretar_relacion(muestras, df_rangos)
            if not hallazgos_r:
                st.info("Se necesitan al menos suelo y savia (o agua y suelo) con datos para cruzar la información.")
            iconos_r = {"error": "🔴", "warning": "🟠", "info": "🔵", "success": "🟢"}
            for nivel, titulo, texto in hallazgos_r:
                with st.container(border=True):
                    st.markdown(f"**{iconos_r[nivel]} {titulo}**")
                    st.markdown(texto)

            aporte = aporte_agua(muestras)
            if aporte:
                st.subheader("💧 Lo que aporta el agua de riego")
                cols = st.columns(len(aporte))
                for col, (nombre, a, s, pct) in zip(cols, aporte):
                    col.metric(nombre, f"{a:g} ppm", help=f"Solución de suelo: {s:g} ppm")
                    col.caption(f"= {pct:.0f} % de lo que hay en el suelo")
                st.caption("Si el agua aporta una parte importante (más del 20–30 %) de un nutriente, descuéntalo "
                           "del plan de fertilización. Si se trata de sodio, es una alerta de calidad de agua.")
            st.caption("ℹ️ Análisis orientativo. Confirma las decisiones con tu agrónomo.")

# ==========================================
# PESTAÑA 1: INGRESO DE DATOS
# ==========================================
with tab_ingreso:
    st.header("Formulario de mediciones HORIBA")

    lotes_existentes = sorted(df_historico["Lote"].unique().tolist())

    with st.form("formulario_registro", clear_on_submit=False):
        c1, c2, c3, c4 = st.columns(4)
        fecha = c1.date_input("Fecha de muestreo", date.today(), format="DD/MM/YYYY")
        lote = c2.text_input("Lote / Invernadero / Casa", value=lotes_existentes[-1] if lotes_existentes else "Lote 1",
                             help="Lotes ya registrados: " + ", ".join(lotes_existentes) if lotes_existentes else None)
        matriz = c3.selectbox("Matriz analizada", MATRICES)
        etapa = c4.selectbox("Etapa fenológica", ETAPAS,
                             help="Para Savia elige la etapa: los rangos cambian según la etapa.")

        st.subheader("Valores medidos")
        st.caption("Deja en blanco los parámetros que no mediste.")
        m1, m2, m3 = st.columns(3)
        ph = m1.number_input("pH (pH-11)", 0.0, 14.0, value=None, step=0.1, placeholder="ej. 6.2")
        k = m1.number_input("Potasio K⁺ ppm (K-11)", 0.0, 10000.0, value=None, step=10.0, placeholder="ej. 200")
        ec = m2.number_input("CE dS/m (EC-11)", 0.0, 20.0, value=None, step=0.05, placeholder="ej. 1.5")
        ca = m2.number_input("Calcio Ca²⁺ ppm (Ca-11)", 0.0, 10000.0, value=None, step=5.0, placeholder="ej. 80")
        no3 = m3.number_input("Nitrato NO3⁻ ppm (NO3-11)", 0.0, 10000.0, value=None, step=10.0, placeholder="ej. 150")
        na = m3.number_input("Sodio Na⁺ ppm (Na-11)", 0.0, 5000.0, value=None, step=5.0, placeholder="ej. 20")

        notas = st.text_area("Notas / observaciones", placeholder="Ej: inicio de floración, tercera semana…")
        enviado = st.form_submit_button("💾 Guardar registro", type="primary")

    if enviado:
        valores = {"pH": ph, "EC_dS_m": ec, "NO3_ppm": no3, "K_ppm": k, "Ca_ppm": ca, "Na_ppm": na}
        if not lote.strip():
            st.error("⚠️ Ingresa un nombre para el lote antes de guardar.")
        elif all(v is None for v in valores.values()):
            st.error("⚠️ Ingresa al menos un valor medido.")
        else:
            nueva = {"Fecha": pd.Timestamp(fecha), "Lote": lote.strip(), "Matriz": matriz,
                     "Etapa": etapa, **valores, "Notas": notas.strip()}
            guardar_datos(pd.concat([df_historico, pd.DataFrame([nueva])], ignore_index=True))
            st.session_state["ultima_muestra"] = nueva
            st.session_state["aviso"] = f"✅ Muestra guardada en {lote.strip()}"
            st.rerun()

    # Análisis inmediato de la última muestra guardada
    if "ultima_muestra" in st.session_state:
        st.divider()
        mostrar_analisis(pd.Series(st.session_state["ultima_muestra"]), "ingreso")

# ==========================================
# PESTAÑA: ANÁLISIS DE CUALQUIER MUESTRA
# ==========================================
with tab_analisis:
    st.header("🧠 Análisis e interpretación")
    if df_historico.empty:
        st.info("Aún no hay muestras registradas.")
    else:
        a1, a2, a3 = st.columns(3)
        lote_a = a1.selectbox("Lote", sorted(df_historico["Lote"].unique()), key="lote_a")
        df_la = df_historico[df_historico["Lote"] == lote_a]
        matriz_a = a2.selectbox("Matriz", sorted(df_la["Matriz"].unique()), key="matriz_a")
        df_lm = df_la[df_la["Matriz"] == matriz_a].sort_values("Fecha", ascending=False)
        idx = a3.selectbox("Muestra", df_lm.index,
                           format_func=lambda i: f"{df_lm.loc[i, 'Fecha']:%d/%m/%Y} · {df_lm.loc[i, 'Etapa']}",
                           key="muestra_a")
        mostrar_analisis(df_lm.loc[idx], "tab")

# ==========================================
# PESTAÑA 2: GRÁFICOS
# ==========================================
with tab_graf:
    st.header("📈 Evolución temporal de nutrientes")
    if df_historico.empty:
        st.info("Aún no hay datos. Registra tu primera muestra en la pestaña **Nuevo ingreso**.")
    else:
        f1, f2, f3, f4 = st.columns(4)
        lotes_sel = f1.multiselect("Lote", sorted(df_historico["Lote"].unique()),
                                   default=sorted(df_historico["Lote"].unique()))
        matrices_disp = [m for m in MATRICES if m in df_historico["Matriz"].unique()] or MATRICES
        matriz_sel = f2.selectbox("Matriz", matrices_disp)
        etapas_disp = sorted(df_historico.loc[df_historico["Matriz"] == matriz_sel, "Etapa"].unique()) or ETAPAS
        etapa_sel = f3.selectbox("Etapa (para el rango óptimo)", etapas_disp)
        parametro = f4.selectbox("Parámetro", list(PARAMETROS), format_func=lambda p: PARAMETROS[p][1])

        fmin, fmax = df_historico["Fecha"].min().date(), df_historico["Fecha"].max().date()
        rango_fechas = st.date_input("Periodo", (fmin, fmax), min_value=fmin, max_value=fmax, format="DD/MM/YYYY")

        df_base = df_historico[(df_historico["Lote"].isin(lotes_sel)) &
                               (df_historico["Matriz"] == matriz_sel)]
        if isinstance(rango_fechas, tuple) and len(rango_fechas) == 2:
            df_base = df_base[df_base["Fecha"].dt.date.between(*rango_fechas)]
        df_base = df_base.sort_values("Fecha")
        df_f = df_base.dropna(subset=[parametro])

        if df_f.empty:
            st.warning("No hay datos para esa combinación de filtros.")
        else:
            fig = px.line(df_f, x="Fecha", y=parametro, color="Lote", markers=True,
                          hover_data=["Etapa", "Notas"],
                          labels={parametro: PARAMETROS[parametro][1]})
            mn, mx = buscar_rango(df_rangos, matriz_sel, etapa_sel, parametro)
            if mn is not None or mx is not None:
                y0 = mn if mn is not None else 0
                y1 = mx if mx is not None else max(df_f[parametro].max(), y0) * 1.2
                fig.add_hrect(y0=y0, y1=y1, fillcolor="green", opacity=0.12, line_width=0,
                              annotation_text="Rango óptimo", annotation_position="top left")
            fig.update_layout(hovermode="x unified", legend_title_text="Lote")
            st.plotly_chart(fig, width="stretch")

            k1, k2, k3, k4 = st.columns(4)
            ultimo = df_f.iloc[-1][parametro]
            previo = df_f.iloc[-2][parametro] if len(df_f) > 1 else None
            k1.metric("Último valor", f"{ultimo:.2f}",
                      delta=f"{ultimo - previo:+.2f}" if previo is not None else None)
            k2.metric("Promedio", f"{df_f[parametro].mean():.2f}")
            k3.metric("Mínimo / Máximo", f"{df_f[parametro].min():.2f} / {df_f[parametro].max():.2f}")
            k4.metric("Estado del último", evaluar(ultimo, mn, mx))

        # ---------- GRÁFICO DE TORTA: COMPOSICIÓN IÓNICA ----------
        st.divider()
        st.subheader("🥧 Composición iónica: Calcio, Potasio, Sodio y Nitratos")
        st.caption("Usa los mismos filtros de lote, matriz y periodo de arriba.")

        p1, p2, p3 = st.columns(3)
        lote_torta = p1.selectbox("Lote", sorted(df_base["Lote"].unique()) or ["—"], key="lote_torta")
        base_torta = p2.radio("Datos", ["Última muestra", "Promedio del periodo"], key="base_torta")
        unidad = p3.radio("Unidad", ["ppm", "meq/L"], horizontal=True, key="unidad_torta",
                          help="meq/L compara los iones por su carga química (más útil para el balance "
                               "nutricional). ppm compara por peso.")

        df_lote = df_base[df_base["Lote"] == lote_torta]
        if df_lote.empty:
            st.info("No hay muestras para ese lote con los filtros actuales.")
        else:
            if base_torta == "Última muestra":
                fila = df_lote.iloc[-1]
                titulo = f"{lote_torta} · {matriz_sel} · {fila['Fecha']:%d/%m/%Y}"
            else:
                fila = df_lote[list(IONES)].mean()
                titulo = f"{lote_torta} · {matriz_sel} · promedio de {len(df_lote)} muestras"

            datos_torta = pd.DataFrame([
                {"Ion": nombre,
                 "Valor": fila[col] / (PESO_EQUIVALENTE[col] if unidad == "meq/L" else 1)}
                for col, nombre in IONES.items() if pd.notna(fila[col]) and fila[col] > 0
            ])
            if datos_torta.empty:
                st.info("Esa muestra no tiene valores de Ca, K, Na ni NO3.")
            else:
                fig_torta = px.pie(datos_torta, names="Ion", values="Valor", hole=0.35,
                                   title=titulo, color="Ion", color_discrete_map=COLORES_IONES)
                fig_torta.update_traces(textinfo="percent+label",
                                        hovertemplate=f"%{{label}}: %{{value:.2f}} {unidad}<extra></extra>")
                t1, t2 = st.columns([2, 1])
                t1.plotly_chart(fig_torta, width="stretch")
                t2.dataframe(datos_torta.assign(**{"%": 100 * datos_torta["Valor"] / datos_torta["Valor"].sum()})
                             .rename(columns={"Valor": unidad}),
                             hide_index=True, width="stretch",
                             column_config={unidad: st.column_config.NumberColumn(format="%.2f"),
                                            "%": st.column_config.NumberColumn(format="%.1f")})
                faltan = [n for c, n in IONES.items() if pd.isna(fila[c]) or fila[c] <= 0]
                if faltan:
                    t2.caption("Sin dato: " + ", ".join(faltan))

# ==========================================
# PESTAÑA 3: HISTÓRICO EDITABLE
# ==========================================
with tab_hist:
    st.header("🗂️ Datos registrados")
    if df_historico.empty:
        st.info("La base de datos está vacía.")
    else:
        st.caption("Doble clic para editar una celda. Selecciona filas y pulsa 🗑️ para eliminarlas. "
                   "Luego guarda los cambios.")
        df_editado = st.data_editor(
            df_historico.sort_values("Fecha", ascending=False),
            num_rows="dynamic", width="stretch", hide_index=True, key="editor_tabla",
            column_config={
                "Fecha": st.column_config.DateColumn(format="DD/MM/YYYY", required=True),
                "Matriz": st.column_config.SelectboxColumn(options=MATRICES, required=True),
                "Etapa": st.column_config.SelectboxColumn(options=ETAPAS),
                "pH": st.column_config.NumberColumn(min_value=0, max_value=14, format="%.2f"),
                "EC_dS_m": st.column_config.NumberColumn("CE dS/m", format="%.2f"),
            })
        b1, b2 = st.columns(2)
        if b1.button("💾 Guardar cambios del histórico", type="primary"):
            guardar_datos(df_editado)
            st.session_state["aviso"] = "✅ Histórico actualizado"
            st.rerun()
        b2.download_button("📥 Descargar Excel (datos + rangos)",
                           data=a_excel({"Monitoreo_HORIBA": df_historico, "Rangos": df_rangos}),
                           file_name=f"reporte_horiba_{date.today():%Y%m%d}.xlsx",
                           mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")

# ==========================================
# PESTAÑA 4: RANGOS DE REFERENCIA
# ==========================================
with tab_rangos:
    st.header("🔬 Rangos de referencia por etapa fenológica")
    st.write("Edita los valores para adaptarlos a tu plan de manejo. Formatos aceptados: "
             "`5.5 - 6.5`, `< 1.0`, `> 2`, o `-` si no aplica.")
    df_rangos_editado = st.data_editor(
        df_rangos, num_rows="dynamic", width="stretch", hide_index=True, key="editor_rangos",
        column_config={
            "Matriz / Recurso": st.column_config.SelectboxColumn(options=MATRICES, required=True),
            "Etapa Fenológica": st.column_config.SelectboxColumn(options=ETAPAS, required=True),
        })
    r1, r2 = st.columns(2)
    if r1.button("💾 Guardar rangos", type="primary"):
        guardar_rangos(df_rangos_editado)
        st.session_state["aviso"] = "✅ Rangos actualizados"
        st.rerun()
    if r2.button("↩️ Restaurar rangos por defecto"):
        guardar_rangos(RANGOS_INICIALES)
        st.session_state["aviso"] = "Rangos restaurados a los valores iniciales"
        st.rerun()
