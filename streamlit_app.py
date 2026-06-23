import streamlit as st
import pandas as pd
import numpy as np
import plotly.express as px
import plotly.graph_objects as go
from plotly.subplots import make_subplots
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseDownload
from google.oauth2 import service_account
import io
import time

# --- CONFIGURACIÓN DE LA PÁGINA WEB ---
st.set_page_config(
    page_title="App Conciliación BEES & COSTEÑO",
    page_icon="📊",
    layout="wide",
    initial_sidebar_state="expanded"
)

# --- CONSTANTES ---
TC_FIJO = 3.396
LISTA_MESES_ORDENADOS = ['Enero', 'Febrero', 'Marzo', 'Abril', 'Mayo', 'Junio', 'Julio', 'Agosto', 'Septiembre', 'Octubre', 'Noviembre', 'Diciembre']

FILE_ID_CONCILIACION = "1-EoM0rYAmYY_tBkKwL5--746cdUa0tw2"
URL_MAESTRO_SKU = "https://docs.google.com/spreadsheets/d/1r1aJNiDvArFqEfAGJ6i8hq_zAo8G5lAc7uW6pXhylZo/export?format=xlsx&gid=1445055226"

# --- CONEXIÓN DRIVE ---
@st.cache_resource
def obtener_servicio_drive():
    try:
        info_claves = st.secrets["gcp_service_account"]
        creds = service_account.Credentials.from_service_account_info(info_claves)
        return build('drive', 'v3', credentials=creds)
    except Exception as e:
        st.error(f"❌ Error de autenticación en Drive: {e}")
        return None

# --- DESCARGA DE DATOS ---
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
        
        df = pd.read_excel(fh, dtype={'ID_Pedido_Ingresado': str, 'ID_Factura_Final': str, 'SKU_Material_Ingresado': str, 'Codigo_Cliente': str, 'Motivo_Devolucion': str, 'Zona_OfVta': str, 'Tipo_Pedido': str})
        
        for c in df.columns:
            if df[c].dtype == object: df[c] = df[c].astype(str).str.strip()
        
        df['Fecha_Ingreso_DT'] = pd.to_datetime(df['Fecha_Ingreso'], format='%d/%m/%Y', errors='coerce')
        meses_es = {1:'Enero', 2:'Febrero', 3:'Marzo', 4:'Abril', 5:'Mayo', 6:'Junio', 7:'Julio', 8:'Agosto', 9:'Septiembre', 10:'Octubre', 11:'Noviembre', 12:'Diciembre'}
        df['Mes_Ingreso'] = df['Fecha_Ingreso_DT'].dt.month.map(meses_es).fillna("Sin Mes")
        
        df['Zona_OfVta_Clean'] = df.get('Zona_OfVta', pd.Series(["SIN ZONA"]*len(df))).astype(str).str.strip().str.upper()
        df['Canal_UI'] = df['Tipo_Pedido'].map({'GENERAL': 'COSTEÑO', 'PEDIDO BEES': 'BEES'}).fillna(df['Tipo_Pedido'])
        
        for col in ['Valor_Neto_Ingresado', 'TOTAL', 'Cantidad_Ingresada', 'Peso_Ingresado', 'Valor_Neto_Facturado', 'Cantidad_Facturada', 'Peso_Facturado']:
            if col in df.columns: df[col] = pd.to_numeric(df[col], errors='coerce').fillna(0)
                
        return df
    except Exception as e:
        st.error(f"❌ Error al descargar Base de Conciliación: {e}")
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

# --- SPINNER DE INGESTIÓN ---
with st.spinner('🔄 Sincronizando y procesando bases de datos operativas...'):
    df_base_raw = descargar_datos_maestros(FILE_ID_CONCILIACION)
    df_sku_raw  = descargar_maestro_sku_directo(URL_MAESTRO_SKU)
    
    if not df_base_raw.empty and not df_sku_raw.empty:
        df_raw = pd.merge(df_base_raw, df_sku_raw, left_on='SKU_Material_Ingresado', right_on='Material', how='left')
        df_raw['Categoria Cuota'] = df_raw['Categoria Cuota'].fillna("No Catalogado")
        df_raw['Marca'] = df_raw['Marca'].fillna("No Catalogado")
    else:
        df_raw = df_base_raw.copy()

# --- SEGMENTACIÓN DE LA APLICACIÓN ---
st.sidebar.title("Navegación del Sistema")
segmento_actual = st.sidebar.radio(
    "Seleccione un módulo:",
    ["🏠 Principal", "📊 Resumen", "📈 Métricas", "🔍 Análisis", "🚧 En proceso"]
)

st.sidebar.divider()

# --- LÓGICA DE SEGMENTOS ---
if segmento_actual == "🏠 Principal":
    
    st.sidebar.subheader("🎛️ Filtros Principales")
    opcion_region = st.sidebar.selectbox("📍 Región Geográfica", ["Lima", "Arequipa", "Ver Todo"], index=2)
    estado_flujo_sel = st.sidebar.selectbox("🔀 Estado de Pedido", ["Ingresados", "Facturados", "Entregados"], index=0)
    
    if st.sidebar.button("🔄 Forzar Sincronización"):
        st.cache_data.clear()
        st.rerun()

    # FILTRADO CORE POR REGIÓN
    df_region = df_raw.copy()
    if opcion_region == "Lima":
        df_region = df_raw[df_raw['Zona_OfVta_Clean'] == "LIMA"]
    elif opcion_region == "Arequipa":
        df_region = df_raw[df_raw['Zona_OfVta_Clean'] == "AREQUIPA"]

    st.title("🏠 Dashboard Principal Operativo")
    st.markdown("Visualización de las métricas primarias de tracción y efectividad logística.")
    
    # --- PARTE 1: EVOLUCIÓN Y TENDENCIA MENSUAL (MULTI-SELECCIÓN) ---
    with st.container(border=True):
        st.subheader("📈 Evolución y Tendencia Mensual Operativa")
        
        metricas_disp = {
            "GMV": ("TOTAL", "S/. {:,.2f}"),
            "Pedidos": ("ID_Pedido_Ingresado", "{:,.0f} und"),
            "Peso": ("Peso_Ingresado", "{:,.1f} Kg"),
            "Clientes": ("Codigo_Cliente", "{:,.0f} cli"),
            "Pedidos Devueltos": ("Devoluciones", "{:,.0f} und")
        }
        
        sel_metrics = st.multiselect(
            "Seleccione las métricas a visualizar simultáneamente:",
            list(metricas_disp.keys()),
            default=["GMV", "Pedidos"]
        )
        
        if sel_metrics:
            # Preparación del DataFrame Cronológico
            df_trend = df_region.groupby('Mes_Ingreso').agg(
                GMV=('TOTAL', 'sum'),
                Pedidos=('ID_Pedido_Ingresado', 'nunique'),
                Peso=('Peso_Ingresado', 'sum'),
                Clientes=('Codigo_Cliente', 'nunique')
            ).reset_index()
            
            # Cálculo especial para devoluciones
            df_devs = df_region[df_region['Motivo_Devolucion'].notna() & (df_region['Motivo_Devolucion'] != "") & (df_region['Motivo_Devolucion'].str.upper() != "NAN")]
            df_devs_group = df_devs.groupby('Mes_Ingreso').agg(**{'Pedidos Devueltos': ('ID_Pedido_Ingresado', 'nunique')}).reset_index()
            df_trend = pd.merge(df_trend, df_devs_group, on='Mes_Ingreso', how='left').fillna(0)
            
            # Ordenar por mes cronológicamente
            df_trend['Mes_Idx'] = df_trend['Mes_Ingreso'].map(lambda x: LISTA_MESES_ORDENADOS.index(x) if x in LISTA_MESES_ORDENADOS else 99)
            df_trend = df_trend.sort_values('Mes_Idx')
            
            # Gráfico Multi-Métrica Subplots
            fig_trend = make_subplots(rows=len(sel_metrics), cols=1, shared_xaxes=True, vertical_spacing=0.08, subplot_titles=sel_metrics)
            
            for i, met in enumerate(sel_metrics, 1):
                # 🛠️ CORRECCIÓN: Se llama directamente a 'met' porque df_trend ya posee las columnas renombradas.
                formato = metricas_disp[met][1]
                y_vals = df_trend[met].values 
                
                # Cálculo de porcentaje MoM (Month-over-Month)
                pct_changes = [0.0] * len(y_vals)
                for j in range(1, len(y_vals)):
                    if y_vals[j-1] != 0:
                        pct_changes[j] = ((y_vals[j] - y_vals[j-1]) / y_vals[j-1]) * 100
                
                # Definición de Textos y Colores para el %
                text_labels = []
                text_colors = []
                for j, pct in enumerate(pct_changes):
                    if j == 0:
                        text_labels.append("")
                        text_colors.append("gray")
                    else:
                        text_labels.append(f"+{pct:.1f}%" if pct >= 0 else f"{pct:.1f}%")
                        text_colors.append("green" if pct >= 0 else "red")
                
                fig_trend.add_trace(go.Scatter(
                    x=df_trend['Mes_Ingreso'], 
                    y=y_vals,
                    mode='lines+markers+text',
                    text=text_labels,
                    textposition="top center",
                    textfont=dict(color=text_colors, size=12, weight="bold"),
                    marker=dict(size=8, color="#4A3B5C"),
                    line=dict(width=3, color="#17A2B8"),
                    hovertemplate=f"<b>%{{x}}</b><br>{met}: {formato.replace('{:', '%{y:').replace('}', '}')}<extra></extra>"
                ), row=i, col=1)
                
                fig_trend.update_yaxes(title_text="", row=i, col=1)

            fig_trend.update_layout(height=250 * len(sel_metrics), showlegend=False, margin=dict(t=40, b=20, l=20, r=20))
            st.plotly_chart(fig_trend, use_container_width=True)
        else:
            st.info("👆 Selecciona al menos una métrica para visualizar la tendencia.")

    st.markdown("<br>", unsafe_allow_html=True)

    # --- PARTE 2: AUDITORÍA DETALLADA (INFERIOR) ---
    st.subheader("📋 Desglose de Participación y Efectividad")
    
    # Filtros locales compactos
    f_col1, f_col2 = st.columns([1, 2])
    meses_validos = [m for m in LISTA_MESES_ORDENADOS if m in df_region['Mes_Ingreso'].unique()]
    with f_col1:
        mes_detalle = st.selectbox("📅 Seleccione Mes:", options=meses_validos)
    with f_col2:
        canal_detalle = st.radio("🏢 Parte del Negocio:", ["UNIVERSO", "BEES", "COSTEÑO"], horizontal=True)

    # Filtrar datos de la sección inferior
    df_mes = df_region[df_region['Mes_Ingreso'] == mes_detalle]
    df_estado = df_mes.copy()
    
    if canal_detalle != "UNIVERSO":
        df_estado = df_estado[df_estado['Canal_UI'] == canal_detalle]

    c1, c2, c3 = st.columns([1.2, 1, 1.3])

    with c1:
        # Ranking de Rutas
        st.markdown("**📍 Ranking de Pedidos Únicos por Ruta**")
        df_rutas = df_estado.groupby('Zona_OfVta_Clean')['ID_Pedido_Ingresado'].nunique().reset_index()
        df_rutas.columns = ['Ruta (Zona)', 'Total Pedidos']
        df_rutas = df_rutas.sort_values('Total Pedidos', ascending=False)
        st.dataframe(df_rutas, use_container_width=True, hide_index=True)

    with c2:
        st.markdown("**🥧 Participación de Negocio**")
        if canal_detalle == "UNIVERSO":
            df_pie = df_mes.groupby('Canal_UI')['ID_Pedido_Ingresado'].nunique().reset_index()
            if not df_pie.empty:
                fig_pie = px.pie(df_pie, values='ID_Pedido_Ingresado', names='Canal_UI', hole=0.5, color_discrete_sequence=['#4A3B5C', '#17A2B8'])
                fig_pie.update_layout(margin=dict(t=0, b=0, l=0, r=0), height=220)
                st.plotly_chart(fig_pie, use_container_width=True)
            else:
                st.info("Sin datos.")
        else:
            st.info(f"Visualizando únicamente el 100% de {canal_detalle}. Selecciona 'UNIVERSO' para ver la comparativa.")

    with c3:
        st.markdown("**⚙️ Efectividad por Fases**")
        
        # Función para calcular embudo
        def calc_efectividad(df_fase):
            ing = df_fase['ID_Pedido_Ingresado'].nunique()
            fac = df_fase[df_fase['ID_Factura_Final'].notna() & (df_fase['ID_Factura_Final'].astype(str) != "0") & (df_fase['ID_Factura_Final'].astype(str) != "")]['ID_Pedido_Ingresado'].nunique()
            
            df_facs = df_fase[df_fase['ID_Factura_Final'].notna() & (df_fase['ID_Factura_Final'].astype(str) != "0")]
            ent = df_facs[(df_facs['Motivo_Devolucion'].isna()) | (df_facs['Motivo_Devolucion'] == "") | (df_facs['Motivo_Devolucion'].astype(str).str.upper() == "NAN")]['ID_Pedido_Ingresado'].nunique()
            
            p_fac = (fac / ing * 100) if ing > 0 else 0
            p_ent = (ent / fac * 100) if fac > 0 else 0
            p_tot = (ent / ing * 100) if ing > 0 else 0
            return ing, p_fac, p_ent, p_tot

        _, ef_c_fac, ef_c_ent, ef_c_tot = calc_efectividad(df_mes[df_mes['Canal_UI'] == 'COSTEÑO'])
        _, ef_b_fac, ef_b_ent, ef_b_tot = calc_efectividad(df_mes[df_mes['Canal_UI'] == 'BEES'])

        html_efectividad = f"""
        <div style="font-family: monospace; background-color: #f8f9fa; padding: 15px; border-radius: 8px; border: 1px solid #ddd; color: #333;">
            <div style="display: flex; justify-content: space-between; font-weight: bold; margin-bottom: 10px; color:#4A3B5C;">
                <span style="width: 50%;">COSTEÑO</span>
                <span style="width: 50%;">BEES</span>
            </div>
            <div style="display: flex; justify-content: space-between;">
                <span style="width: 50%;">Ingreso: 100%</span>
                <span style="width: 50%;">Ingreso: 100%</span>
            </div>
            <div style="display: flex; justify-content: space-between;">
                <span style="width: 50%;">Facturados: {ef_c_fac:.2f}%</span>
                <span style="width: 50%;">Facturados: {ef_b_fac:.2f}%</span>
            </div>
            <div style="display: flex; justify-content: space-between;">
                <span style="width: 50%;">Entregados: {ef_c_ent:.2f}%</span>
                <span style="width: 50%;">Entregados: {ef_b_ent:.2f}%</span>
            </div>
            <hr style="margin: 8px 0; border-top: 1px dashed #ccc;">
            <div style="display: flex; justify-content: space-between; font-weight: bold;">
                <span style="width: 50%;">Total: {ef_c_tot:.2f}%</span>
                <span style="width: 50%;">Total: {ef_b_tot:.2f}%</span>
            </div>
        </div>
        """
        st.markdown(html_efectividad, unsafe_allow_html=True)

elif segmento_actual == "📊 Resumen":
    st.title("📊 Resumen Ejecutivo")
    st.info("🚧 Módulo en construcción. Aquí migraremos el resumen general del cruce y auditoría base.")

elif segmento_actual == "📈 Métricas":
    st.title("📈 Métricas Comerciales y Logísticas")
    st.info("🚧 Módulo en construcción. Se destinará al análisis específico de SKU, Ticket Promedio y Densidad.")

elif segmento_actual == "🔍 Análisis":
    st.title("🔍 Análisis Profundo (Deep Dive)")
    st.info("🚧 Módulo en construcción. Se implementará el análisis de Pareto (Score de Clientes Críticos) y Devoluciones por Macrocategoría.")

else:
    st.title("🚧 En proceso")
    st.info("Espacio reservado para futuras implementaciones de Ciencia de Datos.")
