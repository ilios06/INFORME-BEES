"""Public, aggregate-only operational views over the authenticated SAP contract."""
from __future__ import annotations

import numpy as np
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st
from plotly.subplots import make_subplots

from config.settings import DATA_CACHE_TTL_SECONDS, PALETTE
from src.analytics.operations import aggregate, divide, layers, pareto, select, summary


def operational_frame(source: pd.DataFrame) -> pd.DataFrame:
    d = pd.DataFrame(index=source.index)
    mapping = {'id_pedido': 'ID_Pedido_Ingresado', 'id_cliente': 'Codigo_Cliente',
               'id_sku': 'SKU_Material_Ingresado', 'zona': 'Zona_OfVta_Clean',
               'ruta': 'Ruta_Final', 'canal': 'Canal_UI', 'categoria_sku': 'Categoria Cuota',
               'marca_sku': 'Marca', 'motivo_devol': 'Motivo_Devolucion_Categoria'}
    for target, origin in mapping.items():
        d[target] = source[origin].astype('string').str.strip().replace('', pd.NA)
    d['region'] = 'SIN_REGION_VALIDADA'  # The source contract has no validated region.
    d['fecha_pedido'] = source.Fecha_Ingreso_DT.dt.normalize()
    d['facturado'] = source.has_invoice
    for target, origin in [('cant_ingresada', 'Cantidad_Ingresada'), ('cant_facturada', 'Cantidad_Facturada'),
                           ('cant_devuelta', 'Cantidad_Devuelta_UM_Comercial')]:
        d[target] = source[origin].where(source[origin].ge(0))
    d['cant_devuelta'] = d.cant_devuelta.where(d.cant_devuelta.le(d.cant_facturada))
    price = divide(source.Valor_Neto_Ingresado, d.cant_ingresada).where(lambda s: s.ge(0))
    weight = divide(source.Peso_Ingresado, d.cant_ingresada).where(lambda s: s.ge(0))
    for stage, qty in [('ingresado', 'cant_ingresada'), ('facturado', 'cant_facturada'), ('devuelto', 'cant_devuelta')]:
        d['gmv_' + stage], d['kg_' + stage] = d[qty] * price, d[qty] * weight
    d['gmv_entregado'] = d.gmv_facturado - d.gmv_devuelto
    gap = (d.cant_ingresada - d.cant_facturada).clip(lower=0)
    d['fuga_pre'], d['kg_fuga_pre'] = gap * price, gap * weight
    d['devuelto'] = d.cant_devuelta.gt(0) | source.Total_Devuelto.gt(0)
    for col in ['region', 'zona', 'ruta', 'canal', 'categoria_sku', 'marca_sku', 'motivo_devol']:
        d[col] = d[col].fillna('SIN_CLASIFICAR').astype('category')
    return d


@st.cache_data(ttl=DATA_CACHE_TTL_SECONDS, show_spinner=False)
def prepare_operations(source: pd.DataFrame) -> dict[str, pd.DataFrame]:
    return layers(operational_frame(source))


def adaptive_granularity(start, end, requested: str = 'Automática') -> str:
    days = (pd.Timestamp(end).normalize() - pd.Timestamp(start).normalize()).days + 1
    return requested if requested != 'Automática' else ('Diario' if days <= 31 else 'Semanal' if days <= 180 else 'Mensual')


def period_compare(start, end, mode: str) -> tuple[pd.Timestamp, pd.Timestamp] | None:
    start_ts, end_ts = pd.Timestamp(start).normalize(), pd.Timestamp(end).normalize()
    if mode in ('Sin comparativa', 'Meta manual'):
        return None
    if mode == 'Vs. mismo periodo año anterior (YoY)':
        return start_ts - pd.DateOffset(years=1), end_ts - pd.DateOffset(years=1)
    days = (end_ts - start_ts).days + 1
    return start_ts - pd.Timedelta(days=days), start_ts - pd.Timedelta(days=1)


def period_label(frame: pd.DataFrame, granularity: str) -> pd.Series:
    dates = pd.to_datetime(frame.fecha_pedido)
    return {'Diario': dates.dt.to_period('D'), 'Semanal': dates.dt.to_period('W-MON'),
            'Mensual': dates.dt.to_period('M')}[granularity].astype(str)


def metric_delta(current: float, reference: float, inverse: bool = False) -> tuple[str | None, str]:
    if pd.isna(current) or pd.isna(reference) or reference == 0:
        return None, 'normal'
    return f'{(current / reference - 1) * 100:+.1f}% vs. referencia', 'inverse' if inverse else 'normal'


def money(value: float) -> str:
    return 'Sin base completa' if pd.isna(value) else f'S/ {value:,.0f}'


def show_chart(figure: go.Figure) -> None:
    # CSS variables follow the active Streamlit light/dark scheme, unlike fixed dark tokens.
    figure.update_layout(paper_bgcolor='var(--card)', plot_bgcolor='var(--card)', font={'color': 'var(--text)'},
                         margin=dict(l=10, r=10, t=48, b=70), legend_title_text='',
                         legend={'orientation': 'h', 'x': 0, 'xanchor': 'left', 'y': -0.22, 'yanchor': 'top'}, hovermode='x unified')
    figure.update_xaxes(gridcolor='var(--border)'); figure.update_yaxes(gridcolor='var(--border)')
    st.plotly_chart(figure, width='stretch', config={'displayModeBar': False})


def display_table(frame: pd.DataFrame) -> None:
    presentation = frame.copy()
    tonnes = {'kg_ingresado': 'Toneladas ingresadas', 'kg_facturado': 'Toneladas facturadas',
              'kg_devuelto': 'Toneladas devueltas', 'kg_fuga_pre': 'Toneladas fuga prefactura', 'drop_kg': 'Kg / pedido'}
    for column, label in tonnes.items():
        if column in presentation:
            presentation[label] = presentation.pop(column) / (1_000 if column != 'drop_kg' else 1)
    labels = {'canal': 'Canal', 'ruta': 'Ruta', 'zona': 'Zona', 'region': 'Región', 'gmv_facturado': 'Facturado neto modelo (S/)',
              'gmv_devuelto': 'Devuelto neto modelo (S/)', 'gmv_entregado': 'Neto entregado modelo (S/)',
              'pedidos_facturados': 'Pedidos facturados', 'clientes': 'Clientes únicos', 'ticket': 'S/ por pedido',
              'densidad': 'S/ por kg', 'frecuencia': 'Pedidos / cliente', 'tasa_devolucion': 'Devolución (%)',
              'tasa_pre': 'Fuga pre (%)', 'fuga_pre': 'Fuga prefactura (S/)', 'motivo_devol': 'Familia de motivo',
              'categoria_sku': 'Categoría', 'marca_sku': 'Marca', 'ABC': 'Grupo ABC'}
    st.dataframe(presentation.rename(columns=labels).round(2), width='stretch', hide_index=True)


def _filters(zone: str, route: str, channel: str) -> dict[str, list[str]]:
    return {'zona': [] if zone == 'TODAS' else [zone],
            'ruta': [] if route == 'TODAS' else [route], 'canal': [] if channel == 'TODOS' else [channel]}


def _time_summary(selected: dict[str, pd.DataFrame], granularity: str, keys: list[str] | None = None) -> pd.DataFrame:
    keys = keys or []
    cube, orders, customers = selected['cube'].copy(), selected['orders'].copy(), selected['customers'].copy()
    for frame in (cube, orders, customers):
        frame['periodo'] = period_label(frame, granularity)
    return summary({'cube': cube, 'orders': orders, 'customers': customers}, ['periodo', *keys])


def _reference(data, period, filters, comparison: str) -> pd.Series | None:
    prior = period_compare(*period, comparison)
    if prior is None:
        return None
    selected = select(data, *prior, filters)
    return None if selected['cube'].empty else summary(selected, ['Total']).iloc[0]


def _impact_cards(total: pd.Series, reference: pd.Series | None, comparison: str, meta: float | None) -> None:
    fields = [('GMV facturado', 'gmv_facturado', False, money),
              ('Fill rate monetario', 'tasa_facturacion', False, lambda v: 'Sin base completa' if pd.isna(v) else f'{v:.1f}%'),
              ('Fuga pre-factura', 'fuga_pre', True, money), ('Fuga post-factura', 'gmv_devuelto', True, money)]
    for cell, (label, field, inverse, formatter) in zip(st.columns(4), fields):
        ref = meta if comparison == 'Meta manual' and field == 'gmv_facturado' else (reference[field] if reference is not None else np.nan)
        delta, color = metric_delta(total[field], ref, inverse)
        cell.metric(label, formatter(total[field]), delta=delta, delta_color=color)
        if field == 'fuga_pre' and pd.notna(total.kg_fuga_pre): cell.caption(f'{total.kg_fuga_pre / 1_000:,.3f} t perdidas')
        if field == 'gmv_devuelto' and pd.notna(total.tasa_devolucion): cell.caption(f'{total.tasa_devolucion:.1f}% sobre facturado')


def _funnel_module(selected, total, granularity, reference, comparison, meta) -> None:
    _impact_cards(total, reference, comparison, meta)
    left, right = st.columns((1, 1.25))
    with left:
        chart = go.Figure(go.Waterfall(name='Conversión', measure=['absolute', 'relative', 'total', 'relative', 'total'],
            x=['GMV ingresado', 'Fuga pre', 'GMV facturado', 'Fuga post', 'GMV neto entregado'],
            y=[total.gmv_ingresado, -total.fuga_pre, None, -total.gmv_devuelto, None], textposition='outside',
            decreasing={'marker': {'color': '#C75252'}}, increasing={'marker': {'color': PALETTE['primary']}},
            totals={'marker': {'color': PALETTE['positive']}}))
        chart.update_layout(title='Embudo de valor: demanda a entrega', yaxis_title='Soles'); show_chart(chart)
    with right:
        temporal = _time_summary(selected, granularity)
        chart = make_subplots(specs=[[{'secondary_y': True}]])
        chart.add_trace(go.Scatter(x=temporal.periodo, y=temporal.tasa_pre, name='Fuga pre (%)', line={'color': PALETTE['primary'], 'width': 3}), secondary_y=False)
        chart.add_trace(go.Scatter(x=temporal.periodo, y=temporal.tasa_devolucion, name='Fuga post (%)', line={'color': '#D97706', 'width': 3}), secondary_y=True)
        chart.add_hrect(y0=0, y1=2.5, fillcolor='#94A3B8', opacity=.13, line_width=0, annotation_text='Banda 2.5%')
        chart.update_layout(title=f'Fugas relativas · {granularity.lower()} · azul: pre / naranja: post', showlegend=False)
        chart.update_yaxes(title_text='Fuga pre (%)', secondary_y=False); chart.update_yaxes(title_text='Devolución (%)', secondary_y=True); show_chart(chart)


def _channels_module(selected, granularity) -> None:
    comparison = summary(selected, ['canal'])
    display_table(comparison[['canal', 'pedidos_facturados', 'kg_facturado', 'drop_kg', 'ticket', 'densidad', 'tasa_devolucion']])
    proxy = _time_summary(selected, 'Diario', ['canal'])
    box = px.box(proxy, x='canal', y='drop_kg', points='outliers', color='canal', labels={'drop_kg': 'Kg facturados por pedido', 'canal': 'Canal'},
                 color_discrete_sequence=[PALETTE['primary'], PALETTE['secondary']]); box.update_layout(title='Distribución de drop size · proxy agregado día-canal'); show_chart(box)
    temporal = _time_summary(selected, granularity, ['canal'])
    chart = make_subplots(specs=[[{'secondary_y': True}]])
    for canal, part in temporal.groupby('canal', observed=True):
        color = PALETTE['primary'] if str(canal).upper() == 'BEES' else PALETTE['secondary']
        chart.add_trace(go.Bar(x=part.periodo, y=part.kg_facturado / 1_000, name=f'{canal} · t', marker_color=color, opacity=.65), secondary_y=False)
        chart.add_trace(go.Scatter(x=part.periodo, y=part.drop_kg, name=f'{canal} · kg/ped', line={'color': color, 'dash': 'dot'}), secondary_y=True)
    chart.update_layout(title=f'Volumen y calidad de pedido · {granularity.lower()}', barmode='stack')
    chart.update_yaxes(title_text='Toneladas', secondary_y=False); chart.update_yaxes(title_text='Kg por pedido', secondary_y=True); show_chart(chart)


def _routes_module(selected, granularity) -> None:
    routes = summary(selected, ['zona', 'ruta', 'canal'])
    direction = st.radio('Ranking de carga', ['Mayor carga', 'Menor carga (rutas huecas)'], horizontal=True, key='operation_ranking')
    ranked = routes.sort_values('kg_facturado', ascending=direction.startswith('Menor')).head(15)
    chart = px.bar(ranked, x='kg_facturado', y='ruta', color='canal', orientation='h', barmode='stack', labels={'kg_facturado': 'Kg facturados', 'ruta': 'Ruta'}, color_discrete_sequence=[PALETTE['primary'], PALETTE['secondary']])
    chart.update_layout(title=f'Top 15 rutas por carga · {direction}', yaxis={'categoryorder': 'total ascending'}); show_chart(chart)
    operational = summary(selected, ['zona', 'ruta']); operational['toneladas_por_pedido'] = operational.drop_kg / 1_000
    valid = operational.replace([np.inf, -np.inf], np.nan).dropna(subset=['pedidos_facturados', 'toneladas_por_pedido', 'ticket', 'tasa_devolucion'])
    valid = valid.loc[valid.ticket.gt(0) & valid.pedidos_facturados.gt(0)]
    if valid.empty:
        st.info('No hay rutas con facturación y devolución comparables para la matriz en este período.')
    else:
        chart = px.scatter(valid, x='pedidos_facturados', y='toneladas_por_pedido', size='ticket', color='tasa_devolucion', hover_name='ruta',
            color_continuous_scale=['#2E9D70', '#E3A23B', '#C75252'], labels={'pedidos_facturados': 'Pedidos facturados', 'toneladas_por_pedido': 't por pedido', 'tasa_devolucion': 'Devolución (%)', 'ticket': 'S/ por pedido'})
        chart.add_vline(x=valid.pedidos_facturados.median(), line_dash='dot', line_color=PALETTE['muted']); chart.add_hline(y=valid.toneladas_por_pedido.median(), line_dash='dot', line_color=PALETTE['muted'])
        chart.update_layout(title='Matriz de presión: paradas, carga y devolución'); show_chart(chart)
    heat = _time_summary(selected, granularity, ['ruta']).pivot(index='ruta', columns='periodo', values='tasa_devolucion').dropna(how='all').head(30)
    if not heat.empty:
        chart = px.imshow(heat, aspect='auto', color_continuous_scale=['#2E9D70', '#F3C566', '#C75252'], labels={'color': 'Devolución (%)', 'x': 'Periodo', 'y': 'Ruta'})
        chart.update_layout(title=f'Consistencia temporal de devoluciones · {granularity.lower()}'); show_chart(chart)


def _friction_module(selected) -> None:
    reasons = aggregate(selected['returns'], ['motivo_devol'], ['gmv_devuelto']).sort_values('gmv_devuelto', ascending=False)
    if not reasons.empty:
        reasons['acumulado'] = divide(reasons.gmv_devuelto.cumsum(), reasons.gmv_devuelto.sum(min_count=1)) * 100
        chart = make_subplots(specs=[[{'secondary_y': True}]])
        chart.add_trace(go.Bar(x=reasons.motivo_devol, y=reasons.gmv_devuelto, name='Monto devuelto', marker_color=PALETTE['secondary']), secondary_y=False)
        chart.add_trace(go.Scatter(x=reasons.motivo_devol, y=reasons.acumulado, name='% acumulado', line={'color': PALETTE['primary'], 'width': 3}), secondary_y=True)
        chart.add_hline(y=80, line_dash='dot', line_color=PALETTE['muted'], secondary_y=True); chart.update_layout(title='Pareto de motivos de devolución')
        chart.update_yaxes(title_text='Soles', secondary_y=False); chart.update_yaxes(title_text='% acumulado', range=[0, 105], secondary_y=True); show_chart(chart)
    st.caption('Clientes y SKU individuales no se publican. Esta auditoría conserva cohortes y categoría/marca.')
    clients = pareto(selected['clients'].loc[selected['clients'].id_cliente.notna()], 'id_cliente', 'gmv_devuelto')
    cohorts = clients.groupby('ABC', observed=True).agg(Clientes=('id_cliente', 'nunique'), Monto_devuelto=('gmv_devuelto', 'sum')).reset_index()
    left, right = st.columns((.8, 1.2))
    with left: display_table(cohorts)
    with right:
        categories = aggregate(selected['skus'], ['categoria_sku', 'marca_sku'], ['fuga_pre', 'gmv_ingresado'])
        categories['tasa_fuga_pre'] = divide(categories.fuga_pre, categories.gmv_ingresado) * 100
        chart = px.treemap(categories, path=['categoria_sku', 'marca_sku'], values='gmv_ingresado', color='tasa_fuga_pre', color_continuous_scale=['#2E9D70', '#F3C566', '#C75252'], labels={'tasa_fuga_pre': 'Fuga pre (%)', 'gmv_ingresado': 'Demanda S/'})
        chart.update_layout(title='Fuga pre por categoría y marca'); show_chart(chart)


def render_operations(data: pd.DataFrame, section: str, period, zone: str = 'TODAS', channel: str = 'TODOS', route: str = 'TODAS', granularity: str = 'Automática', comparison: str = 'Sin comparativa', meta: float | None = None) -> None:
    prepared = prepare_operations(data); filters = _filters(zone, route, channel); selected = select(prepared, *period, filters)
    if selected['cube'].empty: st.info('No hay registros para los filtros activos.'); return
    grain = adaptive_granularity(*period, granularity); total = summary(selected, ['Total']).iloc[0]; reference = _reference(prepared, period, filters, comparison)
    st.subheader(section); st.caption(f'Granularidad activa: {grain.lower()} · Comparativa: {comparison}. Modelo comparable sin impuestos; pesos en toneladas cuando corresponde.')
    if section == 'Control de fugas': _funnel_module(selected, total, grain, reference, comparison, meta)
    elif section == 'Canales': _channels_module(selected, grain)
    elif section == 'Rutas': _routes_module(selected, grain)
    elif section == 'Fricción': _friction_module(selected)
