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
    """Autentica con Google Drive usando las credenciales seguras de Streamlit"""
    try:
        info_claves = st.secrets["gcp_service_account"]
        creds = service_account.Credentials.from_service_account_info(info_claves)
        return build('drive', 'v3', credentials=creds)
    except Exception as e:
        st.error(f"❌ Error de autenticación: Verifica la configuración de st.secrets. Detalles: {e}")
        return None

# --- 2. DESCARGA Y CACHÉ DE DATOS ---
@st.cache_data(ttl=3600)  # El caché se limpia automáticamente cada hora
def descargar_datos_maestros(file_id):
    """Descarga un Google Sheet nativo convirtiéndolo dinámicamente a Excel"""
    service = obtener_servicio_drive()
    if not service:
        return pd.DataFrame()
        
    try:
        # 🌟 EL CAMBIO CLAVE: Usamos export_media en lugar de get_media indicando el formato Excel
        request = service.files().export_media(
            fileId=file_id, 
            mimeType='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
        )
        fh = io.BytesIO()
        downloader = MediaIoBaseDownload(fh, request)
        done = False
        while done is False:
            status, done = downloader.next_chunk()
        fh.seek(0)
        
        # Leemos las columnas respetando los formatos de texto originales
        df = pd.read_excel(fh, dtype={
            'Fecha_Ingreso': str,
            'Fecha_Facturacion': str,
            'ID_Pedido_Ingresado': str,
            'ID_Factura_Final': str,
            'SKU_Material_Ingresado': str,
            'Codigo_Cliente': str
        })
        
        columnas_num = ['Valor_Neto_Ingresado', 'Impuestos_Ingresados', 'TOTAL', 
                        'Cantidad_Ingresada', 'Peso_Ingresado', 'Valor_Neto_Facturado', 
                        'Cantidad_Facturada', 'Peso_Facturado']
        for col in columnas_num:
            if col in df.columns:
                df[col] = pd.to_numeric(df[col], errors='coerce').fillna(0)
                
        return df
    except Exception as e:
        st.error(f"❌ Error al exportar e interpretar el Google Sheet de Drive: {e}")
        return pd.DataFrame()

# --- 3. CARGA DE DATOS INICIAL ---
# ID real del archivo 'REPORTE_CONCILIACION_BEES_FINAL.xlsx' en tu Drive
FILE_ID_EXCEL = "1-EoM0rYAmYY_tBkKwL5--746cdUa0tw2"  # Reemplazar si el ID cambia

st.title("📊 Dashboard de Conciliación Operativa - BEES")
st.markdown("Filtra la información en la barra lateral y descarga el reporte a la medida.")

# Botón manual en la barra lateral para forzar actualización de datos
if st.sidebar.button("🔄 Refrescar datos desde Drive"):
    st.cache_data.clear()
    st.sidebar.success("¡Memoria caché limpiada! Cargando última versión...")

df_raw = descargar_datos_maestros(FILE_ID_EXCEL)

if df_raw.empty:
    st.warning("No se pudieron cargar datos. Asegúrate de configurar las credenciales de la cuenta de servicio.")
else:
    # --- 4. CREACIÓN DE FILTROS EN LA BARRA LATERAL (SIDEBAR) ---
    st.sidebar.header("🎛️ Filtros de Búsqueda")
    
    # Filtro por Rango de Fechas (Garantizando orden cronológico interno)
    # Convertimos temporalmente a datetime solo para el widget de selección
    df_raw['_Fecha_Ingreso_DT'] = pd.to_datetime(df_raw['Fecha_Ingreso'], format='%d/%m/%Y', errors='coerce')
    fecha_min = df_raw['_Fecha_Ingreso_DT'].min() if pd.notna(df_raw['_Fecha_Ingreso_DT'].min()) else None
    fecha_max = df_raw['_Fecha_Ingreso_DT'].max() if pd.notna(df_raw['_Fecha_Ingreso_DT'].max()) else None
    
    if fecha_min and fecha_max:
        rango_fecha = st.sidebar.date_input("Rango de Fecha (Ingreso)", [fecha_min, fecha_max])
    else:
        rango_fecha = None

    # Filtros categóricos
    zonas_disponibles = sorted(df_raw['Zona_OfVta'].dropna().unique())
    zona_sel = st.sidebar.multiselect("Zona de Venta", opciones=zonas_disponibles)
    
    tipos_disponibles = sorted(df_raw['Tipo_Pedido'].dropna().unique())
    tipo_sel = st.sidebar.multiselect("Tipo de Pedido", opciones=tipos_disponibles)
    
    # Filtros por búsqueda de texto
    buscar_pedido = st.sidebar.text_input("Buscar ID Pedido (Exacto o Parcial)").strip()
    buscar_cliente = st.sidebar.text_input("Buscar Código Cliente").strip()

    # --- 5. APLICACIÓN LOGICA DE FILTROS ---
    df_filtrado = df_raw.copy()
    
    # Filtro por fecha
    if rango_fecha and len(rango_fecha) == 2:
        df_filtrado = df_filtrado[
            (df_filtrado['_Fecha_Ingreso_DT'].dt.date >= rango_fecha[0]) & 
            (df_filtrado['_Fecha_Ingreso_DT'].dt.date <= rango_fecha[1])
        ]
        
    # Filtros multiselect
    if zona_sel:
        df_filtrado = df_filtrado[df_filtrado['Zona_OfVta'].isin(zona_sel)]
    if tipo_sel:
        df_filtrado = df_filtrado[df_filtrado['Tipo_Pedido'].isin(tipo_sel)]
        
    # Filtros de texto libre
    if buscar_pedido:
        df_filtrado = df_filtrado[df_filtrado['ID_Pedido_Ingresado'].astype(str).str.contains(buscar_pedido)]
    if buscar_cliente:
        df_filtrado = df_filtrado[df_filtrado['Codigo_Cliente'].astype(str).str.contains(buscar_cliente)]
        
    # Limpiamos la columna temporal de fechas de procesamiento
    df_filtrado = df_filtrado.drop(columns=['_Fecha_Ingreso_DT'], errors='ignore')

    # --- 6. INDICADORES CLAVE (KPIs EXECUTIVOS) ---
    st.subheader("📈 Resumen Ejecutivo del Filtro")
    
    total_solicitado = df_filtrado['TOTAL'].sum()
    total_facturado = df_filtrado['Valor_Neto_Facturado'].sum()
    
    cant_ingresada = df_filtrado['Cantidad_Ingresada'].sum()
    cant_facturada = df_filtrado['Cantidad_Facturada'].sum()
    fill_rate = (cant_facturada / cant_ingresada * 100) if cant_ingresada > 0 else 0
    
    kpi1, kpi2, kpi3, kpi4 = st.columns(4)
    kpi1.metric("Total Ingresado (S/.)", f"S/. {total_solicitado:,.2f}")
    kpi2.metric("Total Facturado (S/.)", f"S/. {total_facturado:,.2f}")
    kpi3.metric("Registros Visibles", f"{len(df_filtrado):,}")
    kpi4.metric("Fill Rate Cantidades", f"{fill_rate:.2f}%")
    
    st.markdown("---")

    # --- 7. BOTÓN DE DESCARGA EXCLUSIVA DE DATOS FILTRADOS ---
    col_vacia, col_boton = st.columns([4, 1])
    
    # Procesamos la descarga a Excel solo sobre las líneas visibles (filtradas)
    output = io.BytesIO()
    with pd.ExcelWriter(output, engine='openpyxl') as writer:
        df_filtrado.to_excel(writer, index=False)
    bytes_excel = output.getvalue()
    
    col_boton.download_button(
        label="📥 Descargar Excel Filtrado",
        data=bytes_excel,
        file_name="CONCILIACION_FILTRADA_BEES.xlsx",
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        use_container_width=True
    )

    # --- 8. VISUALIZACIÓN DE LA TABLA MAESTRA ---
    st.subheader("📋 Matriz de Datos")
    st.dataframe(df_filtrado, use_container_width=True, hide_index=True)
