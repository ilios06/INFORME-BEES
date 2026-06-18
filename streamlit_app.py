import streamlit as st
import pandas as pd
import numpy as np
import plotly.express as px
import plotly.graph_objects as go
import io
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseDownload
from google.oauth2 import service_account

# --- CONFIGURACIÓN DE LA PÁGINA WEB ---
st.set_page_config(
    page_title="Command Center Analítico - BEES & COSTEÑO",
    page_icon="🦅",
    layout="wide"
)

# --- INICIALIZACIÓN DE ESTADOS INTERACTIVOS (SESSION STATE) ---
if 'vista_profunda_pedidos' not in st.session_state:
    st.session_state.vista_profunda_pedidos = None
if 'modal_abierto' not in st.session_state:
    st.session_state.modal_abierto = False

# --- CONFIGURACIÓN DE ESTILOS CSS CUSTOM ---
st.markdown("""
    <style>
    .metric-card {
        background-color: #1E1E2E;
        padding: 15px;
        border-radius: 10px;
        border-left: 5px solid #4A3B5C;
        margin-bottom: 10px;
    }
    .metric-title {
        color: #A3A3C2;
        font-size: 13px;
        font-weight: bold;
        text-transform: uppercase;
    }
    .metric-value {
        color: #FFFFFF;
        font-size: 22px;
        font-weight: bold;
    }
    .metric-sub {
        color: #00FFCC;
        font-size: 12px;
    }
    </style>
""", unsafe_allow_html=True)

# --- 1. CAPA DE INGESTIÓN DE DATOS Y GENERADOR SINTÉTICO (FALLBACK) ---
def generar_datos_simulados():
    """Genera un dataset de alta fidelidad comercial si falla la conexión a Drive"""
    np.random.seed(42)
    rows = 6000
    
    fechas_ingreso = pd.date_range(start="2026-01-01", end="2026-06-30", periods=rows)
    df_mock = pd.DataFrame({
        'ID_Pedido_Ingresado': [f"PED-{100000 + x}" for x in np.random.randint(1, 2200, size=rows)],
        'ID_Factura_Final': [f"FAC-{200000 + x}" if np.random.rand() > 0.18 else "0" for x in np.random.randint(1, rows, size=rows)],
        'SKU_Material_Ingresado': [f"SKU-{np.random.randint(100, 150)}" for _ in range(rows)],
        'Codigo_Cliente': [f"CLI-{np.random.randint(1, 450)}" for _ in range(rows)],
        'Motivo_Devolucion': [np.random.choice(["Rechazo por Calidad", "Precio Incorrecto", "Pedido Duplicado", "Cliente Ausente", ""], p=[0.05, 0.04, 0.03, 0.03, 0.85]) for _ in range(rows)],
        'Zona_OfVta': [np.random.choice(["LIMA NORTE", "LIMA SUR", "AREQUIPA CENTRO", "AREQUIPA SUR"], p=[0.4, 0.3, 0.2, 0.1]) for _ in range(rows)],
        'Tipo_Pedido': [np.random.choice(["GENERAL", "PEDIDO BEES"], p=[0.45, 0.55]) for _ in range(rows)],
        'Peso_Ingresado': np.random.uniform(10, 350, size=rows),
        'TOTAL': np.random.uniform(100, 4500, size=rows)
    })
    
    # Simular desfase de fechas de facturación
    df_mock['Fecha_Ingreso_DT'] = fechas_ingreso
    df_mock['Fecha_Facturacion_DT'] = df_mock['Fecha_Ingreso_DT'] + pd.to_timedelta(np.random.randint(0, 4, size=rows), unit='D')
    
    # Forzar filas no facturadas limpias
    df_mock.loc[df_mock['ID_Factura_Final'] == "0", 'Fecha_Facturacion_DT'] = pd.NaT
    df_mock.loc[df_mock['ID_Factura_Final'] == "0", 'TOTAL'] = 0
    
    # Formatear como textos para simular la estructura de Sheets original
    df_mock['Fecha_Ingreso'] = df_mock['Fecha_Ingreso_DT'].dt.strftime('%d/%m/%Y')
    df_mock['Fecha_Facturacion'] = df_mock['Fecha_Facturacion_DT'].dt.strftime('%d/%m/%Y').fillna("")
    
    return df_mock

@st.cache_data(ttl=3600)
def descargar_y_estructurar_base(file_id):
    df = pd.DataFrame()
    try:
        if "gcp_service_account" in st.secrets:
            info_claves = st.secrets["gcp_service_account"]
            creds = service_account.Credentials.from_service_account_info(info_claves)
            service = build('drive', 'v3', credentials=creds)
            request = service.files().get_media(fileId=file_id)
            fh = io.BytesIO()
            downloader = MediaIoBaseDownload(fh, request)
            done = False
            while not done:
                status, done = downloader.next_chunk()
            fh.seek(0)
            df = pd.read_excel(fh, dtype=str)
        else:
            df = generar_datos_simulados()
    except Exception:
        df = generar_datos_simulados()

    # --- PARSING ESTRUCTURAL DE FECHAS (PROTECCIÓN DE MÁSCARAS) ---
    for col in ['Fecha_Ingreso', 'Fecha_Facturacion']:
        if col in df.columns:
            df[f'{col}_DT'] = pd.to_datetime(df[col].astype(str).str.strip(), format='%d/%m/%Y', errors='coerce')
            # Máscara visual estricta sin marcas de tiempo
            df[f'{col}_TXT'] = df[f'{col}_DT'].dt.strftime('%d/%m/%Y').fillna("Sin Registro")
    
    meses_es = {1:'Enero', 2:'Febrero', 3:'Marzo', 4:'Abril', 5:'Mayo', 6:'Junio',
                7:'Julio', 8:'Agosto', 9:'Septiembre', 10:'Octubre', 11:'Noviembre', 12:'Diciembre'}
    
    # Segmentación mensual basada en la regla de negocio cruzada
    df['Mes_Ingreso'] = df['Fecha_Ingreso_DT'].dt.month.map(meses_es).fillna("Sin Mes")
    df['Mes_Facturacion'] = df['Fecha_Facturacion_DT'].dt.month.map(meses_es).fillna("Sin Mes")
    
    # Formateo numérico financiero explicito
    for col in ['TOTAL', 'Peso_Ingresado']:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors='coerce').fillna(0)
            
    return df

# --- 2. INGESTACIÓN GENERAL ---
FILE_ID_EXCEL = "1-EoM0rYAmYY_tBkKwL5--746cdUa0tw2"
df_master = descargar_y_estructurar_base(FILE_ID_EXCEL)

# --- 3. MAQUETACIÓN DE FILTROS FLOTANTES (COLUMNA DERECHA PRINCIPAL) ---
st.title("🦅 Operaciones Maestras - BEES & COSTEÑO")

# Columnas de control superior
col_visual, col_blank, col_filtros = st.columns([6, 1, 3])

with col_filtros:
    st.markdown("### 🎛️ Panel de Control")
    
    # Regla: Elección de Zona Macro
    zona_macro = st.radio("📍 Región Geográfica", ["Lima", "Arequipa", "Ambos"], index=2)
    
    # Selector de Meses disponibles (Basado en Facturación)
    meses_disponibles = [m for m in df_master['Mes_Facturacion'].unique() if m != "Sin Mes"]
    mes_seleccionado = st.selectbox("📅 Período de Análisis", options=sorted(meses_disponibles))
    
    # Filtro Tipo de Canal para exploración profunda
    canal_seleccionado = st.multiselect("🔀 Canal de Negocio", options=["COSTEÑO (GENERAL)", "BEES"], default=["COSTEÑO (GENERAL)", "BEES"])
    
    # Modo de la pantalla
    modo_pantalla = st.toggle("🔍 Activar Zona de Análisis Profundo", value=False)

# --- 4. ENGINE DE FILTRADO DINÁMICO POR REGLA DE NEGOCIO ---
# Filtrar Región Geográfica
if zona_macro == "Lima":
    df_zona = df_master[df_master['Zona_OfVta'].astype(str).str.upper().str.contains('LIMA', na=False)]
elif zona_macro == "Arequipa":
    df_zona = df_master[df_master['Zona_OfVta'].astype(str).str.upper().str.contains('AREQUIPA', na=False)]
else:
    df_zona = df_master.copy()

# Normalización de canales para el filtrado UI
df_zona['Canal_UI'] = df_zona['Tipo_Pedido'].map({'GENERAL': 'COSTEÑO (GENERAL)', 'PEDIDO BEES': 'BEES'})
if canal_seleccionado:
    df_zona = df_zona[df_zona['Canal_UI'].isin(canal_seleccionado)]

# --- REGLA CRÍTICA DE TIEMPOS: Extracción de datasets descalzados ---
# Dataset Ingresados: Se rige por Fecha_Ingreso
df_ingresados_mes = df_zona[df_zona['Mes_Ingreso'] == mes_seleccionado]

# Datasets Facturados y Entregados: Se rigen por Fecha_Facturacion
df_facturados_mes = df_zona[df_zona['Mes_Facturacion'] == mes_seleccionado]
df_facturados_validos = df_facturados_mes[(df_facturados_mes['ID_Factura_Final'].notna()) & (df_facturados_mes['ID_Factura_Final'].astype(str).str.strip() != "0") & (df_facturados_mes['ID_Factura_Final'].astype(str).str.strip() != "")]

# Entregados: Facturados cuya columna Motivo_Devolucion esté limpia
condicion_entregado = (df_facturados_validos['Motivo_Devolucion'].na_rep == "") | (df_facturados_validos['Motivo_Devolucion'].isna()) | (df_facturados_validos['Motivo_Devolucion'].astype(str).str.strip() == "")
df_entregados_mes = df_facturados_validos[condicion_entregado]

with col_visual:
    if not modo_pantalla:
        st.markdown(f"## 📊 Panel Ejecutivo del Mes: `{mes_seleccionado}`")
        
        # --- 5. VISUALIZACIÓN EN PARTICIPACIÓN DE MERCADO (DONUT CHARTS) ---
        # Preparación de datos para los gráficos de participación (Basados en Facturación del Mes)
        metrics_by_channel = df_facturados_mes.groupby('Canal_UI').agg(
            Pedidos=('ID_Pedido_Ingresado', 'nunique'),
            Peso=('Peso_Ingresado', 'sum'),
            Dinero=('TOTAL', 'sum')
        ).reset_index()
        
        c1, c2, c3 = st.columns(3)
        
        with c1:
            fig_ped = px.pie(metrics_by_channel, values='Pedidos', names='Canal_UI', hole=0.5,
                             title="Part. % Pedidos Únicos", color_discrete_sequence=['#4A3B5C', '#17A2B8'])
            fig_ped.update_layout(showlegend=False, height=220, margin=dict(t=30, b=10, l=10, r=10))
            st.plotly_chart(fig_ped, use_container_width=True)
            
        with c2:
            fig_pso = px.pie(metrics_by_channel, values='Peso', names='Canal_UI', hole=0.5,
                             title="Part. % Volumen Peso (Kg)", color_discrete_sequence=['#4A3B5C', '#17A2B8'])
            fig_pso.update_layout(showlegend=False, height=220, margin=dict(t=30, b=10, l=10, r=10))
            st.plotly_chart(fig_pso, use_container_width=True)
            
        with c3:
            fig_mon = px.pie(metrics_by_channel, values='Dinero', names='Canal_UI', hole=0.5,
                             title="Part. % Capital Total (S/.)", color_discrete_sequence=['#4A3B5C', '#17A2B8'])
            fig_mon.update_layout(showlegend=False, height=220, margin=dict(t=30, b=10, l=10, r=10))
            st.plotly_chart(fig_mon, use_container_width=True)

        # --- RESUMEN NUMÉRICO DIRECTO DEBAJO DE GRÁFICOS ---
        st.markdown("#### 🔢 Desglose Estructural Directo")
        n1, n2, n3 = st.columns(3)
        for idx, row in metrics_by_channel.iterrows():
            canal = row['Canal_UI']
            color = "#4A3B5C" if canal == "COSTEÑO (GENERAL)" else "#17A2B8"
            n1.markdown(f"<b style='color:{color};'>{canal}:</b> {row['Pedidos']:,} Pedidos", unsafe_allow_html=True)
            n2.markdown(f"<b style='color:{color};'>{canal}:</b> {row['Peso']:,.1f} Kg", unsafe_allow_html=True)
            n3.markdown(f"<b style='color:{color};'>{canal}:</b> S/. {row['Dinero']:,.2f}", unsafe_allow_html=True)

        st.markdown("---")
        
        # --- 6. CÁLCULO DE FÓRMULAS MATEMÁTICAS AVANZADAS COMERCIALES ---
        st.markdown("### 🧮 Indicadores de Tracción Comercial")
        
        def calcular_kpis_canal(df_origen_fact):
            pedidos_unicos = df_origen_fact['ID_Pedido_Ingresado'].nunique()
            clientes_unicos = df_origen_fact['Codigo_Cliente'].nunique()
            dinero_total = df_origen_fact['TOTAL'].sum()
            
            pedidos_por_cliente = pedidos_unicos / clientes_unicos if clientes_unicos > 0 else 0
            ticket_promedio = dinero_total / pedidos_unicos if pedidos_unicos > 0 else 0
            return pedidos_por_cliente, ticket_promedio

        df_costeno_fact = df_facturados_mes[df_facturados_mes['Canal_UI'] == 'COSTEÑO (GENERAL)']
        df_bees_fact = df_facturados_mes[df_facturados_mes['Canal_UI'] == 'BEES']
        
        cc_ped_cli, cc_tk = calcular_kpis_canal(df_costeno_fact)
        be_ped_cli, be_tk = calcular_kpis_canal(df_bees_fact)
        
        k1, k2 = st.columns(2)
        with k1:
            st.markdown(f"""
            <div class='metric-card'>
                <div class='metric-title'>⚙️ Canal COSTEÑO (GENERAL)</div>
                <div class='metric-value'>N° Pedidos/Cliente: {cc_ped_cli:,.2f}</div>
                <div class='metric-value' style='color:#17A2B8;'>Ticket Promedio: S/. {cc_tk:,.2f}</div>
            </div>
            """, unsafe_allow_html=True)
            
        with k2:
            st.markdown(f"""
            <div class='metric-card'>
                <div class='metric-title'>🐝 Canal BEES</div>
                <div class='metric-value'>N° Pedidos/Cliente: {be_ped_cli:,.2f}</div>
                <div class='metric-value' style='color:#17A2B8;'>Ticket Promedio: S/. {be_tk:,.2f}</div>
            </div>
            """, unsafe_allow_html=True)

        st.markdown("---")

        # --- 7. EMBUDO DE CONVERSIÓN DE OPERACIONES LOGÍSTICAS ---
        st.markdown("### 🌪️ Embudo Logístico de Pedidos Únicos")
        
        val_ingresados = df_ingresados_mes['ID_Pedido_Ingresado'].nunique()
        val_facturados = df_facturados_validos['ID_Pedido_Ingresado'].nunique()
        val_entregados = df_entregados_mes['ID_Pedido_Ingresado'].nunique()
        
        fig_funnel = go.Figure(go.Funnel(
            y = ["1. Pedidos Ingresados", "2. Pedidos Facturados", "3. Pedidos Entregados Nativos"],
            x = [val_ingresados, val_facturados, val_entregados],
            textinfo = "value+percent initial",
            marker = {"color": ["#3B2F4C", "#4A3B5C", "#17A2B8"]}
        ))
        fig_funnel.update_layout(margin=dict(l=20, r=20, t=20, b=20), height=260)
        st.plotly_chart(fig_funnel, use_container_width=True)
        
        st.caption("ℹ️ *Nota de Fondo: El conteo de Ingresados analiza la Fecha_Ingreso, mientras que Facturados y Entregados calculan sobre la Fecha_Facturacion según regla matricial.*")

    else:
        # --- ZONA DE ANÁLISIS PROFUNDO (PULSO DE DEVOLUCIONES Y EFECTIVIDAD) ---
        st.markdown(f"## 🔍 Análisis de Efectividad y Motor de Devoluciones: `{mes_seleccionado}`")
        
        # Motor de cálculo de Efectividad Operativa por Canal
        # Efectividad = (Entregados / Facturados) * 100
        fact_c = df_facturados_validos[df_facturados_validos['Canal_UI'] == 'COSTEÑO (GENERAL)']['ID_Pedido_Ingresado'].nunique()
        ent_c = df_entregados_mes[df_entregados_mes['Canal_UI'] == 'COSTEÑO (GENERAL)']['ID_Pedido_Ingresado'].nunique()
        
        fact_b = df_facturados_validos[df_facturados_validos['Canal_UI'] == 'BEES']['ID_Pedido_Ingresado'].nunique()
        ent_b = df_entregados_mes[df_entregados_mes['Canal_UI'] == 'BEES']['ID_Pedido_Ingresado'].nunique()
        
        ef_costeno = (ent_c / fact_c * 100) if fact_c > 0 else 100
        ef_bees = (ent_b / fact_b * 100) if fact_b > 0 else 100
        
        ef1, ef2 = st.columns(2)
        ef1.metric("📉 Efectividad de Entrega COSTEÑO", f"{ef_costeno:.2f} %", help="Pedidos Entregados Correctamente / Pedidos Facturados Totales")
        ef2.metric("🐝 Efectividad de Entrega BEES", f"{ef_bees:.2f} %", help="Pedidos Entregados Correctamente / Pedidos Facturados Totales")
        
        st.markdown("#### 📋 Matriz de Distribución de Motivos de Devolución")
        
        # Aislar filas con devoluciones reales en el mes de análisis
        df_dev_reales = df_facturados_mes[df_facturados_mes['Motivo_Devolucion'].notna() & (df_facturados_mes['Motivo_Devolucion'].astype(str).str.strip() != "")]
        
        if not df_dev_reales.empty:
            # Agrupación por motivos de devolución cruzados por canal
            pivot_dev = df_dev_reales.groupby('Motivo_Devolucion').agg(
                Pedidos_Totales=('ID_Pedido_Ingresado', 'nunique'),
                Pedidos_Costeno=('ID_Pedido_Ingresado', lambda x: x[df_dev_reales['Canal_UI'] == 'COSTEÑO (GENERAL)'].nunique()),
                Pedidos_Bees=('ID_Pedido_Ingresado', lambda x: x[df_dev_reales['Canal_UI'] == 'BEES'].nunique()),
                Capital_Impactado=('TOTAL', 'sum')
            ).reset_index()
            
            total_dev_pedidos = pivot_dev['Pedidos_Totales'].sum()
            pivot_dev['% Part. Total'] = (pivot_dev['Pedidos_Totales'] / total_dev_pedidos * 100).map("{:.2f}%".format)
            
            pivot_dev = pivot_dev.sort_values(by='Pedidos_Totales', ascending=False)
            
            # Tabla interactiva con opción de selección nativa para Deep-Dive mediante click
            st.markdown("💡 *Haz clic en cualquier fila de la tabla para abrir un desglose flotante en tiempo real de los pedidos afectados.*")
            
            seleccion_tabla = st.dataframe(
                pivot_dev,
                width='stretch',
                hide_index=True,
                column_config={
                    "Motivo_Devolucion": "Motivo de Rechazo",
                    "Pedidos_Totales": "Pedidos Afectados",
                    "Pedidos_Costeno": "Vol. Costeño",
                    "Pedidos_Bees": "Vol. BEES",
                    "Capital_Impactado": st.column_config.NumberColumn("Monto Pérdida", format="S/. %,.2f")
                },
                on_select="rerun",
                selection_mode="single_row"
            )
            
            # Interceptación de Selección para Deep-Dive (Simulación Interactiva de Ventana Emergente)
            if seleccion_tabla and seleccion_tabla['selection']['rows']:
                fila_idx = seleccion_tabla['selection']['rows'][0]
                motivo_critico = pivot_dev.iloc[fila_idx]['Motivo_Devolucion']
                
                st.markdown(f"### 🔍 Foco de Auditoría: `{motivo_critico}`")
                df_deep_dive = df_dev_reales[df_dev_reales['Motivo_Devolucion'] == motivo_critico][['Fecha_Facturacion_TXT', 'ID_Pedido_Ingresado', 'Codigo_Cliente', 'Canal_UI', 'TOTAL']]
                df_deep_dive.columns = ['FECHA FACTURA', 'ID PEDIDO', 'CÓDIGO CLIENTE', 'CANAL', 'MONTO TOTAL (S/.)']
                st.dataframe(df_deep_dive, width='stretch', hide_index=True)
        else:
            st.info("Excelente: No se registran motivos de devolución para los filtros seleccionados.")

# --- 8. BASE DE DATOS ESTRUCTURAL COMPLETA ---
st.markdown("---")
with st.expander("📋 Inspección General de la Base de Datos Estructural Filtrada"):
    st.dataframe(df_zona.drop(columns=['Fecha_Ingreso_DT', 'Fecha_Facturacion_DT', 'Canal_UI'], errors='ignore'), width='stretch', hide_index=True)
