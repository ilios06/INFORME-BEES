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

# --- 1. CONEXIÓN SEGURA CON GOOGLE DRIVE (USANDO SECRETS) ---
@st.cache_resource
def obtener_servicio_drive():
    try:
        info_claves = st.secrets["gcp_service_account"]
        creds = service_account.Credentials.from_service_account_info(info_claves)
        return build('drive', 'v3', credentials=creds)
    except Exception as e:
        st.error(f"❌ Error de autenticación: Verifica st.secrets. Detalles: {e}")
        return None

# --- 2. DESCARGA Y OPTIMIZACIÓN DE CACHÉ DE DATOS ---
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
        
        # 🧼 LIMPIEZA ATÓMICA DE ESPACIOS EN BLANCO
        for c in df.columns:
            if df[c].dtype == object:
                df[c] = df[c].astype(str).str.strip()
        
        # ⚡ PROCESAMIENTO DE FECHAS EN CACHÉ
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
        
        # 🌟 REGLA MASTER: El Mes de Ingreso rige transversalmente toda la aplicación
        df['Mes_Ingreso'] = df['Fecha_Ingreso_DT'].dt.month.map(meses_es).fillna("Sin Mes")
        
        # 🧼 NORMALIZACIÓN GEOGRÁFICA Y DE NOMENCLATURA COSTEÑO
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
        st.error(f"❌ Error al descargar e interpretar el Excel de Drive: {e}")
        return pd.DataFrame()

# --- 3. INGESTACIÓN DE DATOS ---
FILE_ID_EXCEL = "1-EoM0rYAmYY_tBkKwL5--746cdUa0tw2"
df_raw = descargar_datos_maestros(FILE_ID_EXCEL)

if not df_raw.empty:
    
    # --- 4. PANEL DE CONTROL COMPACTO Y OCULTABLE EN LA BARRA LATERAL ---
    with st.sidebar.expander("⚙️ **Filtros y Panel de Control**", expanded=True):
        
        # Selección Transversal basada estrictamente en Fecha_Ingreso
        meses_validos = sorted([m for m in df_raw['Mes_Ingreso'].unique() if m not in ["Sin Mes", "nan"]])
        mes_sel = st.selectbox("📅 Mes de Ingreso", options=meses_validos, index=0)
        
        # Región Geográfica Estricta (Lima / Arequipa)
        opcion_region = st.radio("📍 Región Geográfica", ["Lima", "Arequipa", "Ver Todo"], index=0)
        
        # Selector Dinámico de Estado de Flujo para Análisis de Distribución de Gráficos y KPIs
        estado_flujo_sel = st.selectbox("🔀 Estado del Flujo Visual", ["Entregados", "Facturados", "Ingresados"], index=0)
        
        # Selector de Capa de Pantalla
        zona_analisis = st.toggle("🔍 Activar Zona de Análisis Profundo", value=False)
        
        if st.button("🔄 Refrescar Base"):
            st.cache_data.clear()
            st.success("¡Caché Sincronizada!")
            st.rerun()

    # --- 5. ENGINE DE FILTRADO SEGURO POR REGION LITERAL ---
    if opcion_region == "Lima":
        df_region = df_raw[df_raw['Zona_OfVta_Clean'] == "LIMA"]
    elif opcion_region == "Arequipa":
        df_region = df_raw[df_raw['Zona_OfVta_Clean'] == "AREQUIPA"]
    else:
        df_region = df_raw.copy()

    # --- 5.1 MATRIZ DE CONSTRUCCIÓN TEMPORAL (FLUJO TOTAL LOGÍSTICO DEL MES SELECCIONADO) ---
    df_base_mes = df_region[df_region['Mes_Ingreso'] == mes_sel]
    
    # Fase 1: Ingresados Nativos
    df_ingresados = df_base_mes.copy()
    
    # Fase 2: Facturados (Filtro estricto de existencia de factura real)
    df_facturados = df_base_mes[
        (df_base_mes['ID_Factura_Final'].notna()) & 
        (df_base_mes['ID_Factura_Final'].astype(str) != "0") & 
        (df_base_mes['ID_Factura_Final'].astype(str) != "")
    ]
    
    # Fase 3: Entregados (Facturados sin motivos de devolución registrados)
    condicion_entregado = (df_facturados['Motivo_Devolucion'].isna()) | (df_facturados['Motivo_Devolucion'].astype(str) == "") | (df_facturados['Motivo_Devolucion'].astype(str).str.upper() == "NAN")
    df_entregados = df_facturados[condicion_entregado]

    # --- 5.2 ASIGNACIÓN REACTIVA DE DATASET OPERATIVO SEGÚN EL ESTADO SELECCIONADO ---
    if estado_flujo_sel == "Ingresados":
        df_activo_visual = df_ingresados.copy()
    elif estado_flujo_sel == "Facturados":
        df_activo_visual = df_facturados.copy()
    else:
        df_activo_visual = df_entregados.copy()

    # --- 6. RENDERIZADO DE LA INTERFAZ PRINCIPAL ---
    if not zona_analisis:
        st.title(f"📊 Dashboard Operativo — {mes_sel.upper()} ({opcion_region.upper()})")
        st.markdown(f" Mapeando datos en Estado: **{estado_flujo_sel.upper()}** (Calculado con base en Mes de Ingreso)")
        
        # --- 6.1 GRÁFICOS DE PARTICIPACIÓN DE PLOTLY EXPRESS ---
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
                                      title=f"% Pedidos Únicos ({estado_flujo_sel})", color_discrete_sequence=colores_corporativos), use_container_width=True)
            with g2:
                st.plotly_chart(px.pie(summary_metrics, values='Peso', names='Canal_UI', hole=0.4,
                                      title=f"% Peso Ingresado ({estado_flujo_sel})", color_discrete_sequence=colores_corporativos), use_container_width=True)
            with g3:
                st.plotly_chart(px.pie(summary_metrics, values='Dinero', names='Canal_UI', hole=0.4,
                                      title=f"% Capital Total ({estado_flujo_sel})", color_discrete_sequence=colores_corporativos), use_container_width=True)
            
            # --- 6.2 DESGLOSE NUMÉRICO CON LA INCORPORACIÓN DEL TOTAL GENERAL SUPERIOR ---
            st.markdown("#### 🔢 Desglose Estructural de Canales")
            
            total_pedidos_gen = summary_metrics['Pedidos'].sum()
            total_peso_gen = summary_metrics['Peso'].sum()
            total_dinero_gen = summary_metrics['Dinero'].sum()
            
            rm1, rm2, rm3 = st.columns(3)
            with rm1:
                st.markdown(f"<div style='background-color:#2A2A3A; padding:5px; border-radius:5px;'><b>TOTAL GENERAL:</b> {total_pedidos_gen:,} Pedidos</div>", unsafe_allow_html=True)
                for _, row in summary_metrics.iterrows():
                    col_label = "#4A3B5C" if row['Canal_UI'] == "COSTEÑO" else "#17A2B8"
                    st.markdown(f"<b style='color:{col_label};'>{row['Canal_UI']}:</b> {row['Pedidos']:,} Pedidos", unsafe_allow_html=True)
            with rm2:
                st.markdown(f"<div style='background-color:#2A2A3A; padding:5px; border-radius:5px;'><b>TOTAL GENERAL:</b> {total_peso_gen:,.1f} Kg</div>", unsafe_allow_html=True)
                for _, row in summary_metrics.iterrows():
                    col_label = "#4A3B5C" if row['Canal_UI'] == "COSTEÑO" else "#17A2B8"
                    st.markdown(f"<b style='color:{col_label};'>{row['Canal_UI']}:</b> {row['Peso']:,.1f} Kg", unsafe_allow_html=True)
            with rm3:
                st.markdown(f"<div style='background-color:#2A2A3A; padding:5px; border-radius:5px;'><b>TOTAL GENERAL:</b> S/. {total_dinero_gen:,.2f}</div>", unsafe_allow_html=True)
                for _, row in summary_metrics.iterrows():
                    col_label = "#4A3B5C" if row['Canal_UI'] == "COSTEÑO" else "#17A2B8"
                    st.markdown(f"<b style='color:{col_label};'>{row['Canal_UI']}:</b> S/. {row['Dinero']:,.2f}", unsafe_allow_html=True)
        
        st.markdown("---")
        
        # --- 6.3 INDICADORES COMERCIALES ADAPTATIVOS AL ESTADO SELECCIONADO ---
        st.markdown(f"### 🧮 Indicadores de Tracción Comercial — Estado Actual: `{estado_flujo_sel.upper()}`")
        
        def calcular_kpis_dinamicos(df_sub_canal):
            p_unicos = df_sub_canal['ID_Pedido_Ingresado'].nunique()
            c_unicos = df_sub_canal['Codigo_Cliente'].nunique()
            monto_total = df_sub_canal['TOTAL'].sum()
            
            pedidos_por_cliente = p_unicos / c_unicos if c_unicos > 0 else 0
            ticket_promedio = monto_total / p_unicos if p_unicos > 0 else 0
            return pedidos_por_cliente, ticket_promedio

        df_costeno_kpi = df_activo_visual[df_activo_visual['Canal_UI'] == 'COSTEÑO']
        df_bees_kpi = df_activo_visual[df_activo_visual['Canal_UI'] == 'BEES']
        
        kp_c_pc, kp_c_tk = calcular_kpis_dinamicos(df_costeno_kpi)
        kp_b_pc, kp_b_tk = calcular_kpis_dinamicos(df_bees_kpi)
        
        card1, card2 = st.columns(2)
        with card1:
            st.markdown(f"""
            <div style='background-color: #1E1E2E; padding: 15px; border-radius: 10px; border-left: 5px solid #4A3B5C;'>
                <h4 style='margin:0; color:#A3A3C2;'>⚙️ COSTEÑO</h4>
                <p style='margin:5px 0; font-size:18px;'><b>N° Pedidos por Cliente Promedio:</b> {kp_c_pc:,.2f}</p>
                <p style='margin:5px 0; font-size:18px; color:#17A2B8;'><b>Ticket Promedio:</b> S/. {kp_c_tk:,.2f}</p>
            </div>
            """, unsafe_allow_html=True)
        with card2:
            st.markdown(f"""
            <div style='background-color: #1E1E2E; padding: 15px; border-radius: 10px; border-left: 5px solid #17A2B8;'>
                <h4 style='margin:0; color:#A3A3C2;'>🐝 BEES</h4>
                <p style='margin:5px 0; font-size:18px;'><b>N° Pedidos por Cliente Promedio:</b> {kp_b_pc:,.2f}</p>
                <p style='margin:5px 0; font-size:18px; color:#17A2B8;'><b>Ticket Promedio:</b> S/. {kp_b_tk:,.2f}</p>
            </div>
            """, unsafe_allow_html=True)
            
        st.markdown("---")
        
        # --- 6.4 RENDIMIENTO DE ETAPAS Y ANALISIS DE PEDIDOS PERDIDOS EN FASES ---
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
        
        # Gráfico de Columnas Estructurales
        df_barras_funnel = pd.DataFrame({
            'Etapa Comercial': ["1. Ingresados", "2. Facturados", "3. Entregados"],
            'Pedidos Únicos': [c_ingresados, c_facturados, c_entregados],
            'Texto_Visual': [f"{c_ingresados:,}<br>(100%)", f"{c_facturados:,}<br>({p_facturado:.1f}% Ef.)", f"{c_entregados:,}<br>({p_entregado:.1f}% Ef.)"]
        })
        
        fig_columnas = px.bar(df_barras_funnel, x='Etapa Comercial', y='Pedidos Únicos', text='Texto_Visual',
                             color='Etapa Comercial', color_discrete_sequence=["#3B2F4C", "#4A3B5C", "#17A2B8"])
        fig_columnas.update_traces(textposition='inside', textfont=dict(size=14, color="white"))
        fig_columnas.update_layout(showlegend=False, height=240, margin=dict(t=10, b=10, l=10, r=10))
        st.plotly_chart(fig_columnas, use_container_width=True)
        
        # Matriz de Control de Pedidos Perdidos entre Fases
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

    else:
        # --- 7. ZONA DE ANÁLISIS PROFUNDO (AUDITORÍA DE DEVOLUCIONES CON LÍNEA TOTAL FIJA) ---
        st.title(f"🔍 Análisis de Efectividad y Devoluciones — {mes_sel}")
        st.markdown(" Filtrado estructurado bajo el criterio de **Mes de Ingreso**")
        
        st.markdown("#### 📋 Distribución y Participación de Motivos de Devolución")
        canal_dev = st.radio("🔀 Filtrar Canal de Auditoría", ["Ambos", "COSTEÑO", "BEES"], index=0, horizontal=True)
        
        # Aislar motivos de devoluciones sobre el mes de ingreso seleccionado
        df_devs_reales = df_base_mes[
            df_base_mes['Motivo_Devolucion'].notna() & 
            (df_base_mes['Motivo_Devolucion'].astype(str) != "") &
            (df_base_mes['Motivo_Devolucion'].astype(str).str.upper() != "NAN")
        ]
        
        if canal_dev != "Ambos":
            df_devs_reales = df_devs_reales[df_devs_reales['Canal_UI'] == canal_dev]
            
        if not df_devs_reales.empty:
            pivot_dev = df_devs_reales.groupby('Motivo_Devolucion').agg(
                Total_Pedidos=('ID_Pedido_Ingresado', 'nunique'),
                Costeno_Pedidos=('ID_Pedido_Ingresado', lambda x: x[df_devs_reales['Canal_UI'] == 'COSTEÑO'].nunique()),
                Bees_Pedidos=('ID_Pedido_Ingresado', lambda x: x[df_devs_reales['Canal_UI'] == 'BEES'].nunique()),
                Dinero_Impactado=('TOTAL', 'sum')
            ).reset_index()
            
            gran_total_pedidos = pivot_dev['Total_Pedidos'].sum()
            pivot_dev['% Participación'] = (pivot_dev['Total_Pedidos'] / gran_total_pedidos * 100).map("{:.2f}%".format)
            pivot_dev = pivot_dev.sort_values(by='Total_Pedidos', ascending=False)
            
            # 🌟 REGLA DE DINAMISMO EXCLUSIVO: Eliminar columnas del canal no seleccionado
            columnas_render = ['Motivo_Devolucion', 'Total_Pedidos', 'Costeno_Pedidos', 'Bees_Pedidos', 'Dinero_Impactado', '% Participación']
            if canal_dev == "COSTEÑO":
                columnas_render.remove('Bees_Pedidos')
            elif canal_dev == "BEES":
                columnas_render.remove('Costeno_Pedidos')
                
            pivot_dev = pivot_dev[columnas_render]
            
            # 🌟 REGLA DE CIERRE TOTAL: Inserción de Fila Final de Sumatoria Estructural
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
            
            st.dataframe(
                pivot_dev,
                width='stretch',
                hide_index=True,
                column_config={
                    "Motivo_Devolucion": "Motivo de Rechazo",
                    "Total_Pedidos": "Pedidos Únicos",
                    "Costeno_Pedidos": "Vol. COSTEÑO",
                    "Bees_Pedidos": "Vol. BEES",
                    "Dinero_Impactado": st.column_config.NumberColumn("Dinero Perdido", format="S/. %,.2f"),
                    "% Participación": "% Part. Devoluciones"
                }
            )
        else:
            st.info(f"✨ Canal {canal_dev.upper()} sin motivos de devolución registrados para el mes de {mes_sel}.")

# --- INSPECCIÓN MASTER ---
st.markdown("---")
with st.expander("📋 Inspección Rápida de la Base de Datos Estructural"):
    if not df_raw.empty:
        st.dataframe(df_region.head(50), width='stretch', hide_index=True)
