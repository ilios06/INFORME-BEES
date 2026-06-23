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

# --- NAVEGACIÓN SUPERIOR ESTILO "PILLS/BOTONES" ---
st.markdown("<br>", unsafe_allow_html=True)
opciones_segmento = ["🏠 Principal", "📊 Resumen", "📈 Métricas", "🔍 Análisis", "🔮 Proyección", "🚧 En proceso"]
segmento_actual = st.radio("Módulos", opciones_segmento, horizontal=True, label_visibility="collapsed")
st.divider()

# --- BARRA LATERAL: FILTROS DE BÚSQUEDA ---
st.sidebar.title("🎛️ Filtros de busqueda")
opcion_region = st.sidebar.selectbox("📍 Región Geográfica", ["Lima", "Arequipa", "Ver Todo"], index=2)
estado_flujo_sel = st.sidebar.selectbox("🔀 Estado de Pedido", ["Ingresados", "Facturados", "Entregados"], index=0)

if st.sidebar.button("🔄 Forzar Sincronización"):
    st.cache_data.clear()
    st.rerun()

# --- LÓGICA DE FILTRADO CORE ---
# 1. Filtro de Región (Afecta a todo)
df_region = df_raw.copy()
if opcion_region == "Lima":
    df_region = df_raw[df_raw['Zona_OfVta_Clean'] == "LIMA"]
elif opcion_region == "Arequipa":
    df_region = df_raw[df_raw['Zona_OfVta_Clean'] == "AREQUIPA"]

# 2. Filtro de Estado de Pedido (Crea df_activo para la vista interactiva)
df_activo = df_region.copy()
if estado_flujo_sel == "Facturados":
    df_activo = df_activo[df_activo['ID_Factura_Final'].notna() & (df_activo['ID_Factura_Final'].astype(str) != "0") & (df_activo['ID_Factura_Final'].astype(str) != "")]
elif estado_flujo_sel == "Entregados":
    df_activo = df_activo[df_activo['ID_Factura_Final'].notna() & (df_activo['ID_Factura_Final'].astype(str) != "0")]
    df_activo = df_activo[(df_activo['Motivo_Devolucion'].isna()) | (df_activo['Motivo_Devolucion'] == "") | (df_activo['Motivo_Devolucion'].astype(str).str.upper() == "NAN")]


# --- LÓGICA DE SEGMENTOS ---
if segmento_actual == "🏠 Principal":
    st.title("🏠 Dashboard Principal Operativo")
    st.markdown(f"Visualizando datos bajo el estado: **{estado_flujo_sel}**")
    
    # --- PARTE 1: EVOLUCIÓN Y TENDENCIA MENSUAL ---
    with st.container(border=True):
        st.subheader("📈 Evolución y Tendencia Mensual Operativa")
        
        # Filtro de selección de meses
        meses_existentes = sorted([m for m in df_activo['Mes_Ingreso'].unique() if m != "Sin Mes"], key=lambda x: LISTA_MESES_ORDENADOS.index(x) if x in LISTA_MESES_ORDENADOS else 99)
        meses_sel = st.multiselect("📅 Seleccione los meses a comparar:", options=meses_existentes, default=meses_existentes)
        
        metricas_disp = {
            "GMV": ("TOTAL", "S/. {:,.2f}"),
            "Pedidos": ("ID_Pedido_Ingresado", "{:,.0f} und"),
            "Peso": ("Peso_Ingresado", "{:,.1f} Kg"),
            "Clientes": ("Codigo_Cliente", "{:,.0f} cli"),
            "Pedidos Devueltos": ("Devoluciones", "{:,.0f} und")
        }
        
        sel_metrics = st.multiselect(
            "📊 Seleccione las métricas a visualizar simultáneamente:",
            list(metricas_disp.keys()),
            default=["GMV", "Pedidos"]
        )
        
        if sel_metrics and meses_sel:
            # Filtrar por meses seleccionados
            df_trend_base = df_activo[df_activo['Mes_Ingreso'].isin(meses_sel)]
            
            df_trend = df_trend_base.groupby('Mes_Ingreso').agg(
                GMV=('TOTAL', 'sum'),
                Pedidos=('ID_Pedido_Ingresado', 'nunique'),
                Peso=('Peso_Ingresado', 'sum'),
                Clientes=('Codigo_Cliente', 'nunique')
            ).reset_index()
            
            # Cálculo de devoluciones
            df_devs = df_region[df_region['Motivo_Devolucion'].notna() & (df_region['Motivo_Devolucion'] != "") & (df_region['Motivo_Devolucion'].str.upper() != "NAN")]
            df_devs_group = df_devs[df_devs['Mes_Ingreso'].isin(meses_sel)].groupby('Mes_Ingreso').agg(**{'Pedidos Devueltos': ('ID_Pedido_Ingresado', 'nunique')}).reset_index()
            df_trend = pd.merge(df_trend, df_devs_group, on='Mes_Ingreso', how='left').fillna(0)
            
            df_trend['Mes_Idx'] = df_trend['Mes_Ingreso'].map(lambda x: LISTA_MESES_ORDENADOS.index(x) if x in LISTA_MESES_ORDENADOS else 99)
            df_trend = df_trend.sort_values('Mes_Idx')
            
            # Layout de Gráfico (80%) vs Caja de Info (20%)
            col_chart, col_info = st.columns([4, 1.2])
            
            with col_chart:
                fig_trend = make_subplots(rows=len(sel_metrics), cols=1, shared_xaxes=True, vertical_spacing=0.08, subplot_titles=sel_metrics)
                for i, met in enumerate(sel_metrics, 1):
                    formato = metricas_disp[met][1]
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
                        textfont=dict(color=text_colors, size=12, weight="bold"),
                        marker=dict(size=8, color="#4A3B5C"), line=dict(width=3, color="#17A2B8"),
                        hovertemplate=f"<b>%{{x}}</b><br>{met}: {formato.replace('{:', '%{y:').replace('}', '}')}<extra></extra>"
                    ), row=i, col=1)
                    
                    fig_trend.update_yaxes(title_text="", row=i, col=1)

                fig_trend.update_layout(height=max(250, 200 * len(sel_metrics)), showlegend=False, margin=dict(t=40, b=20, l=20, r=20))
                st.plotly_chart(fig_trend, use_container_width=True)

            with col_info:
                st.markdown("#### 📋 Resumen del Periodo")
                st.caption("Valores acumulados para los meses seleccionados en el gráfico.")
                
                for met in sel_metrics:
                    with st.container(border=True):
                        if met == "GMV":
                            val = df_trend_base['TOTAL'].sum()
                            st.metric("Total GMV", f"S/. {val:,.2f}")
                        elif met == "Pedidos":
                            val = df_trend_base['ID_Pedido_Ingresado'].nunique()
                            st.metric("Total Pedidos Únicos", f"{val:,} und")
                        elif met == "Peso":
                            val = df_trend_base['Peso_Ingresado'].sum()
                            st.metric("Total Peso Ingresado", f"{val:,.1f} Kg")
                        elif met == "Clientes":
                            val = df_trend_base['Codigo_Cliente'].nunique()
                            st.metric("Total Clientes Únicos", f"{val:,} cli")
                        elif met == "Pedidos Devueltos":
                            val = df_devs[df_devs['Mes_Ingreso'].isin(meses_sel)]['ID_Pedido_Ingresado'].nunique()
                            st.metric("Total Pedidos Devueltos", f"{val:,} und")

        else:
            st.info("👆 Selecciona al menos un mes y una métrica para visualizar la tendencia.")

    st.markdown("<br>", unsafe_allow_html=True)

    # --- PARTE 2: AUDITORÍA DETALLADA (INFERIOR) ---
    st.subheader("📋 Desglose de Participación y Efectividad")
    
    # 2.1 Gráficos Superiores (Ranking y Participación usando df_activo filtrado)
    c1, c2 = st.columns(2)

    with c1:
        st.markdown("**📍 Ranking de Pedidos Únicos por Ruta**")
        df_rutas = df_activo.groupby('Zona_OfVta_Clean')['ID_Pedido_Ingresado'].nunique().reset_index()
        df_rutas.columns = ['Ruta (Zona)', 'Total Pedidos']
        df_rutas = df_rutas.sort_values('Total Pedidos', ascending=False)
        st.dataframe(df_rutas, use_container_width=True, hide_index=True)

    with c2:
        st.markdown("**🥧 Participación de Negocio**")
        df_pie = df_activo.groupby('Canal_UI')['ID_Pedido_Ingresado'].nunique().reset_index()
        if not df_pie.empty:
            fig_pie = px.pie(df_pie, values='ID_Pedido_Ingresado', names='Canal_UI', hole=0.5, color_discrete_sequence=['#4A3B5C', '#17A2B8'])
            fig_pie.update_layout(margin=dict(t=0, b=0, l=0, r=0), height=250)
            st.plotly_chart(fig_pie, use_container_width=True)
        else:
            st.info("Sin datos para este estado de pedido.")

    st.markdown("---")

    # 2.2 Filtros Exclusivos para la base inferior
    st.markdown("#### ⚙️ Análisis de Efectividad Logística")
    f_col1, f_col2 = st.columns(2)
    with f_col1:
        mes_detalle = st.selectbox("📅 Analizar Mes:", options=meses_existentes)
    with f_col2:
        canal_detalle = st.radio("🏢 Segmento Logístico:", ["UNIVERSO", "BEES", "COSTEÑO"], horizontal=True)

    # 2.3 Embudo de Barras Apiladas (Usa df_region base para que el cálculo del embudo sea matemático y real)
    df_funnel_base = df_region[df_region['Mes_Ingreso'] == mes_detalle]
    if canal_detalle != "UNIVERSO":
        df_funnel_base = df_funnel_base[df_funnel_base['Canal_UI'] == canal_detalle]

    # Cálculos puros de fases
    ing = df_funnel_base['ID_Pedido_Ingresado'].nunique()
    fac = df_funnel_base[df_funnel_base['ID_Factura_Final'].notna() & (df_funnel_base['ID_Factura_Final'].astype(str) != "0")]['ID_Pedido_Ingresado'].nunique()
    ent = df_funnel_base[df_funnel_base['ID_Factura_Final'].notna() & (df_funnel_base['ID_Factura_Final'].astype(str) != "0") & ((df_funnel_base['Motivo_Devolucion'].isna()) | (df_funnel_base['Motivo_Devolucion'] == "") | (df_funnel_base['Motivo_Devolucion'].astype(str).str.upper() == "NAN"))]['ID_Pedido_Ingresado'].nunique()

    # Preparar DataFrame para Gráfico de Barras Apiladas
    fases_nombres = ["1. Ingreso", "2. Facturación", "3. Entrega"]
    pedidos_pasados = [ing, fac, ent]
    pedidos_perdidos = [0, ing - fac, ing - ent]

    df_stack = pd.DataFrame({
        "Fase": fases_nombres * 2,
        "Cantidad": pedidos_pasados + pedidos_perdidos,
        "Tipo": ["✔️ Pasados"]*3 + ["❌ Perdidos"]*3
    })

    if ing > 0:
        fig_stack = px.bar(
            df_stack, 
            x="Fase", 
            y="Cantidad", 
            color="Tipo", 
            barmode="stack",
            text="Cantidad",
            title=f"Efectividad por Fases — {canal_detalle} ({mes_detalle})",
            color_discrete_map={"✔️ Pasados": "#17A2B8", "❌ Perdidos": "#E74C3C"}
        )
        
        # Formato limpio para la gráfica
        fig_stack.update_traces(textposition='inside', textfont=dict(color='white', size=14, weight='bold'))
        fig_stack.update_layout(
            height=350, 
            margin=dict(t=40, b=20, l=20, r=20),
            xaxis_title="", 
            yaxis_title="Cantidad de Pedidos",
            legend_title="Estado de Flujo"
        )
        st.plotly_chart(fig_stack, use_container_width=True)
    else:
        st.info("No hay pedidos registrados para graficar la efectividad en este mes/canal.")

elif segmento_actual == "🔮 Proyección":
    st.title("🔮 Proyección y Forecasting")
    st.info("Módulo reservado para la implementación de predicción de demanda logística. Se activará en el próximo Sprint de Desarrollo.")

elif segmento_actual == "📊 Resumen":
    st.title("📊 Resumen Ejecutivo")
    st.info("🚧 Módulo en construcción.")

elif segmento_actual == "📈 Métricas":
    st.title("📈 Métricas Comerciales y Logísticas")
    st.info("🚧 Módulo en construcción.")

elif segmento_actual == "🔍 Análisis":
    st.title("🔍 Análisis Profundo (Deep Dive)")
    st.info("🚧 Módulo en construcción.")

else:
    st.title("🚧 En proceso")
    st.info("Espacio reservado.")
