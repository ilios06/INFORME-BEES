from __future__ import annotations

from datetime import date
from pathlib import Path

import pandas as pd
import plotly.express as px
import streamlit as st

from config.settings import APP_NAME, DATA_CACHE_TTL_SECONDS, PALETTE, SOURCE_SECRET_KEYS
from src.analytics.metrics import funnel_metrics, quality_metrics
from src.data.drive_loader import SourceConfigurationError, drive_service, read_google_sheet, sheets_service
from src.processing.cleaner import SchemaError, clean_conciliation
from src.processing.reconciler import apply_business_rules, combine_general_and_recent, merge_master

st.set_page_config(page_title=APP_NAME, layout="wide", initial_sidebar_state="expanded")


def inject_design_tokens() -> None:
    st.markdown(f"""<style>
    :root {{ color-scheme: dark; }}
    .stApp {{ background: {PALETTE['canvas']}; color: {PALETTE['text']}; }}
    [data-testid="stSidebar"] {{ background: {PALETTE['surface']}; border-right: 1px solid {PALETTE['border']}; }}
    [data-testid="stMetric"], [data-testid="stVerticalBlockBorderWrapper"] {{ background: {PALETTE['card']}; border: 1px solid {PALETTE['border']}; border-radius: 10px; transition: border-color 160ms ease, transform 160ms ease, box-shadow 160ms ease; }}
    [data-testid="stMetric"]:hover, [data-testid="stVerticalBlockBorderWrapper"]:hover {{ border-color: {PALETTE['primary']}; transform: translateY(-1px); box-shadow: 0 8px 20px rgba(0,0,0,.18); }}
    .eyebrow {{ color: {PALETTE['muted']}; font-size: .78rem; font-weight: 650; letter-spacing: .11em; text-transform: uppercase; }}
    .app-title {{ color: {PALETTE['text']}; margin: .1rem 0 .35rem; font-size: clamp(1.65rem, 3vw, 2.4rem); }}
    .app-subtitle {{ color: {PALETTE['muted']}; margin: 0 0 1.3rem; }}
    .skeleton {{ height: 100px; border-radius: 10px; background: linear-gradient(100deg, {PALETTE['card']} 32%, {PALETTE['surface']} 46%, {PALETTE['card']} 62%); background-size: 220% 100%; animation: shimmer 1.2s linear infinite; border: 1px solid {PALETTE['border']}; }}
    @keyframes shimmer {{ to {{ background-position: -220% 0; }} }}
    @media (prefers-reduced-motion: reduce) {{ *, *::before, *::after {{ animation-duration: .01ms !important; transition-duration: .01ms !important; }} }}
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
    service = get_drive()
    sheets = get_sheets()
    general_raw = read_google_sheet(service, get_secret(SOURCE_SECRET_KEYS["general"]), "Conciliacion", sheets)
    recent_raw = read_google_sheet(service, get_secret(SOURCE_SECRET_KEYS["recent"]), "Conciliacion", sheets)
    master_raw = read_google_sheet(service, get_secret(SOURCE_SECRET_KEYS["master"]), "Maestro_skus", sheets)
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


def filtered_data(data: pd.DataFrame, zone: str, channel: str, period: tuple[pd.Timestamp, pd.Timestamp]) -> pd.DataFrame:
    result = data.loc[data["Fecha_Ingreso_DT"].between(period[0], period[1])].copy()
    if zone != "TODAS": result = result.loc[result["Zona_OfVta_Clean"] == zone]
    if channel != "TODOS": result = result.loc[result["Canal_UI"] == channel]
    return result


def chart_layout(title: str) -> dict:
    return {"title": {"text": title, "font": {"color": PALETTE["text"], "size": 16}}, "paper_bgcolor": PALETTE["card"], "plot_bgcolor": PALETTE["card"], "font": {"color": PALETTE["muted"]}, "margin": {"l": 10, "r": 10, "t": 48, "b": 12}, "legend": {"orientation": "h", "y": 1.12}}


def main() -> None:
    inject_design_tokens()
    st.markdown('<p class="eyebrow">Conciliación comercial · acceso público agregado</p>', unsafe_allow_html=True)
    st.markdown(f'<h1 class="app-title">{APP_NAME}</h1>', unsafe_allow_html=True)
    st.markdown('<p class="app-subtitle">Datos minimizados: sin detalle por cliente, factura, pedido ni exportación.</p>', unsafe_allow_html=True)
    skeleton = st.empty()
    with skeleton.container(): render_loading()
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
    min_date, max_date = data["Fecha_Ingreso_DT"].min(), data["Fecha_Ingreso_DT"].max()
    with st.sidebar:
        st.header("Filtros")
        zone = st.selectbox("Zona", ["TODAS", *sorted(data["Zona_OfVta_Clean"].dropna().unique())])
        channel = st.selectbox("Canal", ["TODOS", *sorted(data["Canal_UI"].dropna().unique())])
        period = st.date_input("Periodo", value=(min_date.date(), max_date.date()), min_value=min_date.date(), max_value=max_date.date())
        st.caption("Los filtros cambian únicamente agregados del servidor.")
        if st.button("Actualizar datos"): st.cache_data.clear(); st.rerun()
    if not isinstance(period, tuple) or len(period) != 2:
        st.info("Selecciona fecha de inicio y cierre."); return
    active = filtered_data(data, zone, channel, (pd.Timestamp(period[0]), pd.Timestamp(period[1])))
    metrics = funnel_metrics(active)
    cards = st.columns(4)
    cards[0].metric("Pedidos ingresados", f"{metrics['orders']:,}")
    cards[1].metric("Tasa de facturación", f"{metrics['invoice_rate']:.1%}")
    cards[2].metric("Valor final conciliado", fmt_money(metrics["final_value"]))
    cards[3].metric("Conversión final", f"{metrics['final_conversion_rate']:.1%}")
    by_month = active.assign(Mes=active["Fecha_Ingreso_DT"].dt.to_period("M").astype(str)).groupby("Mes", as_index=False).agg(Valor_final=("Saldo_Total_Pedido", "sum"), Pedidos=("ID_Pedido_Ingresado", "nunique"))
    by_channel = active.groupby("Canal_UI", as_index=False).agg(Valor_final=("Saldo_Total_Pedido", "sum"))
    left, right = st.columns((1.55, 1))
    with left:
        figure = px.line(by_month, x="Mes", y="Valor_final", markers=True, color_discrete_sequence=[PALETTE["primary"]])
        figure.update_traces(line={"width": 3}, marker={"size": 7}); figure.update_layout(**chart_layout("Evolución del valor final conciliado"), yaxis_title="Soles", xaxis_title=""); figure.update_xaxes(gridcolor=PALETTE["border"]); figure.update_yaxes(gridcolor=PALETTE["border"])
        st.plotly_chart(figure, use_container_width=True, config={"displayModeBar": False})
    with right:
        figure = px.pie(by_channel, values="Valor_final", names="Canal_UI", hole=.64, color_discrete_sequence=[PALETTE["primary"], PALETTE["secondary"], PALETTE["border"]]); figure.update_layout(**chart_layout("Participación por canal"), showlegend=True)
        st.plotly_chart(figure, use_container_width=True, config={"displayModeBar": False})
    states = active.groupby("Estado_Conciliacion", as_index=False).agg(Pedidos=("ID_Pedido_Ingresado", "nunique"))
    figure = px.bar(states, x="Estado_Conciliacion", y="Pedidos", color="Estado_Conciliacion", color_discrete_map={"ENTREGADO_TOTAL": PALETTE["positive"], "ENTREGADO_PARCIAL": PALETTE["primary"], "NO_FACTURADO": PALETTE["negative"], "SIN_VALOR_FINAL": PALETTE["muted"]})
    figure.update_layout(**chart_layout("Embudo de estado de conciliación"), showlegend=False, xaxis_title="", yaxis_title="Pedidos"); figure.update_xaxes(gridcolor=PALETTE["border"]); figure.update_yaxes(gridcolor=PALETTE["border"])
    st.plotly_chart(figure, use_container_width=True, config={"displayModeBar": False})
    with st.expander("Calidad y trazabilidad de la actualización"):
        quality = quality_metrics(active)
        st.dataframe(pd.DataFrame([quality]).rename(columns={"missing_master_rows": "Filas SIN_MAESTRO", "invalid_ingress_date_rows": "Fechas inválidas", "source_numeric_missing": "Campos numéricos ausentes", "ac_nonzero_multi_line_orders": "Pedidos con AC no-cero en múltiples líneas"}), hide_index=True, use_container_width=True)
        for warning in warnings: st.warning(warning)
        st.caption("AC / Saldo_Total_Pedido se suma por línea. Un pedido sin P / ID_Factura_Final se clasifica como no facturado.")


if __name__ == "__main__": main()
