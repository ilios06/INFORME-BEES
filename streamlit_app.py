import streamlit as st
import pandas as pd
import numpy as np
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseDownload
from google.oauth2 import service_account
import io

# --- CONFIGURACIÓN DE LA PÁGINA WEB ---
st.set_page_config(
    page_title="Dashboard de Conciliación BEES",
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
        
        # Carga rápida mapeando tipos estrictos como texto puro
        df = pd.read_excel(fh, dtype={
            'Fecha_Ingreso': str,
            'Fecha_Facturacion': str,
            'ID_Pedido_Ingresado': str,
            'ID_Factura_Final': str,
            'SKU_Material_Ingresado': str,
            'Codigo_Cliente': str,
            'Motivo_Devolucion': str,
            'Zona_OfVta': str,
            'Tipo_Pedido': str
        })
        
        # ⚡ PROCESAMIENTO CRÍTICO DE FECHAS EN CACHÉ (Para ordenar cronológicamente)
        df['Fecha_Ingreso_DT'] = pd.to_datetime(df['Fecha_Ingreso'], format='%d/%m/%Y', errors='coerce')
        df['Fecha_Facturacion_DT'] = pd.to_datetime(df['Fecha_Facturacion'].astype(str).str.strip(), format='%d/%m/%Y', errors='coerce')
        
        meses_es = {1:'Enero', 2:'Febrero', 3:'Marzo', 4:'Abril', 5:'Mayo', 6:'Junio',
                    7:'Julio', 8:'Agosto', 9:'Septiembre', 10:'Octubre', 11:'Noviembre', 12:'Diciembre'}
        
        df['Mes_Ingreso'] = df['Fecha_Ingreso_DT'].dt.month.map(meses_es).fillna("Sin Mes")
        
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

st.title("📊 Centro de Control y Conciliación - BEES & GENERAL")

if st.sidebar.button("🔄 Forzar Refresco de Base (Borrar Caché)"):
    st.cache_data.clear()
    st.sidebar.success("¡Base sincronizada de nuevo!")

df_raw = descargar_datos_maestros(FILE_ID_EXCEL)

if not df_raw.empty:
    # --- 4. FILTROS DINÁMICOS LATERALES ---
    st.sidebar.header("🎛️ Segmentadores de Datos")
    
    meses_disponibles = ['Todos'] + list(df_raw['Mes_Ingreso'].unique())
    mes_sel = st.sidebar.selectbox("Fecha_Ingreso (mes)", options=meses_disponibles, index=0)
    
    zonas_disponibles = sorted(df_raw['Zona_OfVta'].dropna().unique())
    zona_sel = st.sidebar.multiselect("Zona_OfVta", options=zonas_disponibles)
    
    motivos_disponibles = sorted(df_raw['Motivo_Devolucion'].dropna().unique())
    motivo_sel = st.sidebar.multiselect("Motivo_Devolucion", options=motivos_disponibles)

    # --- 5. FILTRADO EN MEMORIA ---
    df_filtrado = df_raw.copy()
    
    if mes_sel != 'Todos':
        df_filtrado = df_filtrado[df_filtrado['Mes_Ingreso'] == mes_sel]
    if zona_sel:
        df_filtrado = df_filtrado[df_filtrado['Zona_OfVta'].isin(zona_sel)]
    if motivo_sel:
        df_filtrado = df_filtrado[df_filtrado['Motivo_Devolucion'].isin(motivo_sel)]

    # --- 6. PESTAÑAS DE TRABAJO ---
    tab_resumen, tab_detalles = st.tabs(["📊 Vista Tablas Dinámicas", "📋 Base de Datos Estructural"])

    with tab_resumen:
        st.markdown(f"**Filtros Activos:** Mes: `{mes_sel}` | Zonas: `{len(zona_sel) if zona_sel else 'Todas'}` | Devoluciones: `{len(motivo_sel) if motivo_sel else 'Todas'}`")
        
        col_general, col_bees = st.columns(2)
        
        # --- COLUMNA 1: PEDIDOS ENTREGADOS GENERAL ---
        with col_general:
            st.markdown("<h3 style='text-align: center; color: #FFF; background-color: #4A3B5C; padding: 5px; border-radius: 5px;'>PEDIDOS ENTREGADOS GENERAL</h3>", unsafe_allow_html=True)
            df_gen = df_filtrado[df_filtrado['Tipo_Pedido'] == 'GENERAL']
            
            if not df_gen.empty:
                # 🌟 SOLUCIÓN: Agrupamos incluyendo la fecha DT interna para obligar el orden cronológico estricto
                pivot_gen = df_gen.groupby(['Fecha_Facturacion_DT', 'Fecha_Facturacion']).agg(
                    CANTIDAD_DE_PEDIDOS=('ID_Pedido_Ingresado', 'nunique')
                ).reset_index().sort_values('Fecha_Facturacion_DT')
                
                pivot_gen = pivot_gen[['Fecha_Facturacion', 'CANTIDAD_DE_PEDIDOS']]
                pivot_gen.columns = ['FECHA DE FACTURACIÓN', 'CANTIDAD DE PEDIDOS']
                
                # 🌟 NUEVO ESTÁNDAR: Reemplazado 'use_container_width' por 'width' para limpiar logs
                st.dataframe(pivot_gen, width='stretch', hide_index=True)
                st.markdown(f"**Total general:** `{df_gen['ID_Pedido_Ingresado'].nunique():,}` Pedidos Únicos")
            else:
                st.info("No hay datos para el canal GENERAL.")

        # --- COLUMNA 2: PEDIDOS ENTREGADOS BEES ---
        with col_bees:
            st.markdown("<h3 style='text-align: center; color: #FFF; background-color: #4A3B5C; padding: 5px; border-radius: 5px;'>PEDIDOS ENTREGADOS BEES</h3>", unsafe_allow_html=True)
            df_bees = df_filtrado[df_filtrado['Tipo_Pedido'] == 'PEDIDO BEES']
            
            if not df_bees.empty:
                # 🌟 SOLUCIÓN: Agrupamos incluyendo la fecha DT interna para obligar el orden cronológico estricto
                pivot_bees = df_bees.groupby(['Fecha_Facturacion_DT', 'Fecha_Facturacion']).agg(
                    CANTIDAD_DE_PEDIDOS=('ID_Pedido_Ingresado', 'nunique')
                ).reset_index().sort_values('Fecha_Facturacion_DT')
                
                pivot_bees = pivot_bees[['Fecha_Facturacion', 'CANTIDAD_DE_PEDIDOS']]
                pivot_bees.columns = ['FECHA DE FACTURACIÓN', 'CANTIDAD DE PEDIDOS']
                
                # 🌟 NUEVO ESTÁNDAR: Reemplazado 'use_container_width' por 'width' para limpiar logs
                st.dataframe(pivot_bees, width='stretch', hide_index=True)
                st.markdown(f"**Total general:** `{df_bees['ID_Pedido_Ingresado'].nunique():,}` Pedidos Únicos")
            else:
                st.info("No hay datos para el canal BEES.")

    with tab_detalles:
        st.subheader("Base de Conciliación Completa (Filtrada)")
        
        # Descarga limpia sin columnas temporales de ordenamiento
        columnas_descarte = ['Fecha_Ingreso_DT', 'Fecha_Facturacion_DT', 'Mes_Ingreso']
        df_descarga = df_filtrado.drop(columns=columnas_descarte, errors='ignore')
        
        output = io.BytesIO()
        with pd.ExcelWriter(output, engine='openpyxl') as writer:
            df_descarga.to_excel(writer, index=False)
        bytes_excel = output.getvalue()
        
        st.download_button(
            label="📥 Descargar Base Filtrada a Excel",
            data=bytes_excel,
            file_name="CONCILIACION_FILTRADA_EXCEL.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        )
        
        st.dataframe(df_descarga, width='stretch', hide_index=True)
