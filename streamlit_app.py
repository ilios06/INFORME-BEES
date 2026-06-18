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
    page_title="Dashboard de Conciliación BEES & GENERAL",
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
        
        # Carga estricta mapeando tipos como texto puro para evitar deformaciones
        df = pd.read_excel(fh, dtype={
            'ID_Pedido_Ingresado': str,
            'ID_Factura_Final': str,
            'SKU_Material_Ingresado': str,
            'Codigo_Cliente': str,
            'Motivo_Devolucion': str,
            'Zona_OfVta': str,
            'Tipo_Pedido': str
        })
        
        # 🧼 LIMPIEZA ATÓMICA DE ESPACIOS EN BLANCO EN TODO EL DATASET
        for c in df.columns:
            if df[c].dtype == object:
                df[c] = df[c].astype(str).str.strip()
        
        # ⚡ PROCESAMIENTO CRÍTICO DE FECHAS EN CACHÉ
        for col in ['Fecha_Ingreso', 'Fecha_Facturacion']:
            if col in df.columns:
                if pd.api.types.is_datetime64_any_dtype(df[col]):
                    df[f'{col}_DT'] = df[col]
                else:
                    df[f'{col}_DT'] = pd.to_datetime(df[col], format='%d/%m/%Y', errors='coerce')
                
                # Renderizado exacto de texto original sin marcas de tiempo
                df[f'{col}_TXT'] = df[f'{col}_DT'].dt.strftime('%d/%m/%Y').fillna("Sin Fecha")
            else:
                df[f'{col}_DT'] = pd.NaT
                df[f'{col}_TXT'] = "Sin Fecha"
        
        meses_es = {1:'Enero', 2:'Febrero', 3:'Marzo', 4:'Abril', 5:'Mayo', 6:'Junio',
                    7:'Julio', 8:'Agosto', 9:'Septiembre', 10:'Octubre', 11:'Noviembre', 12:'Diciembre'}
        
        df['Mes_Ingreso'] = df['Fecha_Ingreso_DT'].dt.month.map(meses_es).fillna("Sin Mes")
        df['Mes_Facturacion'] = df['Fecha_Facturacion_DT'].dt.month.map(meses_es).fillna("Sin Mes")
        
        # 🧼 ESCUDO DE NORMALIZACIÓN GEOGRÁFICA ESTRICTA (Caso Exacto: Lima / Arequipa)
        if 'Zona_OfVta' in df.columns:
            df['Zona_OfVta_Clean'] = df['Zona_OfVta'].astype(str).str.strip().str.upper()
        else:
            df['Zona_OfVta_Clean'] = "SIN ZONA"
            
        # Normalización unificada de Canales Comerciales de la organización
        df['Canal_UI'] = df['Tipo_Pedido'].map({'GENERAL': 'COSTEÑO (GENERAL)', 'PEDIDO BEES': 'BEES'}).fillna(df['Tipo_Pedido'])
            
        # Conversión de valores numéricos para cálculos
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
    
    # --- 4. MAQUETACIÓN EN DOS COLUMNAS: VISUALIZACIÓN (IZQ) Y FILTROS (DER) ---
    col_visualizacion, col_filtros_derecha = st.columns([7, 3])
    
    with col_filtros_derecha:
        st.markdown("<div style='background-color: #1E1E2E; padding: 15px; border-radius: 10px;'>", unsafe_allow_html=True)
        st.header("🎛️ Panel de Control")
        
        # Extracción segura de meses basados en Facturación
        meses_validos = sorted([m for m in df_raw['Mes_Facturacion'].unique() if m not in ["Sin Mes", "nan"]])
        if not meses_validos:
            meses_validos = sorted([m for m in df_raw['Mes_Ingreso'].unique() if m not in ["Sin Mes", "nan"]])
        mes_sel = st.selectbox("📅 Seleccionar Período Mensual", options=meses_validos, index=0)
        
        # 🌟 SOLUCIÓN AL FILTRO DE ZONA: Comparación literal e inequívoca
        opcion_region = st.radio("📍 Filtrar Región Geográfica", ["Lima", "Arequipa", "Ver Todo"], index=0)
        
        # Selector de Vista / Análisis Profundo
        zona_analisis = st.toggle("🔍 Activar Zona de Análisis Profundo", value=False)
        
        if st.button("🔄 Sincronizar Base (Borrar Caché)"):
            st.cache_data.clear()
            st.success("¡Caché liberada!")
            st.rerun()
        st.markdown("</div>", unsafe_allow_html=True)

    # --- 5. CORE ENGINE: FILTRADO SEGURO POR REGION LITERAL ---
    if opcion_region == "Lima":
        df_region = df_raw[df_raw['Zona_OfVta_Clean'] == "LIMA"]
    elif opcion_region == "Arequipa":
        df_region = df_raw[df_raw['Zona_OfVta_Clean'] == "AREQUIPA"]
    else:
        df_region = df_raw.copy()

    # --- REGLA MATRICIAL DE TIEMPOS CRÍTICA ---
    # 1. Ingresados: Se calculan EXCLUSIVAMENTE con su Mes de Ingreso
    df_ingresados_mes = df_region[df_region['Mes_Ingreso'] == mes_sel]
    
    # 2. Facturados y Entregados: Se calculan con su Mes de Facturación
    df_facturados_mes = df_region[df_region['Mes_Facturacion'] == mes_sel]
    
    # Filtro de facturas válidas (Excluye vacíos, nulos y ceros estrictos)
    df_facturas_validas = df_facturados_mes[
        (df_facturados_mes['ID_Factura_Final'].notna()) & 
        (df_facturados_mes['ID_Factura_Final'].astype(str) != "0") & 
        (df_facturados_mes['ID_Factura_Final'].astype(str) != "")
    ]
    
    # 3. Entregados: Facturas válidas donde el Motivo de Devolución esté limpio
    condicion_entregado = (df_facturas_validas['Motivo_Devolucion'].isna()) | (df_facturas_validas['Motivo_Devolucion'].astype(str) == "") | (df_facturas_validas['Motivo_Devolucion'].astype(str).str.upper() == "NAN")
    df_entregados_mes = df_facturas_validas[condicion_entregado]

    # --- 6. RENDERIZADO EN LA COLUMNA DE VISUALIZACIÓN (IZQUIERDA) ---
    with col_visualizacion:
        if not zona_analisis:
            st.title(f"📊 Dashboard Operativo — {mes_sel.upper()} ({opcion_region.upper()})")
            
            # --- 6.1 TRES GRÁFICOS PEQUEÑOS DE PARTICIPACIÓN ---
            summary_metrics = df_facturados_mes.groupby('Canal_UI').agg(
                Pedidos=('ID_Pedido_Ingresado', 'nunique'),
                Peso=('Peso_Ingresado', 'sum'),
                Dinero=('TOTAL', 'sum')
            ).reset_index()
            
            if summary_metrics.empty or summary_metrics['Pedidos'].sum() == 0:
                st.info(f"📋 No se registran movimientos facturados en {mes_sel} para la región de {opcion_region}.")
            else:
                g1, g2, g3 = st.columns(3)
                colores_corporativos = ['#4A3B5C', '#17A2B8', '#FFC107']
                
                with g1:
                    fig1 = px.pie(summary_metrics, values='Pedidos', names='Canal_UI', hole=0.4,
                                  title="Part. % Pedidos Únicos", color_discrete_sequence=colores_corporativos)
                    fig1.update_layout(showlegend=False, height=190, margin=dict(t=30, b=0, l=0, r=0))
                    st.plotly_chart(fig1, use_container_width=True)
                with g2:
                    fig2 = px.pie(summary_metrics, values='Peso', names='Canal_Visual' if 'Canal_Visual' in summary_metrics else 'Canal_UI', hole=0.4,
                                  title="Part. % Peso Ingresado (Kg)", color_discrete_sequence=colores_corporativos)
                    fig2.update_layout(showlegend=False, height=190, margin=dict(t=30, b=0, l=0, r=0))
                    st.plotly_chart(fig2, use_container_width=True)
                with g3:
                    fig3 = px.pie(summary_metrics, values='Dinero', names='Canal_UI', hole=0.4,
                                  title="Part. % Capital TOTAL (S/.)", color_discrete_sequence=colores_corporativos)
                    fig3.update_layout(showlegend=False, height=190, margin=dict(t=30, b=0, l=0, r=0))
                    st.plotly_chart(fig3, use_container_width=True)
                
                # Desglose numérico directo abajo
                st.markdown("#### 🔢 Desglose Resumido de Canales")
                rm1, rm2, rm3 = st.columns(3)
                for _, row in summary_metrics.iterrows():
                    canal_name = row['Canal_UI']
                    col_label = "#4A3B5C" if "COSTEÑO" in canal_name else "#17A2B8"
                    rm1.markdown(f"<b style='color:{col_label};'>{canal_name}:</b> {row['Pedidos']:,} Pedidos", unsafe_allow_html=True)
                    rm2.markdown(f"<b style='color:{col_label};'>{canal_name}:</b> {row['Peso']:,.1f} Kg", unsafe_allow_html=True)
                    rm3.markdown(f"<b style='color:{col_label};'>{canal_name}:</b> S/. {row['Dinero']:,.2f}", unsafe_allow_html=True)
            
            st.markdown("---")
            
            # --- 6.2 INDICADORES CON FÓRMULAS MATEMÁTICAS AVANZADAS ---
            st.markdown("### 🧮 Indicadores de Tracción Comercial (Basado en Facturación)")
            
            def calcular_kpis_estructurales(df_sub_canal):
                p_unicos = df_sub_canal['ID_Pedido_Ingresado'].nunique()
                c_unicos = df_sub_canal['Codigo_Cliente'].nunique()
                monto_total = df_sub_canal['TOTAL'].sum()
                
                pedidos_por_cliente = p_unicos / c_unicos if c_unicos > 0 else 0
                ticket_promedio = monto_total / p_unicos if p_unicos > 0 else 0
                return pedidos_por_cliente, ticket_promedio

            df_costeno = df_facturados_mes[df_facturados_mes['Tipo_Pedido'] == 'GENERAL']
            df_bees = df_facturados_mes[df_facturados_mes['Tipo_Pedido'] == 'PEDIDO BEES']
            
            kp_c_pc, kp_c_tk = calcular_kpis_estructurales(df_costeno)
            kp_b_pc, kp_b_tk = calcular_kpis_structurales = calcular_kpis_estructurales(df_bees)
            
            card1, card2 = st.columns(2)
            with card1:
                st.markdown(f"""
                <div style='background-color: #1E1E2E; padding: 15px; border-radius: 10px; border-left: 5px solid #4A3B5C;'>
                    <h4 style='margin:0; color:#A3A3C2;'>⚙️ COSTEÑO (GENERAL)</h4>
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
            
            # --- 6.3 🌟 NUEVA EXIGENCIA: GRÁFICO DE COLUMNAS DE EMBUDO CON FILTRO DINÁMICO ---
            st.markdown("### 📊 Rendimiento de Etapas y Efectividad del Canal")
            
            canal_funnel = st.radio("📊 Filtrar Canal del Gráfico", ["Ambos", "COSTEÑO (GENERAL)", "BEES"], index=0, horizontal=True, key="funnel_channel_sel")
            
            # Aplicar filtro de canal dinámico al embudo
            df_ing_f = df_ingresados_mes.copy()
            df_fac_f = df_facturas_validas.copy()
            df_ent_f = df_entregados_mes.copy()
            
            if canal_funnel != "Ambos":
                df_ing_f = df_ing_f[df_ing_f['Canal_UI'] == canal_funnel]
                df_fac_f = df_fac_f[df_fac_f['Canal_UI'] == canal_funnel]
                df_ent_f = df_ent_f[df_ent_f['Canal_UI'] == canal_funnel]
                
            c_ingresados = df_ing_f['ID_Pedido_Ingresado'].nunique()
            c_facturados = df_fac_f['ID_Pedido_Ingresado'].nunique()
            c_entregados = df_ent_f['ID_Pedido_Ingresado'].nunique()
            
            # Cálculo de porcentajes de efectividad correspondientes (Efectividad absoluta vs el paso inicial)
            p_ingresado = 100.0
            p_facturado = (c_facturados / c_ingresados * 100) if c_ingresados > 0 else 0.0
            p_entregado = (c_entregados / c_ingresados * 100) if c_ingresados > 0 else 0.0
            
            # Construcción de la matriz visual de columnas
            df_barras_funnel = pd.DataFrame({
                'Etapa Comercial': ["1. Ingresados", "2. Facturados", "3. Entregados"],
                'Pedidos Únicos': [c_ingresados, c_facturados, c_entregados],
                'Texto_Visual': [f"{c_ingresados:,}<br>(100%)", f"{c_facturados:,}<br>({p_facturado:.1f}% Ef.)", f"{c_entregados:,}<br>({p_entregado:.1f}% Ef.)"]
            })
            
            fig_columnas = px.bar(
                df_barras_funnel, 
                x='Etapa Comercial', 
                y='Pedidos Únicos',
                text='Texto_Visual',
                color='Etapa Comercial',
                color_discrete_sequence=["#3B2F4C", "#4A3B5C", "#17A2B8"]
            )
            fig_columnas.update_traces(textposition='inside', textfont=dict(size=14, color="white"))
            fig_columnas.update_layout(showlegend=False, height=280, margin=dict(t=10, b=10, l=10, r=10))
            st.plotly_chart(fig_columnas, use_container_width=True)

        else:
            # --- ZONA DE ANÁLISIS DE METRICAS REBUSCADAS (ANÁLISIS PROFUNDO) ---
            st.title(f"🔍 Análisis de Efectividad y Devoluciones — {mes_sel}")
            
            f_c = df_facturas_validas[df_facturas_validas['Tipo_Pedido'] == 'GENERAL']['ID_Pedido_Ingresado'].nunique()
            e_c = df_entregados_mes[df_entregados_mes['Tipo_Pedido'] == 'GENERAL']['ID_Pedido_Ingresado'].nunique()
            f_b = df_facturas_validas[df_facturas_validas['Tipo_Pedido'] == 'PEDIDO BEES']['ID_Pedido_Ingresado'].nunique()
            e_b = df_entregados_mes[df_entregados_mes['Tipo_Pedido'] == 'PEDIDO BEES']['ID_Pedido_Ingresado'].nunique()
            
            ef_costeno = (e_c / f_c * 100) if f_c > 0 else 100
            ef_bees = (e_b / f_b * 100) if f_b > 0 else 100
            
            col_ef1, col_ef2 = st.columns(2)
            with col_ef1:
                st.metric("📉 Efectividad Logística COSTEÑO", f"{ef_costeno:.2f} %")
            with col_ef2:
                st.metric("🐝 Efectividad Logística BEES", f"{ef_bees:.2f} %")
            
            st.markdown("---")
            
            # 🌟 NUEVA EXIGENCIA: FILTRO POR CANAL EN LA MATRIZ DE DEVOLUCIONES DE ANÁLISIS PROFUNDO
            st.markdown("#### 📋 Distribución y % de Participación en Devoluciones")
            canal_dev = st.radio("🔀 Filtrar Canal de Auditoría", ["Ambos", "COSTEÑO (GENERAL)", "BEES"], index=0, horizontal=True, key="dev_channel_sel")
            
            df_devs_reales = df_facturados_mes[
                df_facturados_mes['Motivo_Devolucion'].notna() & 
                (df_facturados_mes['Motivo_Devolucion'].astype(str) != "") &
                (df_facturados_mes['Motivo_Devolucion'].astype(str).str.upper() != "NAN")
            ]
            
            # Filtrado reactivo de devoluciones según el selector incorporado
            if canal_dev != "Ambos":
                df_devs_reales = df_devs_reales[df_devs_reales['Canal_UI'] == canal_dev]
            
            if not df_devs_reales.empty:
                pivot_dev = df_devs_reales.groupby('Motivo_Devolucion').agg(
                    Total_Pedidos=('ID_Pedido_Ingresado', 'nunique'),
                    Costeno_Pedidos=('ID_Pedido_Ingresado', lambda x: x[df_devs_reales['Tipo_Pedido'] == 'GENERAL'].nunique()),
                    Bees_Pedidos=('ID_Pedido_Ingresado', lambda x: x[df_devs_reales['Tipo_Pedido'] == 'PEDIDO BEES'].nunique()),
                    Dinero_Impactado=('TOTAL', 'sum')
                ).reset_index()
                
                gran_total_pedidos_dev = pivot_dev['Total_Pedidos'].sum()
                gran_total_dinero_dev = pivot_dev['Dinero_Impactado'].sum()
                
                # % de Participación dinámico calculado sobre el universo filtrado actual
                pivot_dev['% Participación'] = (pivot_dev['Total_Pedidos'] / gran_total_pedidos_dev * 100).map("{:.2f}%".format)
                pivot_dev = pivot_dev.sort_values(by='Total_Pedidos', ascending=False)
                
                st.metric(f"📉 Capital Retenido Afectado ({canal_dev.upper()})", f"S/. {gran_total_dinero_dev:,.2f}")
                st.markdown("💡 *Haz clic en cualquier fila para desplegar el desglose atómico de los pedidos.*")
                
                seleccion = st.dataframe(
                    pivot_dev,
                    width='stretch',
                    hide_index=True,
                    column_config={
                        "Motivo_Devolucion": "Motivo de Rechazo",
                        "Total_Pedidos": "Pedidos Únicos",
                        "Costeno_Pedidos": "Cant. Costeño",
                        "Bees_Pedidos": "Cant. BEES",
                        "Dinero_Impactado": st.column_config.NumberColumn("Dinero Retenido", format="S/. %,.2f"),
                        "% Participación": "% Part. Devoluciones"
                    },
                    on_select="rerun",
                    selection_mode="single-row"
                )
                
                if seleccion and seleccion['selection']['rows']:
                    idx_fila = seleccion['selection']['rows'][0]
                    motivo_click = pivot_dev.iloc[idx_fila]['Motivo_Devolucion']
                    
                    st.markdown(f"### 📋 Auditoría de Pedidos Afectados: `{motivo_click}`")
                    df_drill = df_devs_reales[df_devs_reales['Motivo_Devolucion'] == motivo_click][
                        ['Fecha_Facturacion_TXT', 'ID_Pedido_Ingresado', 'Codigo_Cliente', 'Tipo_Pedido', 'TOTAL']
                    ]
                    df_drill.columns = ['FECHA FACTURA', 'ID PEDIDO', 'CÓDIGO CLIENTE', 'CANAL', 'MONTO (S/.)']
                    st.dataframe(df_drill, width='stretch', hide_index=True)
            else:
                st.info(f"✨ Operación impecable: No existen motivos de devolución registrados para el canal {canal_dev.upper()} en este período.")

# --- INSPECCIÓN TÉCNICA GENERAL ---
st.markdown("---")
with st.expander("📋 Inspección Rápida de la Base de Datos Estructural Filtrada (Primeras 50 líneas)"):
    if not df_raw.empty:
        st.dataframe(df_region.head(50), width='stretch', hide_index=True)
