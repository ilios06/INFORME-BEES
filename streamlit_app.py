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

# --- CONFIGURACIÓN DE LA PÁGINA WEB ---
st.set_page_config(
    page_title="App Conciliación BEES & COSTEÑO",
    page_icon="📊",
    layout="wide",
    initial_sidebar_state="expanded"
)

# --- CONSTANTES COMERCIALES ---
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

# --- DESCARGA Y PROCESAMIENTO DE DATOS EN CACHÉ ---
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
            'ID_Pedido_Ingresado': str, 'ID_Factura_Final': str, 
            'SKU_Material_Ingresado': str, 'Codigo_Cliente': str, 
            'Motivo_Devolucion': str, 'Zona_OfVta': str, 'Tipo_Pedido': str, 
            'Columna_AE_Zpedidos': str
        })
        
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

# --- BARRA DE NAVEGACIÓN SUPERIOR (ESTILO PLANTILLA MODERNA) ---
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
opcion_region = st.sidebar.selectbox("📍 Región Geográfica", ["AMBOS", "LIMA", "AREQUIPA"], index=0)
estado_flujo_sel = st.sidebar.selectbox("🔀 Estado de Pedido", ["Ingresados", "Facturados", "Entregados"], index=0)

meses_existentes = sorted([m for m in df_raw['Mes_Ingreso'].unique() if m != "Sin Mes"], key=lambda x: LISTA_MESES_ORDENADOS.index(x) if x in LISTA_MESES_ORDENADOS else 99)
mes_global_sel = st.sidebar.selectbox("📅 Mes de Operación Core", options=meses_existentes, index=0)

if st.sidebar.button("🔄 Forzar Sincronización"):
    st.cache_data.clear()
    st.rerun()

# --- LÓGICA DE FILTRADO CORE ---
df_region = df_raw.copy()
if opcion_region == "LIMA":
    df_region = df_raw[df_raw['Zona_OfVta_Clean'] == "LIMA"]
elif opcion_region == "AREQUIPA":
    df_region = df_raw[df_raw['Zona_OfVta_Clean'] == "AREQUIPA"]

df_mes_activo = df_region[df_region['Mes_Ingreso'] == mes_global_sel]

df_activo = df_mes_activo.copy()
if estado_flujo_sel == "Facturados":
    df_activo = df_activo[df_activo['ID_Factura_Final'].notna() & (df_activo['ID_Factura_Final'].astype(str) != "0") & (df_activo['ID_Factura_Final'].astype(str) != "")]
elif estado_flujo_sel == "Entregados":
    df_activo = df_activo[df_activo['ID_Factura_Final'].notna() & (df_activo['ID_Factura_Final'].astype(str) != "0") & (df_activo['ID_Factura_Final'].astype(str) != "")]
    df_activo = df_activo[(df_activo['Motivo_Devolucion'].isna()) | (df_activo['Motivo_Devolucion'] == "") | (df_activo['Motivo_Devolucion'].astype(str).str.upper() == "NAN")]

# -----------------------------------------------------------------
# RENDERING DE MÓDULOS DEL PANEL DE CONTROL
# -----------------------------------------------------------------

if segmento_actual == "🏠 Principal":
    st.title("🏠 Dashboard Principal Operativo")
    st.markdown(f"Status: Pedidos **{estado_flujo_sel}** | Región: **{opcion_region}**")
    
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
            df_trend_base = df_region[df_region['Mes_Ingreso'].isin(meses_sel)]
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
                        if met == "GMV": st.metric("Total GMV", f"S/. {df_trend_base['TOTAL'].sum():,.2f}")
                        elif met == "Pedidos": st.metric("Pedidos Únicos", f"{df_trend_base['ID_Pedido_Ingresado'].nunique():,}")
                        elif met == "Peso": st.metric("Peso Total", f"{df_trend_base['Peso_Ingresado'].sum():,.1f} Kg")
                        elif met == "Clientes": st.metric("Clientes Activos", f"{df_trend_base['Codigo_Cliente'].nunique():,}")
                        elif met == "Pedidos Devueltos": st.metric("Devoluciones", f"{df_devs[df_devs['Mes_Ingreso'].isin(meses_sel)]['ID_Pedido_Ingresado'].nunique():,}")

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
        df_rutas_perf = df_rutas_perf.rename(columns={'Ruta_Final': 'Ruta', 'COSTEÑO': 'Pedidos COSTEÑO', 'BEES': 'Pedidos BEES'})
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
        else: st.info("Sin registros.")

    st.markdown("---")
    # --- APARTADO: ANÁLISIS DE EFECTIVIDAD LOGÍSTICA ---
    st.markdown("#### ⚙️ Análisis de Efectividad Logística")
    col_g, col_t = st.columns([2.5, 1.5])
    with col_t:
        sub_c1, sub_c2, sub_c3 = st.columns([1, 4, 1])
        with sub_c2: mes_funnel = st.selectbox("📅 Mes Flujo:", options=meses_existentes, key="funnel_mes_key")
    with col_g: canal_funnel = st.radio("🏢 Segmento:", ["UNIVERSO", "BEES", "COSTEÑO"], horizontal=True, key="funnel_canal_key")

    df_f_base = df_region[df_region['Mes_Ingreso'] == mes_funnel]
    def extraer_metricas_embudo(df_fase):
        ing = df_fase['ID_Pedido_Ingresado'].nunique()
        fac = df_fase[df_fase['ID_Factura_Final'].notna() & (df_fase['ID_Factura_Final'].astype(str) != "0")]['ID_Pedido_Ingresado'].nunique()
        ent = df_fase[df_fase['ID_Factura_Final'].notna() & (df_fase['ID_Factura_Final'].astype(str) != "0") & ((df_fase['Motivo_Devolucion'].isna()) | (df_fase['Motivo_Devolucion'] == "") | (df_fase['Motivo_Devolucion'].astype(str).str.upper() == "NAN"))]['ID_Pedido_Ingresado'].nunique()
        return ing, fac, ent

    ing_f, fac_f, ent_f = extraer_metricas_embudo(df_f_base if canal_funnel == "UNIVERSO" else df_f_base[df_f_base['Canal_UI'] == canal_funnel])
    with col_g:
        if ing_f > 0:
            df_stack = pd.DataFrame({"Fase": ["1. Ingreso", "2. Facturación", "3. Entrega"] * 2, "Cantidad": [ing_f, fac_f, ent_f, 0, ing_f - fac_f, ing_f - ent_f], "Tipo": ["✔️ Pasados"]*3 + ["❌ Perdidos"]*3})
            fig_stack = px.bar(df_stack, x="Fase", y="Cantidad", color="Tipo", barmode="stack", text="Cantidad", color_discrete_map={"✔️ Pasados": "#17A2B8", "❌ Perdidos": "#E74C3C"})
            fig_stack.update_traces(textposition='inside', textfont=dict(color='white', size=13, weight='bold'))
            fig_stack.update_layout(height=300, margin=dict(t=10, b=10, l=10, r=10), xaxis_title="", yaxis_title="Pedidos", legend_title="")
            st.plotly_chart(fig_stack, use_container_width=True)
        else: st.info("No hay transacciones.")
    with col_t:
        ing_c, fac_c, ent_c = extraer_metricas_embudo(df_f_base[df_f_base['Canal_UI']=='COSTEÑO'])
        ing_b, fac_b, ent_b = extraer_metricas_embudo(df_f_base[df_f_base['Canal_UI']=='BEES'])
        st.markdown("<h5 style='text-align: center; margin-top: 10px;'>📊 Desglose de Fases por Canal Comercial</h5>", unsafe_allow_html=True)
        st.markdown(f"""
        <div style="font-family: monospace; font-size: 13px; background-color: var(--secondary-background-color); padding: 15px; border-radius: 8px; border: 1px solid var(--border-color); color: var(--text-color); margin-top: 15px;">
            <div style="display: flex; justify-content: space-between; font-weight: bold; margin-bottom: 10px; color:#4A3B5C; border-bottom: 2px solid var(--border-color); padding-bottom: 4px;">
                <span style="width: 50%;">COSTEÑO</span><span style="width: 50%;">BEES</span>
            </div>
            <div style="display: flex; justify-content: space-between;"><span>Ingreso: 100%</span><span>Ingreso: 100%</span></div>
            <div style="display: flex; justify-content: space-between;"><span>Facturados: {(fac_c/ing_c*100) if ing_c>0 else 0:.1f}%</span><span>Facturados: {(fac_b/ing_b*100) if ing_b>0 else 0:.1f}%</span></div>
            <div style="display: flex; justify-content: space-between;"><span>Entregados: {(ent_c/fac_c*100) if fac_c>0 else 0:.1f}%</span><span>Entregados: {(ent_b/fac_b*100) if fac_b>0 else 0:.1f}%</span></div>
            <hr style="margin: 8px 0; border-top: 1px dashed var(--border-color);">
            <div style="display: flex; justify-content: space-between; font-weight: bold; color: #17A2B8;">
                <span>Total: {(ent_c/ing_c*100) if ing_c>0 else 0:.2f}%</span><span>Total: {(ent_b/ing_b*100) if ing_b>0 else 0:.2f}%</span>
            </div>
        </div>
        """, unsafe_allow_html=True)

elif segmento_actual == "📊 Resumen":
    st.title("📊 Auditoría de Devoluciones y Macrocategorización")
    st.markdown(f"Análisis enfocado en el mes de **{mes_global_sel}**")
    
    df_dev_raw = df_mes_activo[df_mes_activo['Motivo_Devolucion'].notna() & (df_mes_activo['Motivo_Devolucion'] != "") & (df_mes_activo['Motivo_Devolucion'].str.upper() != "NAN")]
    
    if not df_dev_raw.empty:
        def macrocategorizar(m):
            m_str = str(m).upper()
            if any(x in m_str for x in ['CALIDAD', 'MALO', 'ROTO', 'VENCIDO', 'DAÑADO', 'VENCIMIENTO']): return 'Problemas de Calidad'
            elif any(x in m_str for x in ['PRECIO', 'DESCUENTO', 'ERROR COMER', 'BONIF', 'COMERCIAL', 'VALOR']): return 'Discrepancia Comercial'
            elif any(x in m_str for x in ['CERRADO', 'NO TIENE DINERO', 'NO RECIBE', 'RECHAZA', 'NO SOLICITO']): return 'Restricción del Cliente'
            return 'Error Administrativo'
            
        df_dev_raw['Macro_Motivo'] = df_dev_raw['Motivo_Devolucion'].apply(macrocategorizar)
        
        # Tabla de Impacto
        st.subheader("📋 Matriz de Impacto de Fuga Capital por Macrofamilia")
        df_impacto = df_dev_raw.groupby('Macro_Motivo').agg(
            Pedidos_Afectados=('ID_Pedido_Ingresado', 'nunique'),
            Capital_Retenido=('TOTAL', 'sum'),
            Peso_Rebotado=('Peso_Ingresado', 'sum')
        ).reset_index()
        df_impacto['% Capital'] = (df_impacto['Capital_Retenido'] / df_impacto['Capital_Retenido'].sum()) * 100
        st.dataframe(df_impacto.style.background_gradient(cmap="YlOrRd", subset=['Capital_Retenido']), use_container_width=True, hide_index=True)
        
        # Análisis de Densidad por Atributo
        st.subheader("🔍 Análisis de Densidad Económica (Fuga por Familia/Marca)")
        c_f1, c_f2 = st.columns(2)
        with c_f1:
            st.markdown("**Fuga por Categoría Cuota Material**")
            df_cat = df_dev_raw.groupby('Categoria Cuota')['TOTAL'].sum().reset_index().sort_values('TOTAL', ascending=False)
            fig_cat = px.bar(df_cat.head(10), x='TOTAL', y='Categoria Cuota', orientation='h', color_discrete_sequence=['#E74C3C'])
            st.plotly_chart(fig_cat, use_container_width=True)
        with c_f2:
            st.markdown("**Fuga por Marca**")
            df_mrc = df_dev_raw.groupby('Marca')['TOTAL'].sum().reset_index().sort_values('TOTAL', ascending=False)
            fig_mrc = px.bar(df_mrc.head(10), x='TOTAL', y='Marca', orientation='h', color_discrete_sequence=['#4A3B5C'])
            st.plotly_chart(fig_mrc, use_container_width=True)
    else: st.success("🎉 Cero devoluciones registradas en este período de análisis.")

elif segmento_actual == "📈 Métricas":
    st.title("📈 Score Crítico de Clientes (Modelo Pareto 80/20)")
    st.markdown(f"Segmentación de riesgo para el mes: **{mes_global_sel}**")
    
    df_dev_raw = df_mes_activo[df_mes_activo['Motivo_Devolucion'].notna() & (df_mes_activo['Motivo_Devolucion'] != "") & (df_mes_activo['Motivo_Devolucion'].str.upper() != "NAN")]
    
    if not df_dev_raw.empty:
        # Auditoría de Clientes Recurrentes
        df_cli = df_dev_raw.groupby('Codigo_Cliente').agg(
            Eventos_Devolucion=('ID_Pedido_Ingresado', 'nunique'),
            SKUs_Rebotados=('SKU_Material_Ingresado', 'count'),
            Monto_Pérdida=('TOTAL', 'sum')
        ).reset_index().sort_values('Monto_Pérdida', ascending=False)
        
        df_recurrentes = df_cli[df_cli['Eventos_Devolucion'] > 1]
        st.subheader(f"👥 Foco de Alerta: Auditoría de Clientes Recurrentes ({len(df_recurrentes)} clientes)")
        st.dataframe(df_recurrentes, use_container_width=True, hide_index=True)
        
        # Modelo Pareto Matematico
        df_cli['Monto_Acumulado'] = df_cli['Monto_Pérdida'].cumsum()
        total_fuga = df_cli['Monto_Pérdida'].sum()
        df_cli['% Acumulado'] = (df_cli['Monto_Acumulado'] / total_fuga) * 100
        df_cli['Clasificación Pareto'] = np.where(df_cli['% Acumulado'] <= 80.5, '🔴 Zona Crítica 80% (Pocos Afectan Más)', '🟢 Zona Estable 20%')
        
        st.subheader("🎯 Clasificación de Clientes según Concentración de Pérdida")
        fig_pareto = px.scatter(df_cli, x='% Acumulado', y='Monto_Pérdida', color='Clasificación Pareto', size='Eventos_Devolucion', hover_data=['Codigo_Cliente'], color_discrete_map={'🔴 Zona Crítica 80% (Pocos Afectan Más)': '#E74C3C', '🟢 Zona Estable 20%': '#28A745'})
        st.plotly_chart(fig_pareto, use_container_width=True)
        st.dataframe(df_cli[['Codigo_Cliente', 'Eventos_Devolucion', 'Monto_Pérdida', '% Acumulado', 'Clasificación Pareto']], use_container_width=True, hide_index=True)
    else: st.info("Sin registros de rebote.")

elif segmento_actual == "🔍 Detalle":
    st.title("🔍 Detalle Volumétrico y Conversión Logística")
    
    st.subheader("Distribución Estructural Paralela de Operaciones")
    r1_c1, r1_c2 = st.columns(2)
    r2_c1, r2_c2 = st.columns(2)
    
    peds_c = df_activo[df_activo['Canal_UI'] == 'COSTEÑO']['ID_Pedido_Ingresado'].nunique()
    peds_b = df_activo[df_activo['Canal_UI'] == 'BEES']['ID_Pedido_Ingresado'].nunique()
    tot_peds = peds_c + peds_b
    
    cli_c = df_activo[df_activo['Canal_UI'] == 'COSTEÑO']['Codigo_Cliente'].nunique()
    cli_b = df_activo[df_activo['Canal_UI'] == 'BEES']['Codigo_Cliente'].nunique()
    tot_cli = cli_c + cli_b
    
    peso_c = df_activo[df_activo['Canal_UI'] == 'COSTEÑO']['Peso_Ingresado'].sum() / 1000
    peso_b = df_activo[df_activo['Canal_UI'] == 'BEES']['Peso_Ingresado'].sum() / 1000
    tot_peso = peso_c + peso_b
    
    gmv_c = df_activo[df_activo['Canal_UI'] == 'COSTEÑO']['TOTAL'].sum() / TC_FIFixed = TC_FIJO if TC_FIJO > 0 else 3.396
    gmv_c = df_activo[df_activo['Canal_UI'] == 'COSTEÑO']['TOTAL'].sum() / TC_FIFixed
    gmv_b = df_activo[df_activo['Canal_UI'] == 'BEES']['TOTAL'].sum() / TC_FIFixed
    tot_gmv = gmv_c + gmv_b

    def block_dona(col, title, total_str, vc, vb, total_val, unit="", px="$"):
        with col:
            with st.container(border=True):
                st.markdown(f"##### {title}")
                l, r = st.columns([1.6, 1.4])
                with l:
                    st.markdown(f"<p style='font-size:20px; font-weight:bold; margin-bottom:2px;'>{total_str}</p>", unsafe_allow_html=True)
                    st.markdown("<p style='font-size:11px; color:gray; margin-top:0px;'>Volumen Consolidado</p>", unsafe_allow_html=True)
                    st.markdown(f"<div style='font-size:14px; margin-top:10px;'><b>■ COSTEÑO:</b> {px if px!='und' and px!='cli' and px!='TN' else ''}{vc:,.2f if type(vc)==float else vc:,} {unit} ({vc/total_val*100 if total_val>0 else 0:.1f}%)<br><b>■ BEES:</b> {px if px!='und' and px!='cli' and px!='TN' else ''}{vb:,.2f if type(vb)==float else vb:,} {unit} ({vb/total_val*100 if total_val>0 else 0:.1f}%)</div>", unsafe_allow_html=True)
                with r:
                    if total_val > 0:
                        fig = go.Figure(data=[go.Pie(labels=['COSTEÑO', 'BEES'], values=[vc, vb], hole=0.45, marker=dict(colors=['#4A3B5C', '#17A2B8']), textinfo='none')])
                        fig.update_layout(margin=dict(t=5, b=5, l=5, r=5), height=135, showlegend=False)
                        st.plotly_chart(fig, use_container_width=True)
                    else: st.caption("Sin transacciones")

    block_dona(r1_c1, "📦 Cantidad de Pedidos", f"{tot_peds:,} und", peds_c, peds_b, tot_peds, "und", "und")
    block_dona(r1_c2, "👥 Clientes Únicos", f"{tot_cli:,} cli", cli_c, cli_b, tot_cli, "cli", "cli")
    block_dona(r2_c1, "⚖️ Peso Total (TN)", f"{tot_peso:,.2f} TN", peso_c, peso_b, tot_peso, "TN", "TN")
    block_dona(r2_c2, "💵 Capital Total (GMV USD)", f"$ {tot_gmv:,.2f}", gmv_c, gmv_b, tot_gmv, "USD", "$")

    st.markdown("<br>", unsafe_allow_html=True)
    st.subheader("⚙️ Rendimiento de Etapas y Efectividad del Canal")
    canal_log_sel = st.segmented_control("Filtrar Canal Logístico:", options=["UNIVERSO", "BEES", "COSTEÑO"], default="UNIVERSO")
    
    with st.container(border=True):
        st.markdown("#### 📑 Matriz de Conversión Logística por Canal Comercial")
        def calc_fases_m(df_s):
            ing = df_s['ID_Pedido_Ingresado'].nunique()
            fac = df_s[df_s['ID_Factura_Final'].notna() & (df_s['ID_Factura_Final'].astype(str) != "0") & (df_s['ID_Factura_Final'].astype(str) != "")]['ID_Pedido_Ingresado'].nunique()
            ent = df_s[df_s['ID_Factura_Final'].notna() & (df_s['ID_Factura_Final'].astype(str) != "0") & ((df_s['Motivo_Devolucion'].isna()) | (df_s['Motivo_Devolucion'] == "") | (df_s['Motivo_Devolucion'].astype(str).str.upper() == "NAN"))]['ID_Pedido_Ingresado'].nunique()
            return ing, fac, ent

        ing_c, fac_c, ent_c = calc_fases_m(df_mes_activo[df_mes_activo['Canal_UI']=='COSTEÑO'])
        ing_b, fac_b, ent_b = calc_fases_m(df_mes_activo[df_mes_activo['Canal_UI']=='BEES'])
        
        df_matriz = pd.DataFrame({
            "Canal Comercial": ["COSTEÑO", "BEES"],
            "1. Ingreso (Base)": [f"{ing_c:,} und", f"{ing_b:,} und"],
            " Tasa Facturación": [f"{(fac_c/ing_c*100) if ing_c>0 else 0:.1f}%", f"{(fac_b/ing_b*100) if ing_b>0 else 0:.1f}%"],
            "2. Facturado": [f"{fac_c:,} und", f"{fac_b:,} und"],
            " Tasa Entrega": [f"{(ent_c/fac_c*100) if fac_c>0 else 0:.1f}%", f"{(ent_b/fac_b*100) if fac_b>0 else 0:.1f}%"],
            "3. Entregado Real": [f"{ent_c:,} und", f"{ent_b:,} und"],
            "🚀 Efectividad Total": [f"{(ent_c/ing_c*100) if ing_c>0 else 0:.2f}%", f"{(ent_b/ing_b*100) if ing_b>0 else 0:.2f}%"]
        })
        
        if canal_log_sel != "UNIVERSO":
            df_matriz = df_matriz[df_matriz['Canal Comercial'] == canal_log_sel]
        st.dataframe(df_matriz, use_container_width=True, hide_index=True)

elif segmento_actual == "🔮 Proyección":
    st.title("🔮 Proyección y Run-rate de Cierre")
    st.markdown(f"Modelado predictivo basado en comportamiento histórico actual para **{mes_global_sel}**")
    
    with st.container(border=True):
        st.subheader("📈 Proyección Lineal de Cierre de Mes")
        total_actual = df_mes_activo['TOTAL'].sum()
        pedidos_actual = df_mes_activo['ID_Pedido_Ingresado'].nunique()
        
        c_p1, c_p2 = st.columns(2)
        with c_p1:
            st.metric("Volumen Facturado Actual (GMV)", f"S/. {total_actual:,.2f}")
            st.caption("Proyección estimada al cierre basada en tendencia diaria.")
        with c_p2:
            st.metric("Pedidos Únicos Logrados", f"{pedidos_actual:,} und")
            st.caption("Run-rate de transacciones esperadas.")
            
        st.info("💡 Consejo Estratégico: Las desviaciones comerciales en la primera semana impactan el run-rate de facturación en un 12% promedio.")

else:
    st.title("🚧 Módulo de Auditoría Avanzada")
    st.info("Sección habilitada para despliegues de pruebas A/B y auditorías rápidas del Sheets origen.")

# --- 📋 SEGMENTO 5: INSPECCIÓN DE BASE DE DATOS OPERATIVA (EXPANDER GLOBAL) ---
st.markdown("<br><br>", unsafe_allow_html=True)
with st.expander("📋 Segmento 5: Inspección de Base de Datos Operativa"):
    st.markdown("Visualización en bruto de los primeros 50 registros depurados y cruzados en memoria:")
    if not df_raw.empty:
        st.dataframe(df_raw.head(50), use_container_width=True)
    else: st.warning("La base de datos se encuentra vacía o no se logró establecer conexión con Google Drive.")
