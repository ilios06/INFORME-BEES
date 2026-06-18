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

# --- INICIALIZACIÓN DE ESTADOS INTERACTIVOS ---
if 'motivo_seleccionado' not in st.session_state:
    st.session_state.motivo_seleccionado = None

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

# --- 2. DESCARGA Y OPTIMIZACIÓN DE CACHÉ DE DATOS (TU MATRIZ BASE) ---
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
        
        # Carga rápida mapeando tipos estrictos como texto puro (Tu configuración original)
        df = pd.read_excel(fh, dtype={
            'ID_Pedido_Ingresado': str,
            'ID_Factura_Final': str,
            'SKU_Material_Ingresado': str,
            'Codigo_Cliente': str,
            'Motivo_Devolucion': str,
            'Zona_OfVta': str,
            'Tipo_Pedido': str
        })
        
        # ⚡ PROCESAMIENTO CRÍTICO DE FECHAS EN CACHÉ
        for col in ['Fecha_Ingreso', 'Fecha_Facturacion']:
            if col in df.columns:
                if pd.api.types.is_datetime64_any_dtype(df[col]):
                    df[f'{col}_DT'] = df[col]
                else:
                    df[f'{col}_DT'] = pd.to_datetime(df[col].astype(str).str.strip(), format='%d/%m/%Y', errors='coerce')
                
                # Renderizado exacto de texto original sin horas
                df[f'{col}_TXT'] = df[f'{col}_DT'].dt.strftime('%d/%m/%Y').fillna(df[col].astype(str).str.split(' ').str[0])
            else:
                df[f'{col}_DT'] = pd.NaT
                df[f'{col}_TXT'] = "Sin Fecha"
        
        meses_es = {1:'Enero', 2:'Febrero', 3:'Marzo', 4:'Abril', 5:'Mayo', 6:'Junio',
                    7:'Julio', 8:'Agosto', 9:'Septiembre', 100:'Octubre', 11:'Noviembre', 12:'Diciembre'}
        
        # 🌟 EXCEPCIÓN DE FECHAS: Se estructuran ambos meses de forma independiente
        df['Mes_Ingreso'] = df['Fecha_Ingreso_DT'].dt.month.map(meses_es).fillna("Sin Mes")
        df['Mes_Facturacion'] = df['Fecha_Facturacion_DT'].dt.month.map(meses_es).fillna("Sin Mes")
        
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
        
        # Selector de Mes basado en la Fecha de Facturación (Regla General)
        meses_validos = sorted([m for m in df_raw['Mes_Facturacion'].unique() if m != "Sin Mes"])
        if not meses_validos:
            meses_validos = sorted([m for m in df_raw['Mes_Ingreso'].unique() if m != "Sin Mes"])
        mes_sel = st.selectbox("📅 Seleccionar Período Mensual", options=meses_validos, index=0)
        
        # Selector de Región / Zona (Lima vs Arequipa) con tolerancia de texto
        opcion_region = st.radio("📍 Filtrar Región Geográfica", ["Lima", "Arequipa", "Ver Todo"], index=2)
        
        # Selector de Vista / Análisis Profundo
        zona_analisis = st.toggle("🔍 Activar Zona de Análisis Profundo", value=False)
        
        if st.button("🔄 Sincronizar Base (Borrar Caché)"):
            st.cache_data.clear()
            st.success("¡Caché liberada!")
            st.rerun()
        st.markdown("</div>", unsafe_allow_html=True)

    # --- 5. CORE ENGINE: FILTRADO SEGURO POR REGION ---
    if opcion_region == "Lima":
        df_region = df_raw[df_raw['Zona_OfVta'].astype(str).str.upper().str.contains('LIMA', na=False)]
    elif opcion_region == "Arequipa":
        df_region = df_raw[df_raw['Zona_OfVta'].astype(str).str.upper().str.contains('AREQUIPA', na=False)]
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
        (df_facturados_mes['ID_Factura_Final'].astype(str).str.strip() != "0") & 
        (df_facturados_mes['ID_Factura_Final'].astype(str).str.strip() != "")
    ]
    
    # 3. Entregados: Facturas válidas donde el Motivo de Devolución esté limpio
    condicion_entregado = (df_facturas_validas['Motivo_Devolucion'].isna()) | (df_facturas_validas['Motivo_Devolucion'].astype(str).str.strip() == "") | (df_facturas_validas['Motivo_Devolucion'].astype(str).str.upper() == "NAN")
    df_entregados_mes = df_facturas_validas[condicion_entregado]

    # --- 6. RENDERIZADO EN LA COLUMNA DE VISUALIZACIÓN (IZQUIERDA) ---
    with col_visualizacion:
        if not zona_analisis:
            st.title(f"📊 Dashboard Operativo — {mes_sel.upper()} ({opcion_region.upper()})")
            
            # --- 6.1 TRES GRÁFICOS PEQUEÑOS DE PARTICIPACIÓN (PLOTLY EXPRESS) ---
            # Agrupación por canal usando tus literales exactos: 'GENERAL' y 'PEDIDO BEES'
            df_chart_base = df_facturados_mes.copy()
            df_chart_base['Canal_Visual'] = df_chart_base['Tipo_Pedido'].map({'GENERAL': 'COSTEÑO (GENERAL)', 'PEDIDO BEES': 'BEES'}).fillna(df_chart_base['Tipo_Pedido'])
            
            summary_metrics = df_chart_base.groupby('Canal_Visual').agg(
                Pedidos=('ID_Pedido_Ingresado', 'nunique'),
                Peso=('Peso_Ingresado', 'sum'),
                Dinero=('TOTAL', 'sum')
            ).reset_index()
            
            if summary_metrics.empty or summary_metrics['Pedidos'].sum() == 0:
                st.info(f"📋 No se registran movimientos facturados en {mes_sel} para la región elegida.")
            else:
                g1, g2, g3 = st.columns(3)
                colores_corporativos = ['#4A3B5C', '#17A2B8', '#FFC107']
                
                with g1:
                    fig1 = px.pie(summary_metrics, values='Pedidos', names='Canal_Visual', hole=0.4,
                                  title="Part. % Pedidos Únicos", color_discrete_sequence=colores_corporativos)
                    fig1.update_layout(showlegend=False, height=200, margin=dict(t=30, b=0, l=0, r=0))
                    st.plotly_chart(fig1, use_container_width=True)
                with g2:
                    fig2 = px.pie(summary_metrics, values='Peso', names='Canal_Visual', hole=0.4,
                                  title="Part. % Peso Ingresado (Kg)", color_discrete_sequence=colores_corporativos)
                    fig2.update_layout(showlegend=False, height=200, margin=dict(t=30, b=0, l=0, r=0))
                    st.plotly_chart(fig2, use_container_width=True)
                with g3:
                    fig3 = px.pie(summary_metrics, values='Dinero', names='Canal_Visual', hole=0.4,
                                  title="Part. % Capital TOTAL (S/.)", color_discrete_sequence=colores_corporativos)
                    fig3.update_layout(showlegend=False, height=200, margin=dict(t=30, b=0, l=0, r=0))
                    st.plotly_chart(fig3, use_container_width=True)
                
                # Resumen numérico debajo de los gráficos circulares
                st.markdown("#### 🔢 Desglose Resumido de Canales")
                rm1, rm2, rm3 = st.columns(3)
                for _, row in summary_metrics.iterrows():
                    canal_name = row['Canal_Visual']
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
            
            kp_c_pc, kp_c_tk = calcular_kpis_structurales(df_costeno)
            kp_b_pc, kp_b_tk = calcular_kpis_structurales(df_bees)
            
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
            
            # --- 6.3 GRÁFICO DE EMBUDO LOGÍSTICO (CONTEOS ÚNICOS) ---
            st.markdown("### 🌪️ Embudo Logístico de Pedidos Únicos")
            c_ingresados = df_ingresados_mes['ID_Pedido_Ingresado'].nunique()
            c_facturados = df_facturas_validas['ID_Pedido_Ingresado'].nunique()
            c_entregados = df_entregados_mes['ID_Pedido_Ingresado'].nunique()
            
            fig_funnel = go.Figure(go.Funnel(
                y=["1. Pedidos Ingresados (F. Ingreso)", "2. Pedidos Facturados (F. Facturación)", "3. Pedidos Entregados (Sin Dev.)"],
                x=[c_ingresados, c_facturados, c_entregados],
                textinfo="value+percent initial",
                marker={"color": ["#3B2F4C", "#4A3B5C", "#17A2B8"]}
            ))
            fig_funnel.update_layout(margin=dict(l=10, r=10, t=10, b=10), height=220)
            st.plotly_chart(fig_funnel, use_container_width=True)

        else:
            # --- ZONA DE ANÁLISIS DE METRICAS REBUSCADAS (DEVOLUCIONES Y EFECTIVIDAD) ---
            st.title(f"🔍 Análisis de Efectividad y Devoluciones — {mes_sel}")
            
            # Cálculo de efectividad de entrega por parte de negocio
            f_c = df_facturas_validas[df_facturas_validas['Tipo_Pedido'] == 'GENERAL']['ID_Pedido_Ingresado'].nunique()
            e_c = df_entregados_mes[df_entregados_mes['Tipo_Pedido'] == 'GENERAL']['ID_Pedido_Ingresado'].nunique()
            
            f_b = df_facturas_validas[df_facturas_validas['Tipo_Pedido'] == 'PEDIDO BEES']['ID_Pedido_Ingresado'].nunique()
            e_b = df_entregados_mes[df_entregados_mes['Tipo_Pedido'] == 'PEDIDO BEES']['ID_Pedido_Ingresado'].nunique()
            
            ef_costeno = (e_c / f_c * 100) if f_c > 0 else 100
            ef_bees = (e_b / f_b * 100) if f_b > 0 else 100
            
            col_ef1, col_ef2 = st.columns(2)
            with col_ef1:
                st.metric("📉 Efectividad Logística COSTEÑO", f"{ef_costeno:.2f} %", 
                          delta="Mayor Volumen" if ef_costeno >= ef_bees else None)
            with col_ef2:
                st.metric("🐝 Efectividad Logística BEES", f"{ef_bees:.2f} %", 
                          delta="Mayor Volumen" if ef_bees > ef_costeno else None)
            
            # Conclusión explícita de efectividad
            if ef_costeno != ef_bees:
                ganador = "COSTEÑO (GENERAL)" if ef_costeno > ef_bees else "BEES"
                st.success(f"🏆 El canal con **mayor efectividad de entrega** en {mes_sel} es **{ganador}**.")
            
            st.markdown("---")
            st.markdown("#### 📋 Distribución y Participación de Motivos de Devolución")
            
            # Extraer registros con devoluciones reales en el mes de facturación
            df_devs_reales = df_facturados_mes[
                df_facturados_mes['Motivo_Devolucion'].notna() & 
                (df_facturados_mes['Motivo_Devolucion'].astype(str).str.strip() != "") &
                (df_facturados_mes['Motivo_Devolucion'].astype(str).str.upper() != "NAN")
            ]
            
            if not df_devs_reales.empty:
                # Pivote dinámico de motivos calculando cantidades por canal comercial
                pivot_dev = df_devs_reales.groupby('Motivo_Devolucion').agg(
                    Total_Pedidos=('ID_Pedido_Ingresado', 'nunique'),
                    Costeno_Pedidos=('ID_Pedido_Ingresado', lambda x: x[df_devs_reales['Tipo_Pedido'] == 'GENERAL'].nunique()),
                    Bees_Pedidos=('ID_Pedido_Ingresado', lambda x: x[df_devs_reales['Tipo_Pedido'] == 'PEDIDO BEES'].nunique()),
                    Dinero_Impactado=('TOTAL', 'sum')
                ).reset_index()
                
                gran_total_pedidos_dev = pivot_dev['Total_Pedidos'].sum()
                gran_total_dinero_dev = pivot_dev['Dinero_Impactado'].sum()
                
                pivot_dev['% Participación'] = (pivot_dev['Total_Pedidos'] / gran_total_pedidos_dev * 100).map("{:.2f}%".format)
                pivot_dev = pivot_dev.sort_values(by='Total_Pedidos', ascending=False)
                
                st.metric("📉 Capital Total Retenido por Devoluciones", f"S/. {gran_total_dinero_dev:,.2f}")
                
                # Tabla de control interactiva (Push-up con selección nativa)
                st.markdown("💡 *Haz clic en cualquier fila para desplegar inmediatamente la pestaña flotante con el desglose de pedidos.*")
                
                seleccion = st.dataframe(
                    pivot_dev,
                    width='stretch',
                    hide_index=True,
                    column_config={
                        "Motivo_Devolucion": "Motivo de Rechazo",
                        "Total_Pedidos": "Pedidos Únicos",
                        "Costeno_Pedidos": "Cant. Costeño",
                        "Bees_Pedidos": "Cant. BEES",
                        "Dinero_Impactado": st.column_config.NumberColumn("Dinero Retenido", format="S/. %,.2f")
                    },
                    on_select="rerun",
                    selection_mode="single_row"
                )
                
                # --- INTERACTIVIDAD CON SESSION STATE (DEEP-DIVE EN NUEVO CONTENEDOR) ---
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
                st.info("✨ Operación perfecta: No existen motivos de devolución registrados para este segmento.")

# --- INSPECCIÓN TÉCNICA GENERAL ---
st.markdown("---")
with st.expander("📋 Inspección Rápida de la Base de Datos Estructural Filtrada (Primeras 50 líneas)"):
    st.dataframe(df_region.head(50), width='stretch', hide_index=True)
