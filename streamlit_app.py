import streamlit as st
import pandas as pd
import numpy as np
import plotly.express as px
import plotly.graph_objects as go
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseDownload
from google.oauth2 import service_account
import io

# --- CONFIGURACIÓN DE LA PÁGINA WEB ---
st.set_page_config(
    page_title="Dashboard de Conciliación BEES & COSTEÑO",
    page_icon="📊",
    layout="wide"
)

# --- CONFIGURACIÓN DE CONSTANTES COMERCIALES ---
TC_FIJO = 3.396  # Tipo de cambio fijo solicitado
LISTA_MESES_ORDENADOS = ['Enero', 'Febrero', 'Marzo', 'Abril', 'Mayo', 'Junio', 'Julio', 'Agosto', 'Septiembre', 'Octubre', 'Noviembre', 'Diciembre']

# 🌟 ENLACES DE INGESTACIÓN LOGÍSTICA (BYPASS DIRECTO POR URL)
FILE_ID_CONCILIACION = "1-EoM0rYAmYY_tBkKwL5--746cdUa0tw2"
URL_MAESTRO_SKU = "https://docs.google.com/spreadsheets/d/1r1aJNiDvArFqEfAGJ6i8hq_zAo8G5lAc7uW6pXhylZo/export?format=xlsx&gid=1445055226"

# --- 1. CONEXIÓN SEGURA CON GOOGLE DRIVE (PARA BASE PRINCIPAL) ---
@st.cache_resource
def obtener_servicio_drive():
    try:
        info_claves = st.secrets["gcp_service_account"]
        creds = service_account.Credentials.from_service_account_info(info_claves)
        return build('drive', 'v3', credentials=creds)
    except Exception as e:
        st.error(f"❌ Error de autenticación en Drive: Verifica st.secrets. Detalles: {e}")
        return None

# --- 2. DESCARGA Y OPTIMIZACIÓN DE CACHÉ DE BASE CONCILIACIÓN ---
@st.cache_data(ttl=3600)
def descargar_datos_maestros(file_id):
    service = obtener_servicio_drive()
    if not service:
        return pd.DataFrame()
        
    try:
        request = service.files().get_media(fileId=file_id)
        fh = io.BytesIO()
        downloader = MediaIoBaseDownload(fh, request)
        done = False
        while done is False:
            status, done = downloader.next_chunk()
        fh.seek(0)
        
        df = pd.read_excel(fh, dtype={
            'ID_Pedido_Ingresado': str,
            'ID_Factura_Final': str,
            'SKU_Material_Ingresado': str,
            'Codigo_Cliente': str,
            'Motivo_Devolucion': str,
            'Zona_OfVta': str,
            'Tipo_Pedido': str
        })
        
        for c in df.columns:
            if df[c].dtype == object:
                df[c] = df[c].astype(str).str.strip()
        
        for col in ['Fecha_Ingreso', 'Fecha_Facturacion']:
            if col in df.columns:
                if pd.api.types.is_datetime64_any_dtype(df[col]):
                    df[f'{col}_DT'] = df[col]
                else:
                    df[f'{col}_DT'] = pd.to_datetime(df[col], format='%d/%m/%Y', errors='coerce')
                df[f'{col}_TXT'] = df[f'{col}_DT'].dt.strftime('%d/%m/%Y').fillna("Sin Fecha")
            else:
                df[f'{col}_DT'] = pd.NaT
                df[f'{col}_TXT'] = "Sin Fecha"
        
        meses_es = {1:'Enero', 2:'Febrero', 3:'Marzo', 4:'Abril', 5:'Mayo', 6:'Junio',
                    7:'Julio', 8:'Agosto', 9:'Septiembre', 10:'Octubre', 11:'Noviembre', 12:'Diciembre'}
        
        df['Mes_Ingreso'] = df['Fecha_Ingreso_DT'].dt.month.map(meses_es).fillna("Sin Mes")
        
        if 'Zona_OfVta' in df.columns:
            df['Zona_OfVta_Clean'] = df['Zona_OfVta'].astype(str).str.strip().str.upper()
        else:
            df['Zona_OfVta_Clean'] = "SIN ZONA"
            
        df['Canal_UI'] = df['Tipo_Pedido'].map({'GENERAL': 'COSTEÑO', 'PEDIDO BEES': 'BEES'}).fillna(df['Tipo_Pedido'])
            
        columnas_num = ['Valor_Neto_Ingresado', 'Impuestos_Ingresados', 'TOTAL', 
                        'Cantidad_Ingresada', 'Peso_Ingresado', 'Valor_Neto_Facturado', 
                        'Cantidad_Facturada', 'Peso_Facturado']
        for col in columnas_num:
            if col in df.columns:
                df[col] = pd.to_numeric(df[col], errors='coerce').fillna(0)
                
        return df
    except Exception as e:
        st.error(f"❌ Error al descargar el Excel Base de Conciliación: {e}")
        return pd.DataFrame()

# --- 2.1 DESCARGA DE MAESTRO SKU (MÉTODO BYPASS DE ALTA VELOCIDAD) ---
@st.cache_data(ttl=3600)
def descargar_maestro_sku_directo(url_exportacion):
    try:
        df_sku = pd.read_excel(url_exportacion, dtype={
            'Material': str,
            'Marca': str,
            'Categoria Cuota': str
        })
        
        df_sku['Material'] = df_sku['Material'].astype(str).str.strip()
        df_sku['Marca'] = df_sku['Marca'].astype(str).str.strip().fillna("SIN MARCA")
        df_sku['Categoria Cuota'] = df_sku['Categoria Cuota'].astype(str).str.strip().fillna("SIN CATEGORIA")
        
        df_sku = df_sku[['Material', 'Marca', 'Categoria Cuota']].drop_duplicates('Material')
        return df_sku
    except Exception as e:
        st.error(f"⚠️ Alerta Bypass SKU: No se pudo acoplar el maestro desde la URL. Detalles: {e}")
        return pd.DataFrame()

# --- 3. INGESTACIÓN EN PARALELO Y CRUCE EXTENDED ETL ---
df_base_raw = descargar_datos_maestros(FILE_ID_CONCILIACION)
df_sku_raw  = descargar_maestro_sku_directo(URL_MAESTRO_SKU)

if not df_base_raw.empty:
    if not df_sku_raw.empty:
        df_raw = pd.merge(
            df_base_raw, 
            df_sku_raw, 
            left_on='SKU_Material_Ingresado', 
            right_on='Material', 
            how='left'
        )
        df_raw['Categoria Cuota'] = df_raw['Categoria Cuota'].fillna("No Catalogado")
        df_raw['Marca'] = df_raw['Marca'].fillna("No Catalogado")
    else:
        df_raw = df_base_raw.copy()
        df_raw['Categoria Cuota'] = "Sin Conexión Maestro"
        df_raw['Marca'] = "Sin Conexión Maestro"

    if 'Fecha_Ingreso_DT' in df_raw.columns:
        max_date_ingreso = df_raw['Fecha_Ingreso_DT'].max()
        fecha_actualizacion_str = max_date_ingreso.strftime('%d/%m/%Y') if pd.notna(max_date_ingreso) else "No disponible"
    else:
        fecha_actualizacion_str = "No disponible"

    # --- 4. PANEL DE CONTROL LATERAL NATIVO (OCULTABLE) ---
    st.sidebar.header("🎛️ Panel de Control")
    
    # 📆 ORDENAMIENTO CRÓNOLÓGICO SEGURO DE MESES (Evita orden alfabético de la UI)
    meses_existentes = df_raw['Mes_Ingreso'].unique()
    meses_validos = [m for m in LISTA_MESES_ORDENADOS if m in meses_existentes]
    if not meses_validos:
        meses_validos = sorted([m for m in meses_existentes if m not in ["Sin Mes", "nan"]])
        
    mes_sel = st.sidebar.selectbox("📅 Mes de Ingreso", options=meses_validos, index=0)
    opcion_region = st.sidebar.radio("📍 Región Geográfica", ["Lima", "Arequipa", "Ver Todo"], index=0)
    estado_flujo_sel = st.sidebar.selectbox("🔀 Estado del Flujo Visual", ["Entregados", "Facturados", "Ingresados"], index=0)
    zona_analisis = st.sidebar.toggle("🔍 Activar Zona de Análisis Profundo", value=False)
    
    if st.sidebar.button("🔄 Refrescar Base"):
        st.cache_data.clear()
        st.sidebar.success("¡Caché Sincronizada!")
        st.rerun()

    # --- 5. CORE ENGINE: FILTRADO SEGURO POR REGION ---
    if opcion_region == "Lima":
        df_region = df_raw[df_raw['Zona_OfVta_Clean'] == "LIMA"]
    elif opcion_region == "Arequipa":
        df_region = df_raw[df_raw['Zona_OfVta_Clean'] == "AREQUIPA"]
    else:
        df_region = df_raw.copy()

    # --- 5.1 MATRIZ DE CONSTRUCCIÓN TRANSVERSAL ---
    df_base_mes = df_region[df_region['Mes_Ingreso'] == mes_sel]
    
    df_ingresados = df_base_mes.copy()
    df_facturados = df_base_mes[
        (df_base_mes['ID_Factura_Final'].notna()) & 
        (df_base_mes['ID_Factura_Final'].astype(str) != "0") & 
        (df_base_mes['ID_Factura_Final'].astype(str) != "")
    ]
    condicion_entregado = (df_facturados['Motivo_Devolucion'].isna()) | (df_facturados['Motivo_Devolucion'].astype(str) == "") | (df_facturados['Motivo_Devolucion'].astype(str).str.upper() == "NAN")
    df_entregados = df_facturados[condicion_entregado]

    if estado_flujo_sel == "Ingresados":
        df_activo_visual = df_ingresados.copy()
    elif estado_flujo_sel == "Facturados":
        df_activo_visual = df_facturados.copy()
    else:
        df_activo_visual = df_entregados.copy()

    # --- 6. RENDERIZADO DE LA INTERFAZ PRINCIPAL ---
    if not zona_analisis:
        st.title(f"📊 Dashboard Operativo — {mes_sel.upper()} ({opcion_region.upper()})")
        st.markdown(f"Mapeando datos en Estado: **{estado_flujo_sel.upper()}** (Base en Mes de Ingreso con criterio en fecha de facturación) | 📅 Última actualización base: `{fecha_actualizacion_str}`")
        st.markdown("")

        # --- 6.1 GRÁFICOS DE PARTICIPACIÓN ---
        summary_metrics = df_activo_visual.groupby('Canal_UI').agg(
            Pedidos=('ID_Pedido_Ingresado', 'nunique'),
            Peso=('Peso_Ingresado', 'sum'),
            Dinero=('TOTAL', 'sum')
        ).reset_index()
        
        if summary_metrics.empty or summary_metrics['Pedidos'].sum() == 0:
            st.info(f"📋 No se registran movimientos para el estado {estado_flujo_sel} en el mes seleccionado.")
        else:
            g1, g2, g3 = st.columns(3)
            colores_corporativos = ['#4A3B5C', '#17A2B8', '#FFC107']
            
            with g1:
                st.plotly_chart(px.pie(summary_metrics, values='Pedidos', names='Canal_UI', hole=0.4,
                                      title=f"% Pedidos Únicos", color_discrete_sequence=colores_corporativos).update_layout(showlegend=False, height=170, margin=dict(t=30, b=0, l=0, r=0)), use_container_width=True)
            with g2:
                st.plotly_chart(px.pie(summary_metrics, values='Peso', names='Canal_UI', hole=0.4,
                                      title=f"% Peso Ingresado", color_discrete_sequence=colores_corporativos).update_layout(showlegend=False, height=170, margin=dict(t=30, b=0, l=0, r=0)), use_container_width=True)
            with g3:
                st.plotly_chart(px.pie(summary_metrics, values='Dinero', names='Canal_UI', hole=0.4,
                                      title=f"% Capital Total", color_discrete_sequence=colores_corporativos).update_layout(showlegend=False, height=170, margin=dict(t=30, b=0, l=0, r=0)), use_container_width=True)
            
            # --- 6.2 DESGLOSE NUMÉRICO COMPATIBLE CON LIGHT MODE ---
            st.markdown("#### 🔢 Desglose Estructural de Canales")
            
            total_pedidos_gen = summary_metrics['Pedidos'].sum()
            total_peso_gen = summary_metrics['Peso'].sum()
            total_dinero_gen = summary_metrics['Dinero'].sum()
            
            rm1, rm2, rm3 = st.columns(3)
            with rm1:
                for _, row in summary_metrics.iterrows():
                    lbl_color = "violet" if row['Canal_UI'] == "COSTEÑO" else "blue"
                    st.markdown(f"**:{lbl_color}[{row['Canal_UI']}]:** {row['Pedidos']:,} Pedidos")
                st.markdown(f"**TOTAL GENERAL:** {total_pedidos_gen:,} Pedidos")
            with rm2:
                for _, row in summary_metrics.iterrows():
                    lbl_color = "violet" if row['Canal_UI'] == "COSTEÑO" else "blue"
                    st.markdown(f"**:{lbl_color}[{row['Canal_UI']}]:** {row['Peso']:,.1f} Kg")
                st.markdown(f"**TOTAL GENERAL:** {total_peso_gen:,.1f} Kg")
            with rm3:
                for _, row in summary_metrics.iterrows():
                    lbl_color = "violet" if row['Canal_UI'] == "COSTEÑO" else "blue"
                    solles_val = row['Dinero']
                    usd_val = solles_val / TC_FIJO
                    st.markdown(f"**:{lbl_color}[{row['Canal_UI']}]:** S/. {solles_val:,.2f} | \$ {usd_val:,.2f}")
                st.markdown(f"**TOTAL GENERAL:** S/. {total_dinero_gen:,.2f} | \$ {total_dinero_gen/TC_FIJO:,.2f}")
        
        st.markdown("---")
        
        # --- 6.3 INDICADORES COMERCIALES ADAPTATIVOS ---
        st.markdown(f"### 🧮 Indicadores de Tracción Comercial — Estado Actual: `{estado_flujo_sel.upper()}`")
        
        def calcular_kpis_dinamicos(df_sub_canal):
            p_unicos = df_sub_canal['ID_Pedido_Ingresado'].nunique()
            # 🌟 MEJORA: Conteo de clientes únicos por código unificado garantizado
            c_unicos = df_sub_canal['Codigo_Cliente'].nunique()
            monto_total = df_sub_canal['TOTAL'].sum()
            
            pedidos_por_cliente = p_unicos / c_unicos if c_unicos > 0 else 0
            ticket_promedio = monto_total / p_unicos if p_unicos > 0 else 0
            return pedidos_por_cliente, ticket_promedio, c_unicos

        df_costeno_kpi = df_activo_visual[df_activo_visual['Canal_UI'] == 'COSTEÑO']
        df_bees_kpi = df_activo_visual[df_activo_visual['Canal_UI'] == 'BEES']
        
        kp_c_pc, kp_c_tk, kp_c_cli = calcular_kpis_dinamicos(df_costeno_kpi)
        kp_b_pc, kp_b_tk, kp_b_cli = calcular_kpis_dinamicos(df_bees_kpi)
        
        card1, card2 = st.columns(2)
        with card1:
            with st.container(border=True):
                st.markdown("### ⚙️ COSTEÑO")
                st.markdown(f"**Clientes Únicos Activos:** {kp_c_cli:,} Compradores")
                st.markdown(f"**N° Pedidos por Cliente Promedio:** {kp_c_pc:,.2f}")
                st.markdown(f"**Ticket Promedio:** S/. {kp_c_tk:,.2f} | \$ {kp_c_tk/TC_FIJO:,.2f}")
        with card2:
            with st.container(border=True):
                st.markdown("### 🐝 BEES")
                st.markdown(f"**Clientes Únicos Activos:** {kp_b_cli:,} Compradores")
                st.markdown(f"**N° Pedidos por Cliente Promedio:** {kp_b_pc:,.2f}")
                st.markdown(f"**Ticket Promedio:** S/. {kp_b_tk:,.2f} | \$ {kp_b_tk/TC_FIJO:,.2f}")
            
        st.markdown("---")
        
        # --- 6.4 RENDIMIENTO DE ETAPAS ---
        st.markdown("### 📊 Rendimiento de Etapas y Efectividad del Canal")
        canal_funnel = st.radio("📊 Filtrar Canal Logístico", ["Ambos", "COSTEÑO", "BEES"], index=0, horizontal=True)
        
        df_ing_f = df_ingresados.copy()
        df_fac_f = df_facturados.copy()
        df_ent_f = df_entregados.copy()
        
        if canal_funnel != "Ambos":
            df_ing_f = df_ing_f[df_ing_f['Canal_UI'] == canal_funnel]
            df_fac_f = df_fac_f[df_fac_f['Canal_UI'] == canal_funnel]
            df_ent_f = df_ent_f[df_ent_f['Canal_UI'] == canal_funnel]
            
        c_ingresados = df_ing_f['ID_Pedido_Ingresado'].nunique()
        c_facturados = df_fac_f['ID_Pedido_Ingresado'].nunique()
        c_entregados = df_ent_f['ID_Pedido_Ingresado'].nunique()
        
        p_facturado = (c_facturados / c_ingresados * 100) if c_ingresados > 0 else 0.0
        p_entregado = (c_entregados / c_ingresados * 100) if c_ingresados > 0 else 0.0
        
        df_barras_funnel = pd.DataFrame({
            'Etapa Comercial': ["1. Ingresados", "2. Facturados", "3. Entregados"],
            'Pedidos Únicos': [c_ingresados, c_facturados, c_entregados],
            'Texto_Visual': [f"{c_ingresados:,}<br>(100%)", f"{c_facturados:,}<br>({p_facturado:.1f}% Ef.)", f"{c_entregados:,}<br>({p_entregado:.1f}% Ef.)"]
        })
        
        fig_columnas = px.bar(df_barras_funnel, x='Etapa Comercial', y='Pedidos Únicos', text='Texto_Visual',
                             color='Etapa Comercial', color_discrete_sequence=["#3B2F4C", "#4A3B5C", "#17A2B8"])
        fig_columnas.update_traces(textposition='inside', textfont=dict(size=14, color="white"))
        fig_columnas.update_layout(showlegend=False, height=220, margin=dict(t=10, b=10, l=10, r=10))
        st.plotly_chart(fig_columnas, use_container_width=True)
        
        st.markdown("#### 📋 Auditoría de Fuga Logística de Pedidos")
        perdidos_en_facturacion = c_ingresados - c_facturados
        perdidos_en_entrega = c_facturados - c_entregados
        
        df_perdidos = pd.DataFrame({
            'Etapa': ["1. Ingresados", "2. Facturados", "3. Entregados"],
            'Pedidos Únicos Reales': [c_ingresados, c_facturados, c_entregados],
            'Efectividad Relativa': ["100.00%", f"{p_facturado:.2f}%", f"{p_entregado:.2f}%"],
            'Pedidos Perdidos en Fase': ["-", f"{perdidos_en_facturacion:,} Pedidos (No Facturados)", f"{perdidos_en_entrega:,} Pedidos (Devoluciones)"]
        })
        st.dataframe(df_perdidos, width='stretch', hide_index=True)

        # --- 6.5 🌟 NUEVA MEJORA: GRÁFICO DE LÍNEAS CON MARCADORES (EVOLUCIÓN INTERACTIVA) ---
        st.markdown("---")
        st.markdown("### 📈 Evolución y Tendencia Mensual Operativa")
        st.caption("Filtra y analiza el comportamiento histórico de la operación. Este gráfico se recalcula según la región y canal logístico seleccionado arriba.")
        
        # Selector dinámico de indicadores clave
        metrica_tendencia = st.selectbox(
            "📊 Seleccione la métrica para graficar la tendencia histórica:",
            ["Capital Total (Ganancia Bruta - GMV)", "Pedidos Únicos", "Peso Total Ingresado (Kg)", "Clientes Únicos (Códigos)"]
        )
        
        # Agrupación por Mes_Ingreso sobre la base regional
        df_tendencia_base = df_region.copy()
        if canal_funnel != "Ambos":
            df_tendencia_base = df_tendencia_base[df_tendencia_base['Canal_UI'] == canal_funnel]
            
        df_trend_grouped = df_tendencia_base.groupby('Mes_Ingreso').agg(
            TOTAL=('TOTAL', 'sum'),
            Pedidos_Unicos=('ID_Pedido_Ingresado', 'nunique'),
            Peso_Total=('Peso_Ingresado', 'sum'),
            Clientes_Unicos=('Codigo_Cliente', 'nunique')
        ).reset_index()
        
        # Alineación cronológica para evitar desorden alfabético de Plotly
        df_trend_grouped['Mes_Index'] = df_trend_grouped['Mes_Ingreso'].map(lambda x: LISTA_MESES_ORDENADOS.index(x) if x in LISTA_MESES_ORDENADOS else 99)
        df_trend_grouped = df_trend_grouped.sort_values('Mes_Index')
        
        if metrica_tendencia == "Capital Total (Ganancia Bruta - GMV)":
            y_col = 'TOTAL'
            title_trend = "Evolución Mensual del Capital Total (S/.)"
            ytick_format = "S/. %{y:,.2f}"
        elif metrica_tendencia == "Pedidos Únicos":
            y_col = 'Pedidos_Unicos'
            title_trend = "Evolución Mensual de Pedidos Únicos Procesados"
            ytick_format = "%{y:,} Pedidos"
        elif metrica_tendencia == "Peso Total Ingresado (Kg)":
            y_col = 'Peso_Total'
            title_trend = "Evolución Mensual del Peso Total Comercializado (Kg)"
            ytick_format = "%{y:,.1f} Kg"
        else:
            y_col = 'Clientes_Unicos'
            title_trend = "Evolución Mensual de Clientes Únicos Atendidos"
            ytick_format = "%{y:,} Clientes"
            
        fig_trend = px.line(
            df_trend_grouped, 
            x='Mes_Ingreso', 
            y=y_col, 
            markers=True, 
            title=title_trend,
            color_discrete_sequence=['#17A2B8']
        )
        fig_trend.update_traces(
            hovertemplate="<b>Mes:</b> %{x}<br><b>Valor:</b> " + ytick_format + "<extra></extra>",
            line=dict(width=3),
            marker=dict(size=9, symbol="circle")
        )
        fig_trend.update_layout(height=280, margin=dict(t=40, b=20, l=40, r=20), xaxis_title="", yaxis_title="")
        st.plotly_chart(fig_trend, use_container_width=True)

    else:
        # --- 7. ZONA DE ANÁLISIS PROFUNDO ---
        st.title(f"🔍 Análisis de Efectividad y Devoluciones — {mes_sel}")
        st.markdown(f"Mapeando datos en Estado: **{estado_flujo_sel.upper()}** (Base en Mes de Ingreso con criterio en fecha de facturación) | 📅 Última actualización base: `{fecha_actualizacion_str}`")
        st.markdown("")
        
        st.markdown("#### 📈 Matriz de Conversión Logística por Canal Comercial")
        
        def extraer_metricas_embudo_canal(df_ing_raw, df_fac_raw, df_ent_raw, canal_name):
            ing = df_ing_raw[df_ing_raw['Canal_UI'] == canal_name]['ID_Pedido_Ingresado'].nunique()
            fac = df_fac_raw[df_fac_raw['Canal_UI'] == canal_name]['ID_Pedido_Ingresado'].nunique()
            ent = df_ent_raw[df_ent_raw['Canal_UI'] == canal_name]['ID_Pedido_Ingresado'].nunique()
            
            ef_facturacion = (fac / ing * 100) if ing > 0 else 0.0
            ef_entrega = (ent / fac * 100) if fac > 0 else 0.0
            ef_global = (ent / ing * 100) if ing > 0 else 0.0
            
            return [f"{ing:,}", f"{fac:,} ({ef_facturacion:.2f}%)", f"{ent:,} ({ef_entrega:.2f}%)", f"{ef_global:.2f}%"]

        row_costeno = extraer_metricas_embudo_canal(df_ingresados, df_facturados, df_entregados, "COSTEÑO")
        row_bees = extraer_metricas_embudo_canal(df_ingresados, df_facturados, df_entregados, "BEES")
        
        df_conversion_negocios = pd.DataFrame({
            'Canal de Negocio': ["⚙️ COSTEÑO", "🐝 BEES"],
            '1. Pedidos Ingresados': [row_costeno[0], row_bees[0]],
            '2. Facturados (% Ef. vs Ing.)': [row_costeno[1], row_bees[1]],
            '3. Entregados (% Ef. vs Fac.)': [row_costeno[2], row_bees[2]],
            'Efectividad Final (Ing ➔ Ent)': [row_costeno[3], row_bees[3]]
        })
        st.dataframe(df_conversion_negocios, width='stretch', hide_index=True)
        
        st.markdown("---")
        
        # --- 7.2 AUDITORÍA Y AGRUPACIÓN ESTRATÉGICA DE MOTIVOS ---
        st.markdown("#### 📋 Distribución y Participación de Motivos de Devolución")
        canal_dev = st.radio("🔀 Filtrar Canal de Auditoría", ["Ambos", "COSTEÑO", "BEES"], index=0, horizontal=True)
        
        df_base_devoluciones = df_base_mes[
            df_base_mes['Motivo_Devolucion'].notna() & 
            (df_base_mes['Motivo_Devolucion'].astype(str) != "") &
            (df_base_mes['Motivo_Devolucion'].astype(str).str.upper() != "NAN")
        ]
        
        if canal_dev != "Ambos":
            df_devs_reales = df_base_devoluciones[df_base_devoluciones['Canal_UI'] == canal_dev].copy()
        else:
            df_devs_reales = df_base_devoluciones.copy()
            
        if not df_devs_reales.empty:
            
            def mapear_a_macrocategoria(motivo):
                m = str(motivo).upper()
                if any(x in m for x in ["CALIDAD", "MAL ESTADO", "VENCIDO", "AVARIADO", "ROTO", "DAÑADO"]):
                    return "📦 Problemas de Calidad/Producto"
                elif any(x in m for x in ["PRECIO", "DESCUENTO", "COMERCIAL", "VALOR", "ERRADO"]):
                    return "💰 Discrepancia Comercial/Precio"
                elif any(x in m for x in ["AUSENTE", "CERRADO", "NO TIENE", "PAGO", "DINERO", "EFECTIVO", "RECHAZA"]):
                    return "👥 Restricción del Cliente"
                elif any(x in m for x in ["DUPLICADO", "SISTEMA", "ERROR PEDIDO", "NO SOLICITO"]):
                    return "⚙️ Error Administrativo/Sistema"
                else:
                    return "🚚 Otras Causas Logísticas"

            df_devs_reales['Macrocategoria'] = df_devs_reales['Motivo_Devolucion'].apply(mapear_a_macrocategoria)
            
            df_macro_chart = df_devs_reales.groupby('Macrocategoria').agg(
                Pedidos_Unicos=('ID_Pedido_Ingresado', 'nunique')
            ).reset_index().sort_values('Pedidos_Unicos', ascending=True)
            
            fig_macro = px.bar(
                df_macro_chart, 
                y='Macrocategoria', 
                x='Pedidos_Unicos', 
                orientation='h',
                title="Análisis Ejecutivo: Macrocategorías de Rechazo",
                labels={'Pedidos_Unicos': 'Pedidos Afectados', 'Macrocategoria': ''},
                color_discrete_sequence=['#17A2B8']
            )
            fig_macro.update_layout(height=160, margin=dict(t=30, b=10, l=10, r=10))
            st.plotly_chart(fig_macro, use_container_width=True)
            
            # Tabla detallada
            pivot_dev = df_devs_reales.groupby('Motivo_Devolucion').agg(
                Total_Pedidos=('ID_Pedido_Ingresado', 'nunique'),
                Costeno_Pedidos=('ID_Pedido_Ingresado', lambda x: x[df_devs_reales['Canal_UI'] == 'COSTEÑO'].nunique()),
                Bees_Pedidos=('ID_Pedido_Ingresado', lambda x: x[df_devs_reales['Canal_UI'] == 'BEES'].nunique()),
                Dinero_Impactado=('TOTAL', 'sum')
            ).reset_index()
            
            gran_total_pedidos = pivot_dev['Total_Pedidos'].sum()
            pivot_dev['% Participación'] = (pivot_dev['Total_Pedidos'] / gran_total_pedidos * 100).map("{:.2f}%".format)
            pivot_dev = pivot_dev.sort_values(by='Total_Pedidos', ascending=False)
            
            columnas_render = ['Motivo_Devolucion', 'Total_Pedidos', 'Costeno_Pedidos', 'Bees_Pedidos', 'Dinero_Impactado', '% Participación']
            if canal_dev == "COSTEÑO":
                columnas_render.remove('Bees_Pedidos')
            elif canal_dev == "BEES":
                columnas_render.remove('Costeno_Pedidos')
                
            pivot_dev = pivot_dev[columnas_render]
            
            total_row = {
                'Motivo_Devolucion': 'TOTAL GENERAL',
                'Total_Pedidos': pivot_dev['Total_Pedidos'].sum(),
                'Dinero_Impactado': pivot_dev['Dinero_Impactado'].sum(),
                '% Participación': '100.00%'
            }
            if 'Costeno_Pedidos' in pivot_dev.columns:
                total_row['Costeno_Pedidos'] = pivot_dev['Costeno_Pedidos'].sum()
            if 'Bees_Pedidos' in pivot_dev.columns:
                total_row['Bees_Pedidos'] = pivot_dev['Bees_Pedidos'].sum()
                
            pivot_dev = pd.concat([pivot_dev, pd.DataFrame([total_row])], ignore_index=True)
            
            usd_impacto_total = total_row['Dinero_Impactado'] / TC_FIJO
            st.metric(f"📉 Capital Retenido Afectado ({canal_dev.upper()})", f"S/. {total_row['Dinero_Impactado']:,.2f} | $ {usd_impacto_total:,.2f}")
            
            # 🌟 NUEVA MEJORA: SOMBREADO TENUE ADAPTATIVO POR FILA CON PALETA EJECUTIVA (LIGHT MODE BLINDADO)
            def aplicar_estilos_filas_devolucion(row):
                motivo = row['Motivo_Devolucion']
                if motivo == 'TOTAL GENERAL':
                    return ['background-color: rgba(128, 128, 128, 0.18); font-weight: bold;'] * len(row)
                
                cat = mapear_a_macrocategoria(motivo)
                if "Restricción del Cliente" in cat:
                    return ['background-color: rgba(156, 39, 176, 0.07);'] * len(row)      # Morado Tenue
                elif "Otras Causas Logísticas" in cat:
                    return ['background-color: rgba(255, 152, 0, 0.07);'] * len(row)      # Anaranjado Tenue
                elif "Discrepancia Comercial/Precio" in cat:
                    return ['background-color: rgba(76, 175, 80, 0.07);'] * len(row)      # Verde Tenue
                elif "Problemas de Calidad/Producto" in cat:
                    return ['background-color: rgba(139, 69, 19, 0.07);'] * len(row)      # Marrón Madera Tenue
                return [''] * len(row)

            # Inyección del Styler con compatibilidad total en column_config
            st.dataframe(
                pivot_dev.style.apply(aplicar_estilos_filas_devolucion, axis=1),
                width='stretch',
                hide_index=True,
                column_config={
                    "Motivo_Devolucion": "Motivo de Rechazo Detallado",
                    "Total_Pedidos": "Pedidos Únicos",
                    "Costeno_Pedidos": "Vol. COSTEÑO",
                    "Bees_Pedidos": "Vol. BEES",
                    "Dinero_Impactado": st.column_config.NumberColumn("Dinero Perdido (S/.)", format="S/. %,.2f"),
                    "% Participación": "% Part. Devoluciones"
                }
            )
            
            # --- 7.3 ANÁLISIS DE DENSIDAD POR SKU AFECTADO ---
            st.markdown("---")
            st.markdown("#### 📦 Análisis de Densidad por SKU Afectado (Fuga por Atributo)")
            st.caption("Filtra el impacto financiero de las devoluciones analizando la procedencia por Categoría Comercial o Marca del portafolio unificado.")
            
            criterio_sku = st.radio("🏷️ Segmentar Agrupación por:", ["Categoria Cuota", "Marca"], index=0, horizontal=True)
            
            df_density_sku = df_devs_reales.groupby(criterio_sku).agg(
                Pedidos_Unicos=('ID_Pedido_Ingresado', 'nunique'),
                Capital_Impactado_Soles=('TOTAL', 'sum')
            ).reset_index()
            
            df_density_sku['Capital_Impactado_USD'] = df_density_sku['Capital_Impactado_Soles'] / TC_FIJO
            df_density_sku = df_density_sku.sort_values('Pedidos_Unicos', ascending=False)
            
            fig_sku_density = px.bar(
                df_density_sku.head(10),
                x='Pedidos_Unicos',
                y=criterio_sku,
                orientation='h',
                title=f"Top Impacto por {criterio_sku}",
                labels={'Pedidos_Unicos': 'Pedidos Afectados', criterio_sku: ''},
                color_discrete_sequence=['#4A3B5C']
            )
            fig_sku_density.update_layout(height=170, margin=dict(t=30, b=10, l=10, r=10))
            st.plotly_chart(fig_sku_density, use_container_width=True)
            
            st.dataframe(
                df_density_sku,
                width='stretch',
                hide_index=True,
                column_config={
                    criterio_sku: f"{criterio_sku}",
                    "Pedidos_Unicos": st.column_config.NumberColumn("Pedidos Afectados", format="%d 📦"),
                    "Capital_Impactado_Soles": st.column_config.NumberColumn("Monto Soles", format="S/. %,.2f"),
                    "Capital_Impactado_USD": st.column_config.NumberColumn("Monto Dólares", format="$ %,.2f")
                }
            )

            # --- 7.4 CLIENTES RECURRENTES ---
            st.markdown("---")
            st.markdown("#### 👥 Mapeo de Clientes Recurrentes con Múltiples Devoluciones")
            
            # 🌟 NUEVA MEJORA: Incorporación de la columna de Cantidad Total de SKUs devueltos únicos por comprador
            df_cli_rec = df_devs_reales.groupby(['Codigo_Cliente', 'Canal_UI']).agg(
                Pedidos_Rechazados=('ID_Pedido_Ingresado', 'nunique'),
                Skus_Devueltos_Unicos=('SKU_Material_Ingresado', 'nunique'),
                Monto_Fuga_Soles=('TOTAL', 'sum')
            ).reset_index()
            
            df_cli_rec = df_cli_rec[df_cli_rec['Pedidos_Rechazados'] > 1].sort_values('Pedidos_Rechazados', ascending=False)
            
            if not df_cli_rec.empty:
                df_cli_rec['Monto_Fuga_USD'] = df_cli_rec['Monto_Fuga_Soles'] / TC_FIJO
                st.dataframe(
                    df_cli_rec,
                    width='stretch',
                    hide_index=True,
                    column_config={
                        "Codigo_Cliente": "Código del Cliente",
                        "Canal_UI": "Canal Comprador",
                        "Pedidos_Rechazados": st.column_config.NumberColumn("Cantidad Pedidos Devueltos", format="%d 📦"),
                        "Skus_Devueltos_Unicos": st.column_config.NumberColumn("Cantidad SKUs Devueltos", format="%d 🏷️"),
                        "Monto_Fuga_Soles": st.column_config.NumberColumn("Impacto Bruto (S/.)", format="S/. %,.2f"),
                        "Monto_Fuga_USD": st.column_config.NumberColumn("Impacto Bruto ($)", format="$ %,.2f")
                    }
                )
            else:
                st.info("✨ Operación Óptima: No se registran clientes recurrentes con más de una devolución en este período.")

            # --- 7.5 SCORE DE CONCENTRACIÓN DE CLIENTES CRÍTICOS (PARETO 80/20) ---
            st.markdown("---")
            st.markdown("#### 🎯 Score de Concentración de Clientes Críticos (Análisis de Pareto)")
            st.caption("Aplicación de la regla de Pareto: Identifica de forma matemática al grupo de clientes que concentra el mayor volumen de dinero rebotado de la compañía.")
            
            df_pareto = df_devs_reales.groupby(['Codigo_Cliente', 'Canal_UI']).agg(
                Pedidos_Devueltos=('ID_Pedido_Ingresado', 'nunique'),
                Monto_Fuga_Soles=('TOTAL', 'sum')
            ).reset_index()
            
            if not df_pareto.empty:
                df_pareto = df_pareto.sort_values(by='Monto_Fuga_Soles', ascending=False)
                
                monto_global_dev = df_pareto['Monto_Fuga_Soles'].sum()
                df_pareto['Monto_Acumulado_Soles'] = df_pareto['Monto_Fuga_Soles'].cumsum()
                df_pareto['% Acumulado Capital'] = (df_pareto['Monto_Acumulado_Soles'] / monto_global_dev * 100)
                
                df_pareto['Clasificación Operativa'] = df_pareto['% Acumulado Capital'].apply(
                    lambda x: "🔴 Crítico (Zona Pareto 80%)" if x <= 80.0 else "🟢 Estable (Zona 20%)"
                )
                
                df_pareto['Monto_Fuga_USD'] = df_pareto['Monto_Fuga_Soles'] / TC_FIJO
                df_pareto['% Acumulado Capital_TXT'] = df_pareto['% Acumulado Capital'].map("{:.2f}%".format)
                
                st.dataframe(
                    df_pareto[['Codigo_Cliente', 'Canal_UI', 'Pedidos_Devueltos', 'Monto_Fuga_Soles', 'Monto_Fuga_USD', '% Acumulado Capital_TXT', 'Clasificación Operativa']],
                    width='stretch',
                    hide_index=True,
                    column_config={
                        "Codigo_Cliente": "Código Cliente",
                        "Canal_UI": "Canal",
                        "Pedidos_Devueltos": st.column_config.NumberColumn("Pedidos Dev.", format="%d 📦"),
                        "Monto_Fuga_Soles": st.column_config.NumberColumn("Monto Retenido (S/.)", format="S/. %,.2f"),
                        "Monto_Fuga_USD": st.column_config.NumberColumn("Monto Retenido ($)", format="$ %,.2f"),
                        "% Acumulado Capital_TXT": "% Acumulado",
                        "Clasificación Operativa": "Clasificación Estratégica"
                    }
                )
            else:
                st.info("✨ Sin transacciones rebotadas para procesar la curva de Pareto.")
            
        else:
            st.info(f"✨ Canal {canal_dev.upper()} sin motivos de devolución registrados para el mes de {mes_sel}.")

# --- INSPECCIÓN MASTER ---
st.markdown("---")
with st.expander("📋 Inspección Rápida de la Base de Datos Estructural"):
    if not df_raw.empty:
        st.dataframe(df_region.head(50), width='stretch', hide_index=True)
