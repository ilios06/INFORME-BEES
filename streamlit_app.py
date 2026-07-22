import streamlit as st
import pandas as pd
import numpy as np
import plotly.express as px
import plotly.graph_objects as go
from plotly.subplots import make_subplots
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseDownload
from google.oauth2 import service_account
from google.cloud import bigquery
import io

# --- CONFIGURACIÓN DE LA PÁGINA WEB ---
st.set_page_config(
    page_title="App Conciliación BEES & COSTEÑO",
    page_icon="📊",
    layout="wide",
    initial_sidebar_state="expanded"
)

# --- CONSTANTES COMERCIALES E INFRAESTRUCTURA ---
TC_FIJO = 3.396
LISTA_MESES_ORDENADOS = ['Enero', 'Febrero', 'Marzo', 'Abril', 'Mayo', 'Junio', 'Julio', 'Agosto', 'Septiembre', 'Octubre', 'Noviembre', 'Diciembre']
FILE_ID_CONCILIACION = "1-EoM0rYAmYY_tBkKwL5--746cdUa0tw2"
URL_MAESTRO_SKU = "https://docs.google.com/spreadsheets/d/1Zck2x0VPW-zeQ8YjD6LbXw9uPavycYHrNXud-nG5uBc/edit?usp=sharing"

# --- PERSISTENCIA E INICIALIZACIÓN DE ESTADO GLOBAL (1° NIVEL) ---
if 'log_linaje' not in st.session_state: st.session_state.log_linaje = {"status": "OK", "alertas": []}
if 'filtro_region' not in st.session_state: st.session_state.filtro_region = "AMBOS"
if 'filtro_flujo' not in st.session_state: st.session_state.filtro_flujo = "Ingresados"
if 'filtro_mes_detalle' not in st.session_state: st.session_state.filtro_mes_detalle = "Enero"
if 'filtro_canal_log' not in st.session_state: st.session_state.filtro_canal_log = "UNIVERSO"

# --- CAPA DE VALIDACIÓN DE LINAJE DE INGESTIÓN ---
def validar_linaje_columnas(df, esquema_esperado):
    alertas = []
    df_columnas = df.columns.tolist()
    
    # Mapeo por proximidad conceptual en caso de alteración externa
    mapeos_emergencia = {
        'TOTAL': ['MONTO TOTAL', 'VALOR TOTAL', 'VENTA TOTAL'],
        'Zona_OfVta': ['ZONA', 'OFICINA VENTA', 'OFVTA'],
        'Tipo_Pedido': ['TIPO PEDIDO', 'CANAL PEDIDO', 'ORIGEN']
    }
    
    for col_core, sinonimos in mapeos_emergencia.items():
        if col_core not in df_columnas:
            for sinonimo in sinonimos:
                if sinonimo in [c.upper() for c in df_columnas]:
                    idx = [c.upper() for c in df_columnas].index(sinonimo)
                    df = df.rename(columns={df_columnas[idx]: col_core})
                    alertas.append(f"🔄 Linaje corregido: Columna '{df_columnas[idx]}' remapeada a '{col_core}'")
                    break
                    
    # Inyección de columnas faltantes para evitar rupturas de ejecución (Manejo Silencioso)
    for col in esquema_esperado:
        if col not in df.columns:
            alertas.append(f"⚠️ Columna crítica ausente: '{col}'. Inyectando valores por defecto.")
            df[col] = 0 if 'Valor' in col or 'TOTAL' in col or 'Cantidad' in col or 'Peso' in col else "SIN DATA"
            
    if alertas:
        st.session_state.log_linaje = {"status": "ADVERTENCIA", "alertas": alertas}
    return df

# --- CONEXIÓN DRIVE Y GCP ---
@st.cache_resource
def obtener_servicio_drive():
    try:
        info_claves = st.secrets["gcp_service_account"]
        creds = service_account.Credentials.from_service_account_info(info_claves)
        return build('drive', 'v3', credentials=creds)
    except Exception as e:
        st.error(f"❌ Error de autenticación en Drive: {e}")
        return None

# --- DESCARGA DE DATOS OPERATIVOS ---
@st.cache_data(ttl=3600)
def descargar_datos_maestros(file_id):
    service = obtener_servicio_drive()
    if not service: return pd.DataFrame()
    try:
        request = service.files().get_media(fileId=file_id)
        fh = io.BytesIO()
        downloader = MediaIoBaseDownload(fh, request)
        done = False
        while not done:
            status, done = downloader.next_chunk()
        fh.seek(0)
        
        df = pd.read_excel(fh, dtype={
            'ID_Pedido_Ingresado': str, 'ID_Factura_Final': str, 'SKU_Material_Ingresado': str, 
            'Codigo_Cliente': str, 'Motivo_Devolucion': str, 'Zona_OfVta': str, 'Tipo_Pedido': str, 
            'Columna_AE_Zpedidos': str
        })
        
        # Validar Estructura de Linaje antes de transformaciones
        columnas_criticas = ['ID_Pedido_Ingresado', 'ID_Factura_Final', 'SKU_Material_Ingresado', 'Codigo_Cliente', 'TOTAL', 'Zona_OfVta', 'Tipo_Pedido']
        df = validar_linaje_columnas(df, columnas_criticas)
        
        for c in df.columns:
            if df[c].dtype == object: df[c] = df[c].astype(str).str.strip()
        
        df['Fecha_Ingreso_DT'] = pd.to_datetime(df['Fecha_Ingreso'], format='%d/%m/%Y', errors='coerce')
        meses_es = {1:'Enero', 2:'Febrero', 3:'Marzo', 4:'Abril', 5:'Mayo', 6:'Junio', 7:'Julio', 8:'Agosto', 9:'Septiembre', 10:'Octubre', 11:'Noviembre', 12:'Diciembre'}
        df['Mes_Ingreso'] = df['Fecha_Ingreso_DT'].dt.month.map(meses_es).fillna("Sin Mes")
        
        df['Zona_OfVta_Clean'] = df.get('Zona_OfVta', pd.Series(["SIN ZONA"]*len(df))).astype(str).str.strip().str.upper()
        df['Canal_UI'] = df['Tipo_Pedido'].map({'GENERAL': 'COSTEÑO', 'PEDIDO BEES': 'BEES'}).fillna(df['Tipo_Pedido'])
        
        if 'Columna_AE_Zpedidos' in df.columns:
            df['Ruta_Final'] = df['Columna_AE_Zpedidos'].astype(str).str.strip()
        elif len(df.columns) > 2:
            df['Ruta_Final'] = df.iloc[:, 2].astype(str).str.strip()
        else:
            df['Ruta_Final'] = df['Zona_OfVta_Clean'].copy()
            
        df['Ruta_Final'] = df['Ruta_Final'].replace(['nan', 'None', ''], 'SIN RUTA')
        
        for col in ['Valor_Neto_Ingresado', 'TOTAL', 'Cantidad_Ingresada', 'Peso_Ingresado', 'Valor_Neto_Facturado', 'Cantidad_Facturada', 'Peso_Facturado']:
            if col in df.columns: df[col] = pd.to_numeric(df[col], errors='coerce').fillna(0)
                
        return df
    except Exception as e:
        st.error(f"❌ Error catastrófico en descarga de base: {e}")
        return pd.DataFrame()

@st.cache_data(ttl=3600)
def descargar_maestro_sku_directo(url_exportacion):
    try:
        df_sku = pd.read_excel(url_exportacion, dtype={'Material': str, 'Marca': str, 'Categoria Cuota': str})
        df_sku['Material'] = df_sku['Material'].astype(str).str.strip()
        df_sku['Marca'] = df_sku['Marca'].astype(str).str.strip().fillna("SIN MARCA")
        df_sku['Categoria Cuota'] = df_sku['Categoria Cuota'].astype(str).str.strip().fillna("SIN CATEGORIA")
        return df_sku[['Material', 'Marca', 'Categoria Cuota']].drop_duplicates('Material')
    except Exception as e:
        st.error(f"⚠️ Alerta Bypass SKU: {e}")
        return pd.DataFrame()

# --- CARGADOR PREDICTIVO PASO 8: CONSULTA Y CACHÉ BIGQUERY ML ---
@st.cache_data(ttl=3600)
def cargar_proyecciones_bigquery():
    """
    Obtiene la proyección unificada a 3 meses generada por BigQuery ML.
    Aplica caché de 1 hora para evitar re-consultas innecesarias a GCP.
    """
    try:
        info_claves = st.secrets["gcp_service_account"]
        creds = service_account.Credentials.from_service_account_info(info_claves)
        client = bigquery.Client(credentials=creds, project=info_claves.get("project_id", "dashboard-bees-costeno"))
    except Exception:
        client = bigquery.Client()
    
    # 1. Carga Métricas Mensuales de Fuga Predictiva
    query_fuga = """
        SELECT * FROM `dashboard-bees-costeno.conciliacion_ia.v_proyeccion_mensual_fuga`
        ORDER BY segmento, mes_proyectado
    """
    df_fuga = client.query(query_fuga).to_dataframe()
    
    # 2. Carga Serie Diaria Completa (para gráficos de tendencia y SKUs)
    query_diaria = """
        SELECT fecha_proyectada, segmento, metrica, eje, valor_proyectado
        FROM `dashboard-bees-costeno.conciliacion_ia.v_proyeccion_unificada`
        ORDER BY fecha_proyectada
    """
    df_diaria = client.query(query_diaria).to_dataframe()
    
    return df_fuga, df_diaria

# --- INGESTIÓN CORE ---
with st.spinner('🔄 Sincronizando y verificando linaje de bases operativas...'):
    df_base_raw = descargar_datos_maestros(FILE_ID_CONCILIACION)
    df_sku_raw  = descargar_maestro_sku_directo(URL_MAESTRO_SKU)
    
    if not df_base_raw.empty and not df_sku_raw.empty:
        df_raw = pd.merge(df_base_raw, df_sku_raw, left_on='SKU_Material_Ingresado', right_on='Material', how='left')
        df_raw['Categoria Cuota'] = df_raw['Categoria Cuota'].fillna("No Catalogado")
        df_raw['Marca'] = df_raw['Marca'].fillna("No Catalogado")
    else:
        df_raw = df_base_raw.copy()

# --- NOTIFICACIÓN VISUAL DE LINAJE SEGURO ---
if st.session_state.log_linaje["status"] == "ADVERTENCIA":
    with st.expander("⚠️ Alertas de Estructura de Datos Detectadas (Manejo Seguro Activo)"):
        for alerta in st.session_state.log_linaje["alertas"]:
            st.caption(alerta)

# --- PANEL DE CONTROL LATERAL CON ESTADOS PERSISTENTES ---
st.sidebar.title("🗂️ Parámetros de Ingestión")
st.sidebar.subheader("🎛️ Filtros Globales")

st.session_state.filtro_region = st.sidebar.selectbox(
    "📍 Región Geográfica", 
    ["LIMA", "AREQUIPA", "AMBOS"], 
    index=["LIMA", "AREQUIPA", "AMBOS"].index(st.session_state.filtro_region),
    help="Restringe todo el universo de datos del servidor según la sede operativa seleccionada."
)

st.session_state.filtro_flujo = st.sidebar.selectbox(
    "🔀 Estado de Pedido", 
    ["Ingresados", "Facturados", "Entregados"], 
    index=["Ingresados", "Facturados", "Entregados"].index(st.session_state.filtro_flujo),
    help="Define el embudo analítico base: Ingresados (universo bruto), Facturados (con ID de factura), Entregados (sin rebotes logísticos)."
)

if st.sidebar.button("🔄 Forzar Sincronización", help="Limpia el almacenamiento en caché del servidor para descargar la data en tiempo real."):
    st.cache_data.clear()
    st.rerun()

# --- PROCESAMIENTO EN EMBUDO DE MEMORIA DE PASO ÚNICO ---
df_region = df_raw.copy()
if st.session_state.filtro_region == "LIMA":
    df_region = df_raw[df_raw['Zona_OfVta_Clean'] == "LIMA"]
elif st.session_state.filtro_region == "AREQUIPA":
    df_region = df_raw[df_raw['Zona_OfVta_Clean'] == "AREQUIPA"]

df_activo = df_region.copy()
if st.session_state.filtro_flujo == "Facturados":
    df_activo = df_activo[df_activo['ID_Factura_Final'].notna() & (df_activo['ID_Factura_Final'].astype(str) != "0") & (df_activo['ID_Factura_Final'].astype(str) != "")]
elif st.session_state.filtro_flujo == "Entregados":
    df_activo = df_activo[df_activo['ID_Factura_Final'].notna() & (df_activo['ID_Factura_Final'].astype(str) != "0") & (df_activo['ID_Factura_Final'].astype(str) != "")]
    df_activo = df_activo[(df_activo['Motivo_Devolucion'].isna()) | (df_activo['Motivo_Devolucion'] == "") | (df_activo['Motivo_Devolucion'].astype(str).str.upper() == "NAN")]

meses_existentes = sorted([m for m in df_raw['Mes_Ingreso'].unique() if m != "Sin Mes"], key=lambda x: LISTA_MESES_ORDENADOS.index(x) if x in LISTA_MESES_ORDENADOS else 99)

# --- BARRA DE NAVEGACIÓN SUPERIOR ---
opciones_modulos = ["🏠 Principal", "📊 Resumen", "📈 Métricas", "🔍 Detalle", "🔮 Proyección", "🚧 En proceso"]
segmento_actual = st.segmented_control("Módulos de Sistema", options=opciones_modulos, default="🏠 Principal", label_visibility="collapsed")
if not segmento_actual: segmento_actual = "🏠 Principal"

# --- RENDERIZADO MÓDULO: PRINCIPAL ---
if segmento_actual == "🏠 Principal":
    st.title("🏠 Dashboard Principal Operativo")
    st.markdown(f"Status actual del panel: Flujo de Pedidos **{st.session_state.filtro_flujo}** | Ámbito: **{st.session_state.filtro_region}**")
    
    with st.container(border=True):
        st.subheader("📈 Evolución y Tendencia Mensual Operativa")
        
        fil1, fil2, fil3 = st.columns([1.5, 1.5, 1.2])
        with fil1:
            meses_sel = st.multiselect("📅 Filtro de Meses a comparar:", options=meses_existentes, default=meses_existentes, help="Elige los meses que deseas contrastar en la línea de tiempo temporal.")
        with fil2:
            sel_metrics = st.multiselect("📊 Selección de Métricas simultáneas:", ["GMV", "Pedidos", "Peso", "Clientes", "Pedidos Devueltos"], default=["GMV", "Pedidos"], help="Permite superponer o desglosar múltiples indicadores económicos en la gráfica.")
        with fil3:
            tipo_grafico = st.radio("📐 Estructura visual:", ["Unitario (Separados)", "Comparativo (Línea sobre línea)"], horizontal=False)

        if sel_metrics and meses_sel:
            df_trend_base = df_activo[df_activo['Mes_Ingreso'].isin(meses_sel)]
            
            df_trend = df_trend_base.groupby('Mes_Ingreso').agg(
                GMV=('TOTAL', 'sum'), Pedidos=('ID_Pedido_Ingresado', 'nunique'),
                Peso=('Peso_Ingresado', 'sum'), Clientes=('Codigo_Cliente', 'nunique')
            ).reset_index()
            
            df_devs = df_region[df_region['Motivo_Devolucion'].notna() & (df_region['Motivo_Devolucion'] != "") & (df_region['Motivo_Devolucion'].str.upper() != "NAN")]
            df_devs_group = df_devs[df_devs['Mes_Ingreso'].isin(meses_sel)].groupby('Mes_Ingreso').agg(**{'Pedidos Devueltos': ('ID_Pedido_Ingresado', 'nunique')}).reset_index()
            df_trend = pd.merge(df_trend, df_devs_group, on='Mes_Ingreso', how='left').fillna(0)
            
            df_trend['Mes_Idx'] = df_trend['Mes_Ingreso'].map(lambda x: LISTA_MESES_ORDENADOS.index(x) if x in LISTA_MESES_ORDENADOS else 99)
            df_trend = df_trend.sort_values('Mes_Idx')
            
            col_chart, col_info = st.columns([4, 1])
            with col_chart:
                if tipo_grafico == "Unitario (Separados)":
                    fig_trend = make_subplots(rows=len(sel_metrics), cols=1, shared_xaxes=True, vertical_spacing=0.08, subplot_titles=sel_metrics)
                    for i, met in enumerate(sel_metrics, 1):
                        y_vals = df_trend[met].values 
                        pct_changes = [0.0] * len(y_vals)
                        for j in range(1, len(y_vals)):
                            if y_vals[j-1] != 0: pct_changes[j] = ((y_vals[j] - y_vals[j-1]) / y_vals[j-1]) * 100
                        text_labels = [""] + [f"+{pct:.1f}%" if pct >= 0 else f"{pct:.1f}%" for pct in pct_changes[1:]]
                        text_colors = ["gray"] + ["green" if pct >= 0 else "red" for pct in pct_changes[1:]]
                        
                        fig_trend.add_trace(go.Scatter(
                            x=df_trend['Mes_Ingreso'], y=y_vals, mode='lines+markers+text',
                            text=text_labels, textposition="top center",
                            textfont=dict(color=text_colors, size=11, weight="bold"),
                            marker=dict(size=8), line=dict(width=3), name=met
                        ), row=i, col=1)
                    fig_trend.update_layout(height=220 * len(sel_metrics), showlegend=False, margin=dict(t=40, b=20, l=20, r=20))
                    st.plotly_chart(fig_trend, use_container_width=True)
                else:
                    fig_trend = go.Figure()
                    colores_palette = ['#17A2B8', '#4A3B5C', '#FFC107', '#28A745', '#DC3545']
                    for idx, met in enumerate(sel_metrics):
                        y_vals = df_trend[met].values
                        pct_changes = [0.0] * len(y_vals)
                        for j in range(1, len(y_vals)):
                            if y_vals[j-1] != 0: pct_changes[j] = ((y_vals[j] - y_vals[j-1]) / y_vals[j-1]) * 100
                        text_labels = [""] + [f"+{pct:.1f}%" if pct >= 0 else f"{pct:.1f}%" for pct in pct_changes[1:]]
                        fig_trend.add_trace(go.Scatter(
                            x=df_trend['Mes_Ingreso'], y=y_vals, mode='lines+markers+text',
                            text=text_labels, textposition="top center", textfont=dict(size=11, weight="bold"),
                            line=dict(width=3, color=colores_palette[idx % len(colores_palette)]), name=met
                        ))
                    fig_trend.update_layout(height=380, showlegend=True, margin=dict(t=30, b=20, l=20, r=20))
                    st.plotly_chart(fig_trend, use_container_width=True)

            with col_info:
                st.markdown("##### 📋 Resumen Período")
                for met in sel_metrics:
                    with st.container(border=True):
                        if met == "GMV": st.metric("Total GMV", f"S/. {df_trend_base['TOTAL'].sum():,.2f}", help="Suma de venta bruta total expresada en moneda local.")
                        elif met == "Pedidos": st.metric("Pedidos Únicos", f"{df_trend_base['ID_Pedido_Ingresado'].nunique():,}", help="Conteo neto de órdenes comerciales sin duplicar por líneas de SKU.")
                        elif met == "Peso": st.metric("Peso Total", f"{df_trend_base['Peso_Ingresado'].sum():,.1f} Kg", help="Masa logística bruta de los despachos.")
                        elif met == "Clientes": st.metric("Clientes Activos", f"{df_trend_base['Codigo_Cliente'].nunique():,}", help="Padrón único de compradores con órdenes registradas.")
                        elif met == "Pedidos Devueltos":
                            val_dev = df_devs[df_devs['Mes_Ingreso'].isin(meses_sel)]['ID_Pedido_Ingresado'].nunique()
                            st.metric("Devoluciones", f"{val_dev:,}", help="Pedidos rebotados total o parcialmente por el transporte.")
        else:
            st.info("Seleccione al menos un mes y una métrica para renderizar tendencias.")

    st.markdown("<br>", unsafe_allow_html=True)

    # --- PARTICIPACIÓN Y FUNNEL LOGÍSTICO ---
    st.subheader("📋 Desglose de Participación y Efectividad")
    m_col1, _ = st.columns([2.0, 3.0])
    with m_col1:
        mes_pie_sel = st.selectbox("📅 Seleccionar Mes de Análisis Interno:", options=meses_existentes, key="pie_compact_filter", help="Filtra el diagnóstico estático del embudo inferior.")
        
    df_pie_data = df_activo[df_activo['Mes_Ingreso'] == mes_pie_sel]
    c1, c2 = st.columns([1.8, 1.2])

    with c1:
        st.markdown("**📍 Ranking de Pedidos Únicos por Ruta**")
        df_rutas_perf = df_pie_data.groupby(['Ruta_Final', 'Canal_UI'])['ID_Pedido_Ingresado'].nunique().unstack(fill_value=0)
        if 'COSTEÑO' not in df_rutas_perf.columns: df_rutas_perf['COSTEÑO'] = 0
        if 'BEES' not in df_rutas_perf.columns: df_rutas_perf['BEES'] = 0
        df_rutas_perf = df_rutas_perf.reset_index()
        df_rutas_perf['Total_Ruta'] = df_rutas_perf['COSTEÑO'] + df_rutas_perf['BEES']
        df_rutas_perf['% BEES'] = (df_rutas_perf['BEES'] / df_rutas_perf['Total_Ruta'].replace(0, 1)) * 100
        df_rutas_perf = df_rutas_perf.rename(columns={'Ruta_Final': 'Ruta', 'COSTEÑO': 'Pedidos COSTEÑO', 'BEES': 'Pedidos BEES'})
        st.dataframe(df_rutas_perf[['Ruta', 'Pedidos COSTEÑO', 'Pedidos BEES', '% BEES']].sort_values(by='% BEES'), use_container_width=True, hide_index=True, height=310)

    with c2:
        st.markdown("**🥧 Participación de Negocio**")
        df_pie_grp = df_pie_data.groupby('Canal_UI')['ID_Pedido_Ingresado'].nunique().reset_index()
        if not df_pie_grp.empty:
            fig_pie = px.pie(df_pie_grp, values='ID_Pedido_Ingresado', names='Canal_UI', hole=0.4, color_discrete_sequence=['#4A3B5C', '#17A2B8'])
            fig_pie.update_layout(margin=dict(t=5, b=5, l=10, r=10), height=215, showlegend=False)
            st.plotly_chart(fig_pie, use_container_width=True)
            
            total_pedidos_pie = df_pie_grp['ID_Pedido_Ingresado'].sum()
            c_peds = df_pie_grp[df_pie_grp['Canal_UI']=='COSTEÑO']['ID_Pedido_Ingresado'].sum()
            b_peds = df_pie_grp[df_pie_grp['Canal_UI']=='BEES']['ID_Pedido_Ingresado'].sum()
            st.markdown(f"""
            <div style="background-color: var(--secondary-background-color); color: var(--text-color); padding: 8px 10px; border-radius: 6px; font-size: 14px; border-left: 4px solid #4A3B5C; text-align: center; line-height: 1.4;">
                <b>📌 Cuotas ({mes_pie_sel}):</b> • <b>COSTEÑO:</b> {c_peds:,} ({c_peds/total_pedidos_pie*100:.1f}%) | • <b>BEES:</b> {b_peds:,} ({b_peds/total_pedidos_pie*100:.1f}%)
            </div>
            """, unsafe_allow_html=True)

    st.markdown("---")
    st.markdown("#### ⚙️ Análisis de Efectividad Logística")
    col_g, col_t = st.columns([2.5, 1.5])
    with col_t:
        sub_c1, sub_c2, sub_c3 = st.columns([1, 4, 1])
        with sub_c2: mes_funnel = st.selectbox("📅 Mes Flujo Logístico:", options=meses_existentes, key="funnel_mes_key")
    with col_g: canal_funnel = st.radio("🏢 Segmento:", ["UNIVERSO", "BEES", "COSTEÑO"], horizontal=True, key="funnel_canal_key")

    df_f_base = df_region[df_region['Mes_Ingreso'] == mes_funnel]
    def extraer_metricas_embudo(df_fase):
        ing = df_fase['ID_Pedido_Ingresado'].nunique()
        fac = df_fase[df_fase['ID_Factura_Final'].notna() & (df_fase['ID_Factura_Final'].astype(str) != "0")]['ID_Pedido_Ingresado'].nunique()
        ent = df_fase[df_fase['ID_Factura_Final'].notna() & (df_fase['ID_Factura_Final'].astype(str) != "0") & ((df_fase['Motivo_Devolucion'].isna()) | (df_fase['Motivo_Devolucion'] == "") | (df_fase['Motivo_Devolucion'].astype(str).str.upper() == "NAN"))]['ID_Pedido_Ingresado'].nunique()
        return ing, fac, ent

    if canal_funnel != "UNIVERSO":
        ing_f, fac_f, ent_f = extraer_metricas_embudo(df_f_base[df_f_base['Canal_UI'] == canal_funnel])
    else:
        ing_f, fac_f, ent_f = extraer_metricas_embudo(df_f_base)

    with col_g:
        if ing_f > 0:
            df_stack = pd.DataFrame({"Fase": ["1. Ingreso", "2. Facturación", "3. Entrega"] * 2, "Cantidad": [ing_f, fac_f, ent_f, 0, ing_f - fac_f, ing_f - ent_f], "Tipo": ["✔️ Pasados"]*3 + ["❌ Perdidos"]*3})
            fig_stack = px.bar(df_stack, x="Fase", y="Cantidad", color="Tipo", barmode="stack", text="Cantidad", color_discrete_map={"✔️ Pasados": "#17A2B8", "❌ Perdidos": "#E74C3C"})
            fig_stack.update_layout(height=300, margin=dict(t=10, b=10, l=10, r=10), xaxis_title="", yaxis_title="Pedidos", showlegend=False)
            st.plotly_chart(fig_stack, use_container_width=True)

    with col_t:
        ing_c, fac_c, ent_c = extraer_metricas_embudo(df_f_base[df_f_base['Canal_UI']=='COSTEÑO'])
        ing_b, fac_b, ent_b = extraer_metricas_embudo(df_f_base[df_f_base['Canal_UI']=='BEES'])
        st.markdown(f"""
        <div style="font-family: monospace; font-size: 13px; background-color: var(--secondary-background-color); padding: 15px; border-radius: 8px; border: 1px solid var(--border-color); color: var(--text-color); margin-top: 15px;">
            <div style="display: flex; justify-content: space-between; font-weight: bold; margin-bottom: 10px; color:#4A3B5C; border-bottom: 2px solid var(--border-color);">
                <span style="width: 50%;">COSTEÑO</span><span style="width: 50%;">BEES</span>
            </div>
            <div style="display: flex; justify-content: space-between; margin-bottom: 4px;"><span>Facturación: {fac_c/ing_c*100 if ing_c>0 else 0:.1f}%</span><span>Facturación: {fac_b/ing_b*100 if ing_b>0 else 0:.1f}%</span></div>
            <div style="display: flex; justify-content: space-between; margin-bottom: 4px;"><span>Entrega/Fact: {ent_c/fac_c*100 if fac_c>0 else 0:.1f}%</span><span>Entrega/Fact: {ent_b/fac_b*100 if fac_b>0 else 0:.1f}%</span></div>
            <hr style="margin: 8px 0; border-top: 1px dashed var(--border-color);">
            <div style="display: flex; justify-content: space-between; font-weight: bold; color: #17A2B8;"><span>Total: {ent_c/ing_c*100 if ing_c>0 else 0:.1f}%</span><span>Total: {ent_b/ing_b*100 if ing_b>0 else 0:.1f}%</span></div>
        </div>
        """, unsafe_allow_html=True)

# --- RENDERIZADO MÓDULO: DETALLE ---
elif segmento_actual == "🔍 Detalle":
    st.title("🔍 Detalle Volumétrico y Conversión Logística")
    
    sub_filt1, _ = st.columns([2.0, 3.0])
    with sub_filt1:
        st.session_state.filtro_mes_detalle = st.selectbox(
            "📅 Seleccionar Mes de Enfoque para Detalle:", 
            options=meses_existentes, 
            index=meses_existentes.index(st.session_state.filtro_mes_detalle) if st.session_state.filtro_mes_detalle in meses_existentes else 0,
            help="Sincroniza de forma persistente el periodo local de auditoría estructural para las tarjetas espejo."
        )
        
    df_detalle_activo = df_activo[df_activo['Mes_Ingreso'] == st.session_state.filtro_mes_detalle]
    st.subheader("📊 Distribución Estructural de Operaciones por Canal")
    
    fila1_col1, fila1_col2 = st.columns(2)
    fila2_col1, fila2_col2 = st.columns(2)
    
    peds_c = df_detalle_activo[df_detalle_activo['Canal_UI'] == 'COSTEÑO']['ID_Pedido_Ingresado'].nunique()
    peds_b = df_detalle_activo[df_detalle_activo['Canal_UI'] == 'BEES']['ID_Pedido_Ingresado'].nunique()
    tot_peds = peds_c + peds_b
    
    cli_c = df_detalle_activo[df_detalle_activo['Canal_UI'] == 'COSTEÑO']['Codigo_Cliente'].nunique()
    cli_b = df_detalle_activo[df_detalle_activo['Canal_UI'] == 'BEES']['Codigo_Cliente'].nunique()
    tot_cli = cli_c + cli_b
    
    peso_c = df_detalle_activo[df_detalle_activo['Canal_UI'] == 'COSTEÑO']['Peso_Ingresado'].sum() / 1000
    peso_b = df_detalle_activo[df_detalle_activo['Canal_UI'] == 'BEES']['Peso_Ingresado'].sum() / 1000
    tot_peso = peso_c + peso_b
    
    gmv_c = df_detalle_activo[df_detalle_activo['Canal_UI'] == 'COSTEÑO']['TOTAL'].sum() / TC_FIJO
    gmv_b = df_detalle_activo[df_detalle_activo['Canal_UI'] == 'BEES']['TOTAL'].sum() / TC_FIJO
    tot_gmv = gmv_c + gmv_b

    def renderizar_bloque_espejo(columna_target, titulo, total_formateado, val_c, val_b, total_numerico, tooltip, sufijo=""):
        with columna_target:
            with st.container(border=True):
                st.markdown(f"##### {titulo}")
                sub_izq, sub_der = st.columns([1.6, 1.4])
                
                pct_c = (val_c / total_numerico * 100) if total_numerico > 0 else 0
                pct_b = (val_b / total_numerico * 100) if total_numerico > 0 else 0
                val_c_disp = f"{val_c:,.2f}" if isinstance(val_c, float) else f"{val_c:,}"
                val_b_disp = f"{val_b:,.2f}" if isinstance(val_b, float) else f"{val_b:,}"
                
                with sub_izq:
                    st.metric("Volumen Consolidado", total_formateado, help=tooltip, label_visibility="collapsed")
                    st.markdown(f"""
                    <div style="font-family: sans-serif; font-size: 14px; margin-top:12px; line-height:1.6;">
                        <span style="color:#4A3B5C; font-weight:bold;">■ COSTEÑO:</span> {val_c_disp} {sufijo} <b style="color:gray;">({pct_c:.1f}%)</b><br>
                        <span style="color:#17A2B8; font-weight:bold;">■ BEES:</span> {val_b_disp} {sufijo} <b style="color:gray;">({pct_b:.1f}%)</b>
                    </div>
                    """, unsafe_allow_html=True)
                with sub_der:
                    if total_numerico > 0:
                        fig = go.Figure(data=[go.Pie(labels=['COSTEÑO', 'BEES'], values=[val_c, val_b], hole=0.48, marker=dict(colors=['#4A3B5C', '#17A2B8']), textinfo='none')])
                        fig.update_layout(margin=dict(t=5, b=5, l=5, r=5), height=130, showlegend=False)
                        st.plotly_chart(fig, use_container_width=True, key=f"dona_{titulo.replace(' ', '_')}")

    renderizar_bloque_espejo(fila1_col1, "📦 Pedidos Únicos", f"{tot_peds:,} und", peds_c, peds_b, tot_peds, "Conteo neto de transacciones comerciales independientes.", "und")
    renderizar_bloque_espejo(fila1_col2, "👥 Clientes Únicos", f"{tot_cli:,} cli", cli_c, cli_b, tot_cli, "Padrón neto de puntos de venta con transacciones en el periodo.", "cli")
    renderizar_bloque_espejo(fila2_col1, "⚖️ Peso Total", f"{tot_peso:,.2f} TN", peso_c, peso_b, tot_peso, "Masa calculada en Toneladas Métricas (Kilogramos base divididos entre 1,000).", "TN")
    renderizar_bloque_espejo(fila2_col2, "💵 Capital Total", f"$ {tot_gmv:,.2f}", gmv_c, gmv_b, tot_gmv, f"Monto financiero dolarizado aplicando la tasa corporativa mandatoria de S/. {TC_FIJO}.", "USD")

    st.markdown("<br>", unsafe_allow_html=True)
    st.subheader("⚙️ Rendimiento de Etapas y Efectividad del Canal")
    
    st.session_state.filtro_canal_log = st.segmented_control(
        "Filtrar Canal Logístico:", 
        options=["UNIVERSO", "BEES", "COSTEÑO"], 
        default=st.session_state.filtro_canal_log,
        help="Aísla de forma persistente la visualización de la matriz de conversión secuencial."
    )
    if not st.session_state.filtro_canal_log: st.session_state.filtro_canal_log = "UNIVERSO"
    
    def obtener_volumen_etapas(df_segmento):
        ingresados = df_segmento['ID_Pedido_Ingresado'].nunique()
        facturados = df_segmento[df_segmento['ID_Factura_Final'].notna() & (df_segmento['ID_Factura_Final'].astype(str) != "0") & (df_segmento['ID_Factura_Final'].astype(str) != "")]["ID_Pedido_Ingresado"].nunique()
        entregados = df_segmento[df_segmento['ID_Factura_Final'].notna() & (df_segmento['ID_Factura_Final'].astype(str) != "0") & (df_segmento['ID_Factura_Final'].astype(str) != "") & ((df_segmento['Motivo_Devolucion'].isna()) | (df_segmento['Motivo_Devolucion'] == "") | (df_segmento['Motivo_Devolucion'].astype(str).str.upper() == "NAN"))]['ID_Pedido_Ingresado'].nunique()
        return ingresados, facturados, entregados

    with st.container(border=True):
        st.markdown("#### 📑 Matriz de Conversión Logística por Canal Comercial", help="Análisis secuencial paso a paso: Tasa Facturación (Ingreso ➔ Facturado) y Tasa Entrega (Facturado ➔ Entregado Real sin Devoluciones).")
        ing_cost, fac_cost, ent_cost = obtener_volumen_etapas(df_detalle_activo[df_detalle_activo['Canal_UI'] == 'COSTEÑO'])
        ing_bees, fac_bees, ent_bees = obtener_volumen_etapas(df_detalle_activo[df_detalle_activo['Canal_UI'] == 'BEES'])
        
        df_matriz_final = pd.DataFrame({
            "Canal Comercial": ["COSTEÑO", "BEES"],
            "1. Ingreso (Base)": [f"{ing_cost:,} und", f"{ing_bees:,} und"],
            " Tasa Facturación (% Cambio)": [f"{fac_cost/ing_cost*100 if ing_cost>0 else 0:.1f}%", f"{fac_bees/ing_bees*100 if ing_bees>0 else 0:.1f}%"],
            "2. Facturado": [f"{fac_cost:,} und", f"{fac_bees:,} und"],
            " Tasa Entrega (% Cambio)": [f"{ent_cost/fac_cost*100 if fac_cost>0 else 0:.1f}%", f"{ent_bees/fac_bees*100 if fac_bees>0 else 0:.1f}%"],
            "3. Entregado Real": [f"{ent_cost:,} und", f"{ent_bees:,} und"],
            "🚀 Efectividad Final Total": [f"{ent_cost/ing_cost*100 if ing_cost>0 else 0:.2f}%", f"{ent_bees/ing_bees*100 if ing_bees>0 else 0:.2f}%"]
        })
        
        if st.session_state.filtro_canal_log != "UNIVERSO":
            df_matriz_final = df_matriz_final[df_matriz_final['Canal Comercial'] == st.session_state.filtro_canal_log]
        st.dataframe(df_matriz_final, use_container_width=True, hide_index=True)

# --- RENDERIZADO MÓDULO PREDICTIVO: PROYECCIÓN (PASO 8 COMPLETO) ---
elif segmento_actual == "🔮 Proyección":
    st.title("🔮 Proyección Inteligente a 3 Meses (BigQuery ML ARIMA_PLUS)")
    st.caption("Fuga Predictiva, Demanda vs Facturación y Volumen Top SKUs Líderes (en Miles de Unidades)")
    
    try:
        df_fuga, df_diaria = cargar_proyecciones_bigquery()
        
        # Selector de Segmento Comercial / Canal Logístico
        segmentos_disponibles = ['UNIVERSO', 'PEDIDO BEES', 'GENERAL']
        
        segmento_sel = st.selectbox(
            "🌐 Seleccionar Canal Logístico / Segmento:", 
            segmentos_disponibles,
            index=0,
            help="Aísla el modelo predictivo de BigQuery ML por canal: UNIVERSO (Consolidado), PEDIDO BEES o GENERAL (Costeño)."
        )
        
        # Filtrar dataframes por segmento
        df_fuga_seg = df_fuga[df_fuga['segmento'] == segmento_sel].copy()
        df_diaria_seg = df_diaria[df_diaria['segmento'] == segmento_sel].copy()

        # -------------------------------------------------------------------------
        # BLOQUE 1: KPIs RESUMEN ACUMULADO (3 MESES / 90 DÍAS)
        # -------------------------------------------------------------------------
        st.subheader("📊 Totales Proyectados para los Próximos 90 Días")
        
        tot_dinero_ingresado = df_fuga_seg['dinero_ingresado_soles'].sum() if 'dinero_ingresado_soles' in df_fuga_seg.columns else 0
        tot_dinero_facturado = df_fuga_seg['dinero_facturado_soles'].sum() if 'dinero_facturado_soles' in df_fuga_seg.columns else 0
        tot_fuga_dinero = df_fuga_seg['fuga_dinero_soles'].sum() if 'fuga_dinero_soles' in df_fuga_seg.columns else 0
        pct_fuga_prom = (tot_fuga_dinero / tot_dinero_ingresado * 100) if tot_dinero_ingresado > 0 else 0
        tot_peso_ingresado = df_fuga_seg['peso_ingresado_toneladas'].sum() if 'peso_ingresado_toneladas' in df_fuga_seg.columns else 0

        kpi1, kpi2, kpi3, kpi4 = st.columns(4)
        kpi1.metric(
            "Demanda Total (S/.)", 
            f"S/ {tot_dinero_ingresado:,.2f}", 
            help=f"Equivalente a USD ${tot_dinero_ingresado/TC_FIJO:,.2f} (Tasa Corporativa Fija: {TC_FIJO})"
        )
        kpi2.metric(
            "Facturación Estimada (S/.)", 
            f"S/ {tot_dinero_facturado:,.2f}",
            delta=f"-S/ {tot_fuga_dinero:,.2f} Fuga"
        )
        kpi3.metric(
            "Tasa de Fuga Predictiva", 
            f"{pct_fuga_prom:.2f}%", 
            delta_color="inverse",
            help="Porcentaje estimado de la demanda que no se convertirá en dinero facturado de caja."
        )
        kpi4.metric(
            "Peso Demanda (Tn)", 
            f"{tot_peso_ingresado:,.2f} Tn",
            help="Masa total proyectada en Toneladas Métricas para planificación logitudinal."
        )

        st.divider()

        # -------------------------------------------------------------------------
        # BLOQUE 2: TENDENCIA DIARIA Y DESGLOSE MENSUAL (DEMANDA VS OPERACIÓN)
        # -------------------------------------------------------------------------
        col_graf, col_tabla = st.columns([6, 4])
        
        with col_graf:
            st.subheader("📈 Tendencia Diaria: Demanda vs Facturación")
            df_diaria_dinero = df_diaria_seg[df_diaria_seg['metrica'].isin(['dinero_ingresado', 'dinero_facturado'])].copy()
            
            if not df_diaria_dinero.empty:
                fig_pred = px.line(
                    df_diaria_dinero,
                    x='fecha_proyectada',
                    y='valor_proyectado',
                    color='metrica',
                    labels={'metrica': 'Eje Comercial', 'valor_proyectado': 'Monto (S/.)', 'fecha_proyectada': 'Fecha'},
                    color_discrete_map={'dinero_ingresado': '#17A2B8', 'dinero_facturado': '#4A3B5C'}
                )
                fig_pred.update_layout(
                    height=380, 
                    margin=dict(l=10, r=10, t=30, b=10),
                    legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1)
                )
                st.plotly_chart(fig_pred, use_container_width=True)
            else:
                st.info("Sin registros diarios de montos financieros para graficar.")

        with col_tabla:
            st.subheader("📋 Desglose Mensual y Fuga")
            columnas_visibles = [
                'nombre_mes', 'dinero_ingresado_soles', 'dinero_facturado_soles', 
                'fuga_dinero_soles', 'pct_fuga_dinero'
            ]
            cols_existentes = [c for c in columnas_visibles if c in df_fuga_seg.columns]
            
            if not df_fuga_seg.empty and len(cols_existentes) > 0:
                df_tabla_fuga = df_fuga_seg[cols_existentes].rename(columns={
                    'nombre_mes': 'Mes',
                    'dinero_ingresado_soles': 'Demanda (S/.)',
                    'dinero_facturado_soles': 'Facturado (S/.)',
                    'fuga_dinero_soles': 'Fuga (S/.)',
                    'pct_fuga_dinero': '% Fuga'
                })
                st.dataframe(df_tabla_fuga, use_container_width=True, hide_index=True, height=300)
            else:
                st.info("Sin datos de agregación mensual.")

        st.divider()

        # -------------------------------------------------------------------------
        # BLOQUE 3: PROYECCIÓN TOP SKUs (EN MILES DE UNIDADES)
        # -------------------------------------------------------------------------
        st.subheader("📦 Proyección de Volumen para Top SKUs Líderes (en Miles de Unidades)")
        
        df_skus = df_diaria_seg[df_diaria_seg['metrica'].str.startswith('SKU_')].copy()
        if not df_skus.empty:
            df_skus['sku'] = df_skus['metrica'].str.replace('SKU_', '')
            df_skus_agrupado = df_skus.groupby('sku')['valor_proyectado'].sum() / 1000.0  # Expresado en Miles
            df_skus_agrupado = df_skus_agrupado.reset_index().sort_values('valor_proyectado', ascending=False)
            
            fig_sku = px.bar(
                df_skus_agrupado,
                x='sku',
                y='valor_proyectado',
                text_auto='.2f',
                labels={'sku': 'Código SKU', 'valor_proyectado': 'Miles de Unidades'},
                color='valor_proyectado',
                color_continuous_scale='Purples'
            )
            fig_sku.update_layout(height=350, margin=dict(l=10, r=10, t=30, b=10))
            st.plotly_chart(fig_sku, use_container_width=True)
        else:
            st.info("No hay series temporales de SKUs registradas para este segmento.")

    except Exception as e:
        st.error(f"❌ Error al conectar con las vistas de BigQuery ML: {e}")
        st.info("Verifica que las credenciales `st.secrets['gcp_service_account']` estén configuradas y que la vista `v_proyeccion_mensual_fuga` haya sido creada en GCP.")

# --- RENDERIZADO MÓDULOS EN DESARROLLO ---
elif segmento_actual in ["📊 Resumen", "📈 Métricas", "🚧 En proceso"]:
    st.title(f"{segmento_actual}")
    st.info("Módulo analítico estructurado en caché. Listo para inyección lógica.")
