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
    "Na_ppm": (None, "Sodio Na⁺ (ppm)"),
}

RANGOS_INICIALES = pd.DataFrame({
    "Matriz / Recurso": ["Agua de Riego", "Solución de Suelo", "Savia (ECP)", "Savia (ECP)", "Savia (ECP)"],
    "Etapa Fenológica": ["Todas", "Todas", "Inicial / Enraizamiento", "Vegetativa / Desarrollo", "Productiva / Llenado"],
    "pH Óptimo": ["5.5 - 6.5", "5.8 - 6.8", "5.4 - 6.0", "5.4 - 6.2", "5.6 - 6.2"],
    "CE (dS/m)": ["< 1.0", "1.5 - 2.5", "-", "-", "-"],
    "Nitrato (NO3⁻) ppm": ["10 - 50", "100 - 200", "1200 - 1500", "1000 - 1300", "700 - 900"],
    "Potasio (K⁺) ppm": ["10 - 30", "150 - 250", "2000 - 2500", "2500 - 3500", "3500 - 5000"],
    "Calcio (Ca²⁺) ppm": ["40 - 80", "100 - 180", "150 - 200", "150 - 250", "100 - 180"],
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


def cargar_datos() -> pd.DataFrame:
    if DB_FILE.exists():
        return normalizar_datos(pd.read_csv(DB_FILE))
    return normalizar_datos(pd.DataFrame(columns=COLUMNAS_DATOS))


def guardar_datos(df: pd.DataFrame) -> None:
    normalizar_datos(df).to_csv(DB_FILE, index=False)


def cargar_rangos() -> pd.DataFrame:
    if RANGOS_FILE.exists():
        df = pd.read_csv(RANGOS_FILE, dtype=str).fillna("-")
        if "Etapa Fenológica" in df.columns:
            return df
    RANGOS_INICIALES.to_csv(RANGOS_FILE, index=False)
    return RANGOS_INICIALES.copy()


def guardar_rangos(df: pd.DataFrame) -> None:
    df.fillna("-").to_csv(RANGOS_FILE, index=False)


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
# ESTADO
# ==========================================
df_historico = cargar_datos()
df_rangos = cargar_rangos()

# Mensajes que sobreviven a st.rerun()
if "aviso" in st.session_state:
    st.toast(st.session_state.pop("aviso"))

# ==========================================
# BARRA LATERAL: respaldo de datos
# ==========================================
with st.sidebar:
    st.header("💾 Respaldo de datos")
    st.caption("En Streamlit Cloud los archivos se borran cuando la app se reinicia. "
               "Descarga un respaldo después de cada jornada y súbelo si la app se reinicia.")
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

tab_ingreso, tab_graf, tab_hist, tab_rangos = st.tabs(
    ["📥 Nuevo ingreso", "📊 Gráficos de tendencia", "📋 Histórico", "🔬 Rangos de referencia"])

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

    # Diagnóstico inmediato de la última muestra guardada
    if "ultima_muestra" in st.session_state:
        muestra = pd.Series(st.session_state["ultima_muestra"])
        st.subheader(f"🩺 Diagnóstico: {muestra['Lote']} · {muestra['Matriz']} · {muestra['Etapa']}")
        diag = tabla_diagnostico(muestra, df_rangos)
        st.dataframe(diag, hide_index=True, width="stretch",
                     column_config={"Medido": st.column_config.NumberColumn(format="%.2f")})
        fuera = diag[diag["Estado"].str.contains("Alto|Bajo")]
        if fuera.empty:
            st.success("Todos los parámetros con rango definido están en el óptimo.")
        else:
            st.warning("Fuera de rango: " + ", ".join(f"{r.Parámetro} ({r.Estado[2:]})" for r in fuera.itertuples()))

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

        df_f = df_historico[(df_historico["Lote"].isin(lotes_sel)) &
                            (df_historico["Matriz"] == matriz_sel)].dropna(subset=[parametro])
        if isinstance(rango_fechas, tuple) and len(rango_fechas) == 2:
            df_f = df_f[df_f["Fecha"].dt.date.between(*rango_fechas)]
        df_f = df_f.sort_values("Fecha")

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
