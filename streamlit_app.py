from __future__ import annotations

from datetime import date
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pandas as pd
import plotly.express as px
import streamlit as st

from config.settings import APP_NAME, DATA_CACHE_TTL_SECONDS, PALETTE, SOURCE_SECRET_KEYS, recent_window_start
from src.analytics.metrics import funnel_metrics, quality_metrics
from src.analytics.public_dashboard import render_operations
from src.data.drive_loader import SourceConfigurationError, drive_service, read_google_sheet, sheets_service
from src.processing.cleaner import SchemaError, clean_conciliation
from src.processing.reconciler import apply_business_rules, combine_general_and_recent, merge_master

st.set_page_config(page_title=APP_NAME, layout="wide", initial_sidebar_state="collapsed")


def inject_design_tokens() -> None:
    st.markdown(f"""<style>
    :root {{ color-scheme: light dark; --canvas: #F6F8FC; --surface: #FFFFFF; --card: #FFFFFF; --text: #172033; --muted: #536078; --border: #CCD5E1; --shadow: rgba(15, 23, 42, .10); --focus: #5140C9; }}
    @media (prefers-color-scheme: dark) {{ :root {{ --canvas: {PALETTE['canvas']}; --surface: {PALETTE['surface']}; --card: {PALETTE['card']}; --text: {PALETTE['text']}; --muted: {PALETTE['muted']}; --border: {PALETTE['border']}; --shadow: rgba(0, 0, 0, .24); --focus: {PALETTE['primary']}; }} }}
    .stApp, [data-testid="stAppViewContainer"] {{ background: var(--canvas); color: var(--text); }}
    .main .block-container {{ max-width: 1440px; padding-top: 2rem; padding-bottom: 2.75rem; }}
    [data-testid="stHeader"] {{ background: transparent; }}
    [data-testid="stSidebar"] {{ background: var(--surface); border-right: 1px solid var(--border); }}
    [data-testid="stMetric"], [data-testid="stVerticalBlockBorderWrapper"] {{ background: var(--card); border: 1px solid var(--border); border-radius: 10px; box-shadow: 0 1px 2px var(--shadow); transition: border-color 160ms cubic-bezier(.2,.8,.2,1), transform 160ms cubic-bezier(.2,.8,.2,1), box-shadow 160ms cubic-bezier(.2,.8,.2,1); }}
    [data-testid="stMetricLabel"], [data-testid="stMetricValue"], .stMarkdown, .stText, label, [data-testid="stWidgetLabel"] {{ color: var(--text); }}
    [data-testid="stCaptionContainer"], .stCaption, .stCaption p {{ color: var(--muted) !important; }}
    @media (hover: hover) and (pointer: fine) {{ [data-testid="stMetric"]:hover, [data-testid="stVerticalBlockBorderWrapper"]:hover {{ border-color: var(--focus); transform: translateY(-1px); box-shadow: 0 8px 20px var(--shadow); }} }}
    .stButton > button {{ min-height: 2.65rem; border-radius: 8px; border-color: var(--border); color: var(--text); background: var(--surface); transition: background-color 160ms ease, border-color 160ms ease, transform 120ms ease; touch-action: manipulation; }}
    [data-baseweb="select"] > div, [data-baseweb="input"] > div, [data-testid="stDateInput"] input {{ background: var(--surface) !important; color: var(--text) !important; border-color: var(--border) !important; }}
    [data-baseweb="select"] *, [data-baseweb="input"] input {{ color: var(--text) !important; }}
    [role="radiogroup"] {{ gap: .45rem; flex-wrap: wrap; }}
    [data-testid="stHorizontalBlock"] {{ gap: 1rem; align-items: stretch; }}
    .stButton > button:active {{ transform: translateY(1px); }}
    button:focus-visible, [role="combobox"]:focus-visible, input:focus-visible {{ outline: 3px solid var(--focus); outline-offset: 2px; }}
    .eyebrow {{ color: var(--muted); font-size: .78rem; font-weight: 650; letter-spacing: .11em; text-transform: uppercase; }}
    .app-title {{ color: var(--text); margin: .1rem 0 .35rem; font-size: clamp(1.65rem, 3vw, 2.4rem); line-height: 1.15; overflow-wrap: anywhere; }}
    .app-subtitle {{ color: var(--muted); margin: 0 0 1.3rem; line-height: 1.5; }}
    .skeleton {{ height: 100px; border-radius: 10px; background: linear-gradient(100deg, var(--card) 32%, var(--surface) 46%, var(--card) 62%); background-size: 220% 100%; animation: shimmer 1.2s linear infinite; border: 1px solid var(--border); }}
    @keyframes shimmer {{ to {{ background-position: -220% 0; }} }}
    .quality-note {{ color: var(--muted); font-size: .88rem; }}
    @media (max-width: 740px) {{ .main .block-container {{ padding: 1.25rem 1rem 2rem; }} .app-subtitle {{ margin-bottom: 1rem; }} [data-testid="stMetric"] {{ padding: .7rem; }} }}
    @media (prefers-reduced-motion: reduce) {{ *, *::before, *::after {{ animation: none !important; transition: none !important; scroll-behavior: auto !important; }} }}
    </style>""", unsafe_allow_html=True)

def get_secret(name: str) -> str:
    value = st.secrets.get(name, "")
    if not value:
        raise SourceConfigurationError(f"Falta el secreto '{name}'.")
    return str(value)


@st.cache_resource
def get_drive():
    account = st.secrets.get("gcp_service_account")
    if not account:
        raise SourceConfigurationError("Falta la cuenta de servicio de solo lectura.")
    return drive_service(account)


@st.cache_resource
def get_sheets():
    account = st.secrets.get("gcp_service_account")
    if not account:
        raise SourceConfigurationError("Falta la cuenta de servicio de solo lectura.")
    return sheets_service(account)


@st.cache_data(ttl=DATA_CACHE_TTL_SECONDS, show_spinner=False)
def load_dashboard_data() -> tuple[pd.DataFrame, list[str]]:
    account = st.secrets.get("gcp_service_account")
    if not account:
        raise SourceConfigurationError("Falta la cuenta de servicio de solo lectura.")
    source_ids = {key: get_secret(secret_key) for key, secret_key in SOURCE_SECRET_KEYS.items()}
    account = dict(account)  # Materialize secrets on the main thread before workers.

    def fetch(source_key: str, sheet_name: str) -> pd.DataFrame:
        return read_google_sheet(drive_service(account), source_ids[source_key], sheet_name, sheets_service(account))

    with ThreadPoolExecutor(max_workers=2) as executor:
        general_future = executor.submit(fetch, "general", "Conciliacion")
        recent_future = executor.submit(fetch, "recent", "Conciliacion")
        general_raw = general_future.result()
        recent_raw = recent_future.result()
    master_raw = fetch("master", "Maestro_skus")
    general, general_warnings = clean_conciliation(general_raw, "GENERAL")
    recent, recent_warnings = clean_conciliation(recent_raw, "3M")
    combined = combine_general_and_recent(general, recent, date.today())
    final = apply_business_rules(merge_master(combined, master_raw), Path("config/return_reasons.json"))
    return final, general_warnings + recent_warnings


def fmt_money(value: float) -> str:
    return f"S/ {value:,.0f}"


def render_loading() -> None:
    for column in st.columns(4):
        column.markdown('<div class="skeleton" aria-label="Cargando métricas"></div>', unsafe_allow_html=True)


def filtered_data(data: pd.DataFrame, zone: str, route: str, channel: str, period: tuple[pd.Timestamp, pd.Timestamp]) -> pd.DataFrame:
    result = data.loc[data["Fecha_Ingreso_DT"].between(period[0], period[1])].copy()
    if zone != "TODAS":
        result = result.loc[result["Zona_OfVta_Clean"] == zone]
    if route != "TODAS":
        result = result.loc[result["Ruta_Final"] == route]
    if channel != "TODOS":
        result = result.loc[result["Canal_UI"] == channel]
    return result


def chart_layout(title: str) -> dict:
    return {"title": {"text": title, "font": {"color": "var(--text)", "size": 16}}, "paper_bgcolor": "var(--card)", "plot_bgcolor": "var(--card)", "font": {"color": "var(--muted)"}, "margin": {"l": 10, "r": 10, "t": 48, "b": 12}, "legend": {"orientation": "h", "y": 1.12}, "hovermode": "x unified"}


def temporal_controls(min_date: pd.Timestamp, max_date: pd.Timestamp) -> tuple[tuple[date, date] | None, str, str, float | None]:
    mode = st.radio("Rango de fechas", ("Mes actual", "Últimas 4 semanas", "Trimestre", "Histórico completo", "Personalizado"), key="filters_period_mode")
    if mode == "Histórico completo":
        period = (min_date.date(), max_date.date())
    elif mode == "Trimestre":
        period = (max(min_date.date(), (max_date - pd.DateOffset(months=3)).date()), max_date.date())
    elif mode == "Últimas 4 semanas":
        period = (max(min_date.date(), (max_date - pd.Timedelta(days=27)).date()), max_date.date())
    elif mode == "Mes actual":
        period = (date(max_date.year, max_date.month, 1), max_date.date())
    else:
        selected = st.date_input("Inicio y fin", value=(min_date.date(), max_date.date()), min_value=min_date.date(), max_value=max_date.date(), key="filters_custom_period")
        period = selected if isinstance(selected, tuple) and len(selected) == 2 else None
    granularity = st.selectbox("Granularidad", ("Automática", "Diario", "Semanal", "Mensual"), help="Automática: diario hasta 31 días, semanal hasta 180 y mensual después.", key="filters_granularity")
    comparison = st.selectbox("Comparativa", ("Sin comparativa", "Vs. periodo anterior (PoP)", "Vs. mismo periodo año anterior (YoY)", "Meta manual"), key="filters_comparison")
    meta = None
    if comparison == "Meta manual":
        meta = st.number_input("Meta de GMV facturado (S/)", min_value=0.0, value=0.0, step=1000.0, key="filters_meta")
    return period, granularity, comparison, meta


def reset_filters() -> None:
    for key in ("filters_zone", "filters_route", "filters_channel", "filters_period_mode", "filters_custom_period", "filters_granularity", "filters_comparison", "filters_meta"):
        st.session_state.pop(key, None)


def main() -> None:
    inject_design_tokens()
    st.markdown('<p class="eyebrow">Conciliación comercial · acceso público agregado</p>', unsafe_allow_html=True)
    st.markdown(f'<h1 class="app-title">{APP_NAME}</h1>', unsafe_allow_html=True)
    st.markdown('<p class="app-subtitle">Datos minimizados: sin detalle por cliente, factura, pedido ni exportación.</p>', unsafe_allow_html=True)
    skeleton = st.empty()
    with skeleton.container():
        render_loading()
    try:
        data, warnings = load_dashboard_data()
    except (SourceConfigurationError, SchemaError, ValueError) as error:
        skeleton.empty(); st.error("La fuente no está lista para una publicación segura."); st.caption(str(error)); st.info("Configure secretos y conceda acceso Lector a la cuenta de servicio. No use enlaces públicos de las bases."); return
    except Exception:
        skeleton.empty(); st.error("No se pudo actualizar el panel. El detalle está solo en los logs privados."); return
    skeleton.empty()
    if data.empty or data["Fecha_Ingreso_DT"].dropna().empty:
        st.warning("La actualización no contiene registros con fecha de ingreso válida.")
        return
    source_quality = quality_metrics(data)
    min_date, max_date = data["Fecha_Ingreso_DT"].min(), data["Fecha_Ingreso_DT"].max()
    st.caption(f"Cobertura disponible: {min_date:%d/%m/%Y} a {max_date:%d/%m/%Y}. Datos agregados, sin detalle ni exportación.")
    with st.sidebar:
        st.header("Filtros")
        st.caption("Control temporal")
        period, granularity, comparison, meta = temporal_controls(min_date, max_date)
        st.divider()
        st.caption("Filtros de corte")
        region = st.selectbox("Región", ["TODAS"], disabled=True, help="La fuente actual no contiene una región validada.")
        zone = st.selectbox("Zona", ["TODAS", *sorted(data["Zona_OfVta_Clean"].dropna().unique())], key="filters_zone")
        route = st.selectbox("Ruta", ["TODAS", *sorted(data["Ruta_Final"].dropna().unique())], key="filters_route")
        channel = st.selectbox("Canal", ["TODOS", *sorted(data["Canal_UI"].dropna().unique())], key="filters_channel")
        st.caption("Los filtros solo recalculan agregados de esta sesión.")
        if st.button("Restablecer filtros", width="stretch"):
            reset_filters(); st.rerun()
        if st.button("Refrescar fuentes", width="stretch"):
            st.cache_data.clear(); st.rerun()
    if period is None:
        st.info("Selecciona fecha de inicio y cierre."); return
    section = st.radio('Navegación', ['Resumen', 'Control de fugas', 'Canales', 'Rutas', 'Fricción'],
                       horizontal=True, key='dashboard_section')
    st.caption(f"Zona: {zone} · Ruta: {route} · Canal: {channel} · {period[0]:%d/%m/%Y} — {period[1]:%d/%m/%Y}")
    if section != 'Resumen':
        render_operations(data, section, period, zone=zone, channel=channel, region=region, route=route,
                          granularity=granularity, comparison=comparison, meta=meta)
        return
    active = filtered_data(data, zone, route, channel, (pd.Timestamp(period[0]), pd.Timestamp(period[1])))
    if active.empty:
        st.info("No hay pedidos para esta combinación. Ajusta los filtros para ver los indicadores.")
        return
    metrics = funnel_metrics(active)
    cards = st.columns(4)
    cards[0].metric("Pedidos ingresados", f"{metrics['orders']:,}")
    cards[1].metric("Tasa de facturación", f"{metrics['invoice_rate']:.1%}")
    cards[2].metric("Valor final conciliado", fmt_money(metrics["final_value"]))
    cards[3].metric("Conversión final", f"{metrics['final_conversion_rate']:.1%}")
    by_month = active.assign(Mes=active["Fecha_Ingreso_DT"].dt.to_period("M").astype(str)).groupby("Mes", as_index=False).agg(Valor_final=("Saldo_Total_Pedido", "sum"), Pedidos=("ID_Pedido_Ingresado", "nunique"))
    by_channel = active.groupby("Canal_UI", as_index=False).agg(Valor_final=("Saldo_Total_Pedido", "sum"))
    if by_month["Valor_final"].abs().sum() > 0:
        left, right = st.columns((1.55, 1))
        with left:
            figure = px.line(by_month, x="Mes", y="Valor_final", markers=True, color_discrete_sequence=[PALETTE["primary"]])
            figure.update_traces(line={"width": 3}, marker={"size": 7}); figure.update_layout(**chart_layout("Evolución del valor final conciliado"), yaxis_title="Soles", xaxis_title=""); figure.update_xaxes(gridcolor=PALETTE["border"]); figure.update_yaxes(gridcolor=PALETTE["border"])
            st.plotly_chart(figure, width="stretch", config={"displayModeBar": False})
        with right:
            figure = px.pie(by_channel, values="Valor_final", names="Canal_UI", hole=.64, color_discrete_sequence=[PALETTE["primary"], PALETTE["secondary"], PALETTE["border"]]); figure.update_layout(**chart_layout("Participación por canal"), showlegend=True)
            st.plotly_chart(figure, width="stretch", config={"displayModeBar": False})
    else:
        st.info("No hay valor final conciliado distinto de cero para los filtros elegidos.")
    states = active.groupby("Estado_Conciliacion", as_index=False).agg(Pedidos=("ID_Pedido_Ingresado", "nunique"))
    figure = px.bar(states, x="Estado_Conciliacion", y="Pedidos", color="Estado_Conciliacion", color_discrete_map={"ENTREGADO_TOTAL": PALETTE["positive"], "ENTREGADO_PARCIAL": PALETTE["primary"], "NO_FACTURADO": PALETTE["negative"], "SIN_VALOR_FINAL": PALETTE["muted"]})
    figure.update_layout(**chart_layout("Embudo de estado de conciliación"), showlegend=False, xaxis_title="", yaxis_title="Pedidos"); figure.update_xaxes(gridcolor=PALETTE["border"]); figure.update_yaxes(gridcolor=PALETTE["border"])
    st.plotly_chart(figure, width="stretch", config={"displayModeBar": False})
    with st.expander("Calidad y trazabilidad de la actualización"):
        active_quality = quality_metrics(active)
        summary = pd.DataFrame([
            {"Ámbito": "Fuentes cargadas", "Filas": source_quality["rows"], "Pedidos": source_quality["orders"], "Sin maestro": source_quality["missing_master_rows"], "Fechas inválidas": source_quality["invalid_ingress_date_rows"], "Campos numéricos ausentes": source_quality["source_numeric_missing"], "Formato numérico inválido": source_quality["invalid_numeric_format"]},
            {"Ámbito": "Filtros activos", "Filas": active_quality["rows"], "Pedidos": active_quality["orders"], "Sin maestro": active_quality["missing_master_rows"], "Fechas inválidas": active_quality["invalid_ingress_date_rows"], "Campos numéricos ausentes": active_quality["source_numeric_missing"], "Formato numérico inválido": active_quality["invalid_numeric_format"]},
        ])
        st.table(summary)
        for warning in warnings:
            st.warning(warning)
        st.markdown('<p class="quality-note">AC / Saldo_Total_Pedido se suma por línea. Un pedido sin P / ID_Factura_Final se clasifica como no facturado. Los formatos numéricos inválidos no se convierten en cero.</p>', unsafe_allow_html=True)


if __name__ == "__main__":
    main()
