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
        
        df = pd.read_excel(fh, dtype={'ID_Pedido_Ingresado': str, 'ID_Factura_Final': str, 'SKU_Material_Ingresado': str, 'Codigo_Cliente': str, 'Motivo_Devolucion': str, 'Zona_OfVta': str, 'Tipo_Pedido': str, 'Columna_AE_Zpedidos': str})
        
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

# --- BARRA DE NAVEGACIÓN SUPERIOR ---
opciones_modulos = ["🏠 Principal", "📊 Resumen", "📈 Métricas", "🔍 Detalle", "🔮 Proyección", "🚧 En proceso"]

segmento_actual = st.segmented_control(
    "Módulos de Sistema",
    options=opciones_modulos,
    default="🏠 Principal",
    label_visibility="collapsed"
)

if not segmento_actual:
    segmento_actual = "🏠 Principal"

# --- CONTROL LATERAL: PARÁMETROS GLOBALES ---
st.sidebar.title("🗂️ Parámetros de Ingestión")
st.sidebar.subheader("🎛️ Filtros Globales")

# Corrección a la lista de Regiones solicitada (LIMA-AREQUIPA-AMBOS)
opcion_region = st.sidebar.selectbox("📍 Región Geográfica", ["LIMA", "AREQUIPA", "AMBOS"], index=2)
estado_flujo_sel = st.sidebar.selectbox("🔀 Estado de Pedido", ["Ingresados", "Facturados", "Entregados"], index=0)

# Mantenimiento y selección global del mes desde la barra lateral
meses_existentes = sorted([m for m in df_raw['Mes_Ingreso'].unique() if m != "Sin Mes"], key=lambda x: LISTA_MESES_ORDENADOS.index(x) if x in LISTA_MESES_ORDENADOS else 99)
mes_global_sel = st.sidebar.selectbox("📅 Seleccionar Mes", options=meses_existentes, index=0)

if st.sidebar.button("🔄 Forzar Sincronización"):
    st.cache_data.clear()
    st.rerun()

# --- LÓGICA DE FILTRADO CORE ---
df_region = df_raw.copy()
if opcion_region == "LIMA":
    df_region = df_raw[df_raw['Zona_OfVta_Clean'] == "LIMA"]
elif opcion_region == "AREQUIPA":
    df_region = df_raw[df_raw['Zona_OfVta_Clean'] == "AREQUIPA"]

# Filtrar por el mes global seleccionado
df_mes_activo = df_region[df_region['Mes_Ingreso'] == mes_global_sel]

df_activo = df_mes_activo.copy()
if estado_flujo_sel == "Facturados":
    df_activo = df_activo[df_activo['ID_Factura_Final'].notna() & (df_activo['ID_Factura_Final'].astype(str) != "0") & (df_activo['ID_Factura_Final'].astype(str) != "")]
elif estado_flujo_sel == "Entregados":
    df_activo = df_activo[df_activo['ID_Factura_Final'].notna() & (df_activo['ID_Factura_Final'].astype(str) != "0") & (df_activo['ID_Factura_Final'].astype(str) != "")]
    df_activo = df_activo[(df_activo['Motivo_Devolucion'].isna()) | (df_activo['Motivo_Devolucion'] == "") | (df_activo['Motivo_Devolucion'].astype(str).str.upper() == "NAN")]


# --- RENDERING DE SEGMENTOS ---
if segmento_actual == "🏠 Principal":
    st.title("🏠 Dashboard Principal Operativo")
    st.markdown(f"Status actual del panel: Flujo de Pedidos **{estado_flujo_sel}** en **{mes_global_sel}** ({opcion_region})")
    
    # --- PARTE 1: EVOLUCIÓN Y TENDENCIA MENSUAL OPERATIVA ---
    with st.container(border=True):
        st.subheader("📈 Evolución y Tendencia Mensual Operativa")
        
        fil1, fil2, fil3 = st.columns([1.5, 1.5, 1.2])
        with fil1:
            meses_sel = st.multiselect("📅 Filtro de Meses a comparar:", options=meses_existentes, default=meses_existentes)
        with fil2:
            metricas_disp = {
                "GMV": ("TOTAL", "S/. {:,.2f}"),
                "Pedidos": ("ID_Pedido_Ingresado", "{:,.0f} und"),
                "Peso": ("Peso_Ingresado", "{:,.1f} Kg"),
                "Clientes": ("Codigo_Cliente", "{:,.0f} cli"),
                "Pedidos Devueltos": ("Devoluciones", "{:,.0f} und")
            }
            sel_metrics = st.multiselect("📊 Selección de Métricas simultáneas:", list(metricas_disp.keys()), default=["GMV", "Pedidos"])
        with fil3:
            tipo_grafico = st.radio("📐 Estructura visual:", ["Unitario (Separados)", "Comparativo (Línea sobre línea)"], horizontal=False)

        if sel_metrics and meses_sel:
            df_trend_base = df_activo[df_activo['Mes_Ingreso'].isin(meses_sel)]
            
            df_trend = df_trend_base.groupby('Mes_Ingreso').agg(
                GMV=('TOTAL', 'sum'),
                Pedidos=('ID_Pedido_Ingresado', 'nunique'),
                Peso=('Peso_Ingresado', 'sum'),
                Clientes=('Codigo_Cliente', 'nunique')
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
                            if y_vals[j-1] != 0:
                                pct_changes[j] = ((y_vals[j] - y_vals[j-1]) / y_vals[j-1]) * 100
                        
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
                            if y_vals[j-1] != 0:
                                pct_changes[j] = ((y_vals[j] - y_vals[j-1]) / y_vals[j-1]) * 100
                        
                        text_labels = [""] + [f"+{pct:.1f}%" if pct >= 0 else f"{pct:.1f}%" for pct in pct_changes[1:]]
                        
                        fig_trend.add_trace(go.Scatter(
                            x=df_trend['Mes_Ingreso'], y=y_vals, mode='lines+markers+text',
                            text=text_labels, textposition="top center",
                            textfont=dict(size=11, weight="bold"),
                            line=dict(width=3, color=colores_palette[idx % len(colores_palette)]),
                            name=met
                        ))
                    fig_trend.update_layout(height=380, showlegend=True, margin=dict(t=30, b=20, l=20, r=20))
                    st.plotly_chart(fig_trend, use_container_width=True)

            with col_info:
                st.markdown("##### 📋 Resumen Período")
                for met in sel_metrics:
                    with st.container(border=True):
                        if met == "GMV":
                            st.metric("Total GMV", f"S/. {df_trend_base['TOTAL'].sum():,.2f}")
                        elif met == "Pedidos":
                            st.metric("Pedidos Únicos", f"{df_trend_base['ID_Pedido_Ingresado'].nunique():,}")
                        elif met == "Peso":
                            st.metric("Peso Total", f"{df_trend_base['Peso_Ingresado'].sum():,.1f} Kg")
                        elif met == "Clientes":
                            st.metric("Clientes Activos", f"{df_trend_base['Codigo_Cliente'].nunique():,}")
                        elif met == "Pedidos Devueltos":
                            val_dev = df_devs[df_devs['Mes_Ingreso'].isin(meses_sel)]['ID_Pedido_Ingresado'].nunique()
                            st.metric("Devoluciones", f"{val_dev:,}")
        else:
            st.info("Seleccione al menos un mes y una métrica para renderizar tendencias.")

    st.markdown("<br>", unsafe_allow_html=True)

    # --- PARTE 2: DESGLOSE DE PARTICIPACIÓN Y EFECTIVIDAD ---
    st.subheader("📋 Desglose de Participación y Efectividad")
    
    m_col1, _ = st.columns([1.5, 3.5])
    with m_col1:
        mes_pie_sel = st.selectbox("📅 Seleccionar Mes de Análisis:", options=meses_existentes, key="pie_compact_filter")
        
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
        
        df_rutas_perf = df_rutas_perf.rename(columns={
            'Ruta_Final': 'Ruta',
            'COSTEÑO': 'Pedidos COSTEÑO',
            'BEES': 'Pedidos BEES'
        })
        df_rutas_perf = df_rutas_perf.sort_values(by='% BEES', ascending=True)
        st.dataframe(df_rutas_perf[['Ruta', 'Pedidos COSTEÑO', 'Pedidos BEES', '% BEES']], use_container_width=True, hide_index=True, height=310)

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
            
            pct_c = (c_peds / total_pedidos_pie * 100) if total_pedidos_pie > 0 else 0
            pct_b = (b_peds / total_pedidos_pie * 100) if total_pedidos_pie > 0 else 0
            
            st.markdown(f"""
            <div style="background-color: var(--secondary-background-color); color: var(--text-color); padding: 8px 10px; border-radius: 6px; font-size: 14px; border-left: 4px solid #4A3B5C; text-align: center; line-height: 1.4;">
                <b>📌 Resumen de Cuotas ({mes_pie_sel}):</b><br>
                • <b>COSTEÑO:</b> {c_peds:,} und ({pct_c:.2f}%) &nbsp;|&nbsp; • <b>BEES:</b> {b_peds:,} und ({pct_b:.2f}%)
            </div>
            """, unsafe_allow_html=True)
        else:
            st.info("Sin registros.")

    st.markdown("---")

    # --- APARTADO: ANÁLISIS DE EFECTIVIDAD LOGÍSTICA ---
    st.markdown("#### ⚙️ Análisis de Efectividad Logística")
    
    col_g, col_t = st.columns([2.5, 1.5])
    
    with col_t:
        sub_c1, sub_c2, sub_c3 = st.columns([1, 4, 1])
        with sub_c2:
            mes_funnel = st.selectbox("📅 Mes Flujo:", options=meses_existentes, key="funnel_mes_key")
            
    with col_g:
        canal_funnel = st.radio("🏢 Segmento:", ["UNIVERSO", "BEES", "COSTEÑO"], horizontal=True, key="funnel_canal_key")

    df_f_base = df_region[df_region['Mes_Ingreso'] == mes_funnel]
    
    def extraer_metricas_embudo(df_fase):
        ing = df_fase['ID_Pedido_Ingresado'].nunique()
        fac = df_fase[df_fase['ID_Factura_Final'].notna() & (df_fase['ID_Factura_Final'].astype(str) != "0")]['ID_Pedido_Ingresado'].nunique()
        ent = df_fase[df_fase['ID_Factura_Final'].notna() & (df_fase['ID_Factura_Final'].astype(str) != "0") & ((df_fase['Motivo_Devolucion'].isna()) | (df_fase['Motivo_Devolucion'] == "") | (df_fase['Motivo_Devolucion'].astype(str).str.upper() == "NAN"))]['ID_Pedido_Ingresado'].nunique()
        return ing, fac, ent

    if canal_funnel != "UNIVERSO":
        df_f_filt = df_f_base[df_f_base['Canal_UI'] == canal_funnel]
        ing_f, fac_f, ent_f = extraer_metricas_embudo(df_f_filt)
    else:
        ing_f, fac_f, ent_f = extraer_metricas_embudo(df_f_base)

    with col_g:
        fases_labels = ["1. Ingreso", "2. Facturación", "3. Entrega"]
        lista_pasados = [ing_f, fac_f, ent_f]
        lista_perdidos = [0, ing_f - fac_f, ing_f - ent_f]

        df_stack = pd.DataFrame({
            "Fase": fases_labels * 2,
            "Cantidad": lista_pasados + lista_perdidos,
            "Tipo": ["✔️ Pasados"]*3 + ["❌ Perdidos"]*3
        })

        if ing_f > 0:
            fig_stack = px.bar(
                df_stack, x="Fase", y="Cantidad", color="Tipo", barmode="stack", text="Cantidad",
                color_discrete_map={"✔️ Pasados": "#17A2B8", "❌ Perdidos": "#E74C3C"}
            )
            fig_stack.update_traces(textposition='inside', textfont=dict(color='white', size=13, weight='bold'))
            fig_stack.update_layout(height=300, margin=dict(t=10, b=10, l=10, r=10), xaxis_title="", yaxis_title="Pedidos", legend_title="")
            st.plotly_chart(fig_stack, use_container_width=True)
        else:
            st.info("No hay transacciones para construir el embudo logístico.")

    with col_t:
        ing_c, fac_c, ent_c = extraer_metricas_embudo(df_f_base[df_f_base['Canal_UI']=='COSTEÑO'])
        ing_b, fac_b, ent_b = extraer_metricas_embudo(df_f_base[df_f_base['Canal_UI']=='BEES'])

        p_fac_c = (fac_c / ing_c * 100) if ing_c > 0 else 0
        p_ent_c = (ent_c / fac_c * 100) if fac_c > 0 else 0
        p_tot_c = (ent_c / ing_c * 100) if ing_c > 0 else 0

        p_fac_b = (fac_b / ing_b * 100) if ing_b > 0 else 0
        p_ent_b = (ent_b / fac_b * 100) if fac_b > 0 else 0
        p_tot_b = (ent_b / ing_b * 100) if ing_b > 0 else 0

        html_efectividad = f"""
        <div style="font-family: monospace; font-size: 13px; background-color: var(--secondary-background-color); padding: 15px; border-radius: 8px; border: 1px solid var(--border-color); color: var(--text-color); margin-top: 15px;">
            <div style="display: flex; justify-content: space-between; font-weight: bold; margin-bottom: 10px; color:#4A3B5C; border-bottom: 2px solid var(--border-color); padding-bottom: 4px;">
                <span style="width: 50%;">COSTEÑO</span>
                <span style="width: 50%;">BEES</span>
            </div>
            <div style="display: flex; justify-content: space-between; margin-bottom: 4px;">
                <span style="width: 50%;">Ingreso: 100%</span>
                <span style="width: 50%;">Ingreso: 100%</span>
            </div>
            <div style="display: flex; justify-content: space-between; margin-bottom: 4px;">
                <span style="width: 50%;">Facturados: {p_fac_c:.2f}%</span>
                <span style="width: 50%;">Facturados: {p_fac_b:.2f}%</span>
            </div>
            <div style="display: flex; justify-content: space-between; margin-bottom: 4px;">
                <span style="width: 50%;">Entregados: {p_ent_c:.2f}%</span>
                <span style="width: 50%;">Entregados: {p_ent_b:.2f}%</span>
            </div>
            <hr style="margin: 8px 0; border-top: 1px dashed var(--border-color);">
            <div style="display: flex; justify-content: space-between; font-weight: bold; color: #17A2B8;">
                <span style="width: 50%;">Total: {p_tot_c:.2f}%</span>
                <span style="width: 50%;">Total: {p_tot_b:.2f}%</span>
            </div>
        </div>
        """
        st.markdown("<h5 style='text-align: center; margin-top: 10px;'>📊 Desglose de Fases por Canal Comercial</h5>", unsafe_allow_html=True)
        st.markdown(html_efectividad, unsafe_allow_html=True)


elif segmento_actual == "📊 Resumen":
    st.title("📊 Resumen Ejecutivo")
    st.info("Módulo en construcción.")

elif segmento_actual == "📈 Métricas":
    st.title("📈 Métricas Comerciales")
    st.info("Módulo en construcción.")

# --- NUEVO SEGMENTO CORE DE DETALLE SOLICITADO ---
elif segmento_actual == "🔍 Detalle":
    st.title("🔍 Detalle Volumétrico y Conversión Logística")
    st.markdown(f"Filtros Activos: Región: **{opcion_region}** | Flujo: **{estado_flujo_sel}** | Mes: **{mes_global_sel}**")
    
    # -----------------------------------------------------------------
    # ESTRUCTURA EN DONA PARALELA (IZQUIERDA: DATOS | DERECHA: GRÁFICO)
    # -----------------------------------------------------------------
    st.subheader("📊 Distribución Estructural de Operaciones por Canal")
    
    # Grid de 2x2 para las 4 métricas críticas
    fila1_col1, fila1_col2 = st.columns(2)
    fila2_col1, fila2_col2 = st.columns(2)
    
    # 1. Pedidos Únicos
    peds_c = df_activo[df_activo['Canal_UI'] == 'COSTEÑO']['ID_Pedido_Ingresado'].nunique()
    peds_b = df_activo[df_activo['Canal_UI'] == 'BEES']['ID_Pedido_Ingresado'].nunique()
    tot_peds = peds_c + peds_b
    
    # 2. Clientes Únicos
    cli_c = df_activo[df_activo['Canal_UI'] == 'COSTEÑO']['Codigo_Cliente'].nunique()
    cli_b = df_activo[df_activo['Canal_UI'] == 'BEES']['Codigo_Cliente'].nunique()
    tot_cli = cli_c + cli_b
    
    # 3. Peso Total en Toneladas (Base de datos original asumida en Kg)
    peso_c = df_activo[df_activo['Canal_UI'] == 'COSTEÑO']['Peso_Ingresado'].sum() / 1000
    peso_b = df_activo[df_activo['Canal_UI'] == 'BEES']['Peso_Ingresado'].sum() / 1000
    tot_peso = peso_c + peso_b
    
    # CORRECCIÓN DE SINTAXIS: Se aisla el divisor condicional de forma segura para evitar SyntaxError
    tc_divisor = TC_FIJO if TC_FIJO > 0 else 3.396
    gmv_c = df_activo[df_activo['Canal_UI'] == 'COSTEÑO']['TOTAL'].sum() / tc_divisor
    gmv_b = df_activo[df_activo['Canal_UI'] == 'BEES']['TOTAL'].sum() / tc_divisor
    tot_gmv = gmv_c + gmv_b

    def renderizar_bloque_espejo(columna_target, titulo, total_formateado, val_c, val_b, total_numerico, sufijo=""):
        with columna_target:
            with st.container(border=True):
                st.markdown(f"##### {titulo}")
                sub_izq, sub_der = st.columns([1.6, 1.4])
                
                pct_c = (val_c / total_numerico * 100) if total_numerico > 0 else 0
                pct_b = (val_b / total_numerico * 100) if total_numerico > 0 else 0
                
                with sub_izq:
                    st.markdown(f"<p style='font-size:22px; font-weight:bold; margin-bottom:2px;'>{total_formateado}</p>", unsafe_allow_html=True)
                    st.markdown("<p style='font-size:11px; color:gray; margin-top:0px;'>Volumen Total Consolidador</p>", unsafe_allow_html=True)
                    
                    html_datos = f"""
                    <div style="font-family: sans-serif; font-size: 14px; margin-top:12px; line-height:1.6;">
                        <span style="color:#4A3B5C; font-weight:bold;">■ COSTEÑO:</span> {val_c:,.2f if type(val_c)==float else val_c:} {sufijo} <b style="color:gray;">({pct_c:.1f}%)</b><br>
                        <span style="color:#17A2B8; font-weight:bold;">■ BEES:</span> {val_b:,.2f if type(val_b)==float else val_b:} {sufijo} <b style="color:gray;">({pct_b:.1f}%)</b>
                    </div>
                    """
                    st.markdown(html_datos, unsafe_allow_html=True)
                    
                with sub_der:
                    if total_numerico > 0:
                        fig = go.Figure(data=[go.Pie(
                            labels=['COSTEÑO', 'BEES'], 
                            values=[val_c, val_b], 
                            hole=0.48,
                            marker=dict(colors=['#4A3B5C', '#17A2B8']),
                            textinfo='none'
                        )])
                        fig.update_layout(margin=dict(t=5, b=5, l=5, r=5), height=130, showlegend=False)
                        st.plotly_chart(fig, use_container_width=True, key=f"dona_{titulo.replace(' ', '_')}")
                    else:
                        st.caption("Sin transacciones")

    # Renderizado simétrico de los 4 bloques volumétricos
    renderizar_bloque_espejo(fila1_col1, "📦 Pedidos Únicos", f"{tot_peds:,} und", peds_c, peds_b, tot_peds, "und")
    renderizar_bloque_espejo(fila1_col2, "👥 Cantidad de Clientes Únicos", f"{tot_cli:,} cli", cli_c, cli_b, tot_cli, "cli")
    renderizar_bloque_espejo(fila2_col1, "⚖️ Peso Total (Representación TN)", f"{tot_peso:,.2f} TN", peso_c, peso_b, tot_peso, "TN")
    renderizar_bloque_espejo(fila2_col2, "💵 Capital Total (Representación USD)", f"$ {tot_gmv:,.2f}", gmv_c, gmv_b, tot_gmv, "USD")

    st.markdown("<br>", unsafe_allow_html=True)

    # -----------------------------------------------------------------
    # SECCIÓN: RENDIMIENTO DE ETAPAS Y EFECTIVIDAD DEL CANAL
    # -----------------------------------------------------------------
    st.subheader("⚙️ Rendimiento de Etapas y Efectividad del Canal")
    
    canal_log_sel = st.segmented_control("Filtrar Canal Logístico:", options=["UNIVERSO", "BEES", "COSTEÑO"], default="UNIVERSO")
    if not canal_log_sel: canal_log_sel = "UNIVERSO"
    
    # Función auxiliar interna para calcular los volúmenes puros por etapas
    def obtener_volumen_etapas(df_segmento):
        ingresados = df_segmento['ID_Pedido_Ingresado'].nunique()
        facturados = df_segmento[df_segmento['ID_Factura_Final'].notna() & (df_segmento['ID_Factura_Final'].astype(str) != "0") & (df_segmento['ID_Factura_Final'].astype(str) != "")]['ID_Pedido_Ingresado'].nunique()
        entregados = df_segmento[df_segmento['ID_Factura_Final'].notna() & (df_segmento['ID_Factura_Final'].astype(str) != "0") & (df_segmento['ID_Factura_Final'].astype(str) != "") & ((df_segmento['Motivo_Devolucion'].isna()) | (df_segmento['Motivo_Devolucion'] == "") | (df_segmento['Motivo_Devolucion'].astype(str).str.upper() == "NAN"))]['ID_Pedido_Ingresado'].nunique()
        return ingresados, facturados, entregados

    with st.container(border=True):
        st.markdown("#### 📑 Matriz de Conversión Logística por Canal Comercial")
        
        # Ingesta y cálculo cruzado de fases para los dos canales comerciales directos
        ing_cost, fac_cost, ent_cost = obtener_volumen_etapas(df_mes_activo[df_mes_activo['Canal_UI'] == 'COSTEÑO'])
        ing_bees, fac_bees, ent_bees = obtener_volumen_etapas(df_mes_activo[df_mes_activo['Canal_UI'] == 'BEES'])
        
        # Porcentajes de cambio secuenciales entre fases
        pct_fac_c = (fac_cost / ing_cost * 100) if ing_cost > 0 else 0
        pct_ent_c = (ent_cost / fac_cost * 100) if fac_cost > 0 else 0
        tot_eff_c = (ent_cost / ing_cost * 100) if ing_cost > 0 else 0
        
        pct_fac_b = (fac_bees / ing_bees * 100) if ing_bees > 0 else 0
        pct_ent_b = (ent_bees / fac_bees * 100) if fac_bees > 0 else 0
        tot_eff_b = (ent_bees / ing_bees * 100) if ing_bees > 0 else 0

        # Construcción estructural del dataframe de conversión
        matriz_conversion_raw = {
            "Canal Comercial": ["COSTEÑO", "BEES"],
            "1. Ingreso (Base)": [f"{ing_cost:,} und", f"{ing_bees:,} und"],
            " Tasa Facturación (% Cambio)": [f"{pct_fac_c:.1f}%", f"{pct_fac_b:.1f}%"],
            "2. Facturado": [f"{fac_cost:,} und", f"{fac_bees:,} und"],
            " Tasa Entrega (% Cambio)": [f"{pct_ent_c:.1f}%", f"{pct_ent_b:.1f}%"],
            "3. Entregado Real": [f"{ent_cost:,} und", f"{ent_bees:,} und"],
            "🚀 Efectividad Final Total": [f"{tot_eff_c:.2f}%", f"{tot_eff_b:.2f}%"]
        }
        
        df_matriz_final = pd.DataFrame(matriz_conversion_raw)
        
        # Filtro interactivo inyección sobre filas
        if canal_log_sel != "UNIVERSO":
            df_matriz_final = df_matriz_final[df_matriz_final['Canal Comercial'] == canal_log_sel]
            
        st.dataframe(df_matriz_final, use_container_width=True, hide_index=True)
        st.markdown("<p style='font-size:12px; color:gray; margin-top:4px;'>* El porcentaje de cambio evalúa el comportamiento secuencial: Tasa Facturación (Ingreso ➔ Facturado) | Tasa Entrega (Facturado ➔ Entregado Real sin Devoluciones).</p>", unsafe_allow_html=True)


elif segmento_actual == "🔮 Proyección":
    st.title("🔮 Proyección")
    st.info("Módulo en construcción.")

else:
    st.title("🚧 En proceso")
    st.info("Módulo en construcción.")
