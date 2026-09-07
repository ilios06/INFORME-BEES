"""Public, aggregate-only operational views over the authenticated SAP contract."""
import pandas as pd
import plotly.express as px
import streamlit as st

from config.settings import DATA_CACHE_TTL_SECONDS
from src.analytics.operations import aggregate, divide, layers, pareto, select, summary


def operational_frame(source):
    d = pd.DataFrame(index=source.index)
    mapping = {'id_pedido':'ID_Pedido_Ingresado', 'id_cliente':'Codigo_Cliente',
               'id_sku':'SKU_Material_Ingresado', 'zona':'Zona_OfVta_Clean',
               'ruta':'Ruta_Final', 'canal':'Canal_UI', 'categoria_sku':'Categoria Cuota',
               'marca_sku':'Marca', 'motivo_devol':'Motivo_Devolucion_Categoria'}
    for target, origin in mapping.items():
        d[target] = source[origin].astype('string').str.strip().replace('', pd.NA)
    # No invented region assignment: the deployed contract supplies sales zone only.
    d['region'] = 'SIN_REGION_VALIDADA'
    d['fecha_pedido'] = source.Fecha_Ingreso_DT.dt.normalize()
    d['facturado'] = source.has_invoice
    for target, origin in [('cant_ingresada','Cantidad_Ingresada'),
                           ('cant_facturada','Cantidad_Facturada'),
                           ('cant_devuelta','Cantidad_Devuelta_UM_Comercial')]:
        d[target] = source[origin].where(source[origin].ge(0))
    # Comparable commercial units only. A blank or invalid return is not zero.
    d['cant_devuelta'] = d.cant_devuelta.where(d.cant_devuelta.le(d.cant_facturada))
    price = divide(source.Valor_Neto_Ingresado, d.cant_ingresada)
    weight = divide(source.Peso_Ingresado, d.cant_ingresada)
    price = price.where(price.ge(0))
    weight = weight.where(weight.ge(0))
    for stage, qty in [('ingresado','cant_ingresada'), ('facturado','cant_facturada'), ('devuelto','cant_devuelta')]:
        d['gmv_' + stage] = d[qty] * price
        d['kg_' + stage] = d[qty] * weight
    d['gmv_entregado'] = d.gmv_facturado - d.gmv_devuelto
    gap = (d.cant_ingresada - d.cant_facturada).clip(lower=0)
    d['fuga_pre'] = gap * price
    d['kg_fuga_pre'] = gap * weight
    d['devuelto'] = d.cant_devuelta.gt(0) | source.Total_Devuelto.gt(0)
    for col in ['region','zona','ruta','canal','categoria_sku','marca_sku','motivo_devol']:
        d[col] = d[col].fillna('SIN_CLASIFICAR').astype('category')
    return d


@st.cache_data(ttl=DATA_CACHE_TTL_SECONDS, show_spinner=False)
def prepare_operations(source):
    return layers(operational_frame(source))


def show_chart(figure):
    figure.update_layout(margin=dict(l=10, r=10, t=35, b=10), legend_title_text='')
    st.plotly_chart(figure, width='stretch', config={'displayModeBar':False})


def display_table(frame):
    # Only callers with an explicit aggregate projection may render a table.
    presentation = frame.copy()
    tonne_columns = {
        'kg_ingresado':'Toneladas ingresadas', 'kg_facturado':'Toneladas facturadas',
        'kg_devuelto':'Toneladas devueltas', 'kg_fuga_pre':'Toneladas fuga prefactura',
        'drop_kg':'Toneladas / pedido',
    }
    for column, label in tonne_columns.items():
        if column in presentation:
            presentation[label] = presentation.pop(column) / 1_000
    st.table(presentation.rename(columns={
        'canal':'Canal', 'ruta':'Ruta', 'zona':'Zona', 'gmv_facturado':'Facturado neto modelo (S/)',
        'gmv_devuelto':'Devuelto neto modelo (S/)',
        'pedidos_facturados':'Pedidos facturados', 'clientes':'Clientes únicos',
        'ticket':'S/ por pedido', 'densidad':'S/ por kg',
        'frecuencia':'Pedidos / cliente', 'tasa_devolucion':'Devolución (%)',
        'fuga_pre':'Fuga prefactura (S/)', 'motivo_devol':'Familia de motivo',
        'categoria_sku':'Categoría', 'marca_sku':'Marca', 'ABC':'Grupo ABC'}).round(2))


def render_operations(data, section, period, zone, channel):
    filters = {'zona': [] if zone == 'TODAS' else [zone],
               'canal': [] if channel == 'TODOS' else [channel]}
    selected = select(prepare_operations(data), *period, filters)
    if selected['cube'].empty:
        st.info('No hay registros para los filtros activos.'); return
    st.subheader(section)
    st.caption('Modelo comparable sin impuestos: cantidades comerciales × precio neto unitario de ingreso. '
               'No sustituye los importes fiscales de SAP ni el saldo conciliado del Resumen. '
               'Un dato incompleto deja su total y razón sin calcular; no se convierte en cero.')
    st.caption('Las métricas de peso se visualizan en toneladas métricas (t): peso de origen en kg ÷ 1,000. '
               'Las brechas no prueban por sí solas quiebre de stock ni responsabilidad de un área.')
    total = summary(selected, ['Total']).iloc[0]
    if section == 'Control de fugas':
        columns = st.columns(6)
        for cell, key, label in zip(columns[:4], ['gmv_ingresado','gmv_facturado','fuga_pre','gmv_devuelto'],
                                     ['Demanda neta','Facturado neto','Fuga prefactura','Devolución posfactura']):
            value = total[key]
            cell.metric(label, 'Sin base completa' if pd.isna(value) else f'S/ {value:,.2f}')
        for cell, key, label in zip(columns[4:], ['kg_facturado','kg_devuelto'], ['Peso facturado','Peso devuelto']):
            value = total[key]
            cell.metric(label, 'Sin base completa' if pd.isna(value) else f'{value / 1_000:,.3f} t')
        display_table(summary(selected, ['canal'])[['canal','tasa_facturacion','tasa_pre',
                                                   'tasa_devolucion','gmv_entregado','kg_facturado','kg_devuelto']])
        st.caption('Conversión USD: dividir los importes en soles entre TC_FIJO = 3.396. '
                   'No se calcula OTIF sin fecha comprometida y evidencia de entrega.')
    elif section == 'Canales':
        comparison = summary(selected, ['canal'])
        display_table(comparison[['canal','pedidos_facturados','clientes','gmv_facturado',
                                  'kg_facturado','drop_kg','ticket','densidad','tasa_devolucion']])
        comparison = comparison.assign(toneladas_por_pedido=comparison.drop_kg / 1_000)
        show_chart(px.scatter(comparison, x='toneladas_por_pedido', y='ticket', color='canal',
                              labels={'toneladas_por_pedido':'Toneladas por pedido', 'ticket':'S/ por pedido'}))
    elif section == 'Rutas':
        routes = summary(selected, ['zona','ruta','canal'])
        ranking = st.selectbox('Ordenar rutas por', ['kg_facturado','pedidos_facturados','gmv_facturado'],
                               format_func={'kg_facturado':'Toneladas facturadas','pedidos_facturados':'Pedidos facturados',
                                            'gmv_facturado':'Venta neta modelada'}.get, key='operation_ranking')
        display_table(routes.sort_values(ranking, ascending=False).head(20)[
            ['zona','ruta','canal','pedidos_facturados','clientes','kg_facturado','drop_kg','ticket','frecuencia']])
        routes = routes.assign(toneladas_por_pedido=routes.drop_kg / 1_000)
        show_chart(px.scatter(routes, x='pedidos_facturados', y='toneladas_por_pedido', color='ticket',
                              hover_name='ruta', labels={'pedidos_facturados':'Pedidos facturados',
                                                       'toneladas_por_pedido':'Toneladas por pedido','ticket':'S/ por pedido'}))
    else:
        st.caption('Vista pública: grupos de clientes y categorías de productos; sin identificación individual.')
        reasons = aggregate(selected['returns'], ['motivo_devol'], ['gmv_devuelto'])
        display_table(reasons.sort_values('gmv_devuelto', ascending=False))
        clients = pareto(selected['clients'].loc[selected['clients'].id_cliente.notna()],
                         'id_cliente', 'gmv_facturado')
        # Identity columns remain server-side, never passed to Streamlit/Plotly.
        cohorts = clients.groupby('ABC', observed=True).agg(Clientes=('id_cliente','nunique'),
                                                           Venta_neta_modelo=('gmv_facturado','sum')).reset_index()
        display_table(cohorts)
        categories = aggregate(selected['skus'], ['categoria_sku','marca_sku'], ['fuga_pre','gmv_devuelto'])
        display_table(categories.sort_values('fuga_pre', ascending=False).head(20))
