"""Pure vectorized metrics. No row UDFs, implicit taxes, or distinct rollups."""
import numpy as np
import pandas as pd

DIMENSIONS = ['fecha_pedido', 'region', 'zona', 'ruta', 'canal']
MEASURES = ['gmv_ingresado', 'gmv_facturado', 'gmv_devuelto', 'gmv_entregado',
            'fuga_pre', 'kg_ingresado', 'kg_facturado', 'kg_devuelto', 'kg_fuga_pre',
            'cant_ingresada', 'cant_facturada', 'cant_devuelta']


def divide(numerator, denominator):
    if isinstance(denominator, pd.Series):
        return numerator / denominator.where(denominator.ne(0))
    return numerator / denominator if pd.notna(denominator) and denominator != 0 else np.nan


def number(series):
    # Explicit contract: decimal point or decimal comma, no thousands separators.
    text = series.astype('string').str.strip().replace('', pd.NA)
    value = pd.to_numeric(text.str.replace(',', '.', regex=False), errors='coerce')
    if (text.notna() & value.isna()).any():
        raise ValueError(f'Formato numérico inválido en {series.name}. Use números sin separador de miles.')
    return value.astype(float)


def normalize(raw):
    required = ['id_pedido', 'id_cliente', 'id_sku', 'fecha_pedido', 'canal',
                'region', 'zona', 'ruta', 'cant_ingresada', 'cant_facturada',
                'cant_devuelta', 'precio_neto', 'peso_unit_kg']
    missing = sorted(set(required) - set(raw.columns))
    if missing:
        raise ValueError('Columnas requeridas: ' + ', '.join(missing))
    d = raw.copy()
    for col in ['id_pedido', 'id_cliente', 'id_sku', 'canal', 'region', 'zona', 'ruta']:
        d[col] = d[col].astype('string').str.strip().replace('', pd.NA)
        if d[col].isna().any():
            raise ValueError(f'Identificador o dimensión vacía: {col}')
    d['canal'] = d['canal'].replace({'GENERAL': 'COSTEÑO', 'PEDIDO BEES': 'BEES'})
    d['fecha_pedido'] = pd.to_datetime(d['fecha_pedido'], format='%Y-%m-%d', errors='coerce').dt.normalize()
    if d['fecha_pedido'].isna().any():
        raise ValueError('Fecha de pedido inválida; use YYYY-MM-DD.')
    for col in ['cant_ingresada', 'cant_facturada', 'cant_devuelta', 'precio_neto', 'peso_unit_kg']:
        d[col] = number(d[col])
        if d[col].lt(0).any():
            raise ValueError(f'Valores negativos en {col}; requieren revisión de origen.')
    if (d.cant_devuelta > d.cant_facturada).any():
        raise ValueError('Cantidad devuelta superior a facturada.')
    for col in ['categoria_sku', 'marca_sku', 'motivo_devol']:
        if col not in d:
            d[col] = pd.NA
        d[col] = d[col].astype('string').str.strip().replace('', pd.NA).fillna('SIN_CLASIFICAR')
    if 'id_linea' in d and d[['id_pedido', 'id_linea']].duplicated().any():
        raise ValueError('Pedido + línea repetidos. Revisar posición/factura antes de consolidar.')
    d['sobre_facturado'] = d.cant_facturada > d.cant_ingresada
    # Optional invoice evidence preserves zero-value commercial/promotional lines.
    if 'id_factura' in d:
        invoice = d.id_factura.astype('string').str.strip().replace('', pd.NA)
        d['facturado'] = invoice.notna() & ~invoice.isin(['0', '0.0'])
        if ((~d.facturado) & d.cant_facturada.gt(0)).any():
            raise ValueError('Cantidad facturada positiva sin factura válida.')
    else:
        d['facturado'] = d.cant_facturada.gt(0)
    d['devuelto'] = d.cant_devuelta.gt(0)
    for stage, quantity in [('ingresado','cant_ingresada'), ('facturado','cant_facturada'), ('devuelto','cant_devuelta')]:
        d['gmv_' + stage] = d[quantity] * d.precio_neto
        d['kg_' + stage] = d[quantity] * d.peso_unit_kg
    d['gmv_entregado'] = d.gmv_facturado - d.gmv_devuelto
    gap = (d.cant_ingresada - d.cant_facturada).clip(lower=0)
    d['fuga_pre'] = gap * d.precio_neto
    d['kg_fuga_pre'] = gap * d.peso_unit_kg
    for col in ['canal','region','zona','ruta','categoria_sku','marca_sku']:
        d[col] = d[col].astype('category')
    return d


def aggregate(d, keys, measures=MEASURES):
    grouped = d.groupby(keys, observed=True, dropna=False)
    sums = grouped[measures].sum(min_count=1)
    # Missing values cannot silently become plausible partial totals.
    sums = sums.where(grouped[measures].count().eq(grouped.size(), axis=0))
    return sums.reset_index()


def layers(d):
    cube = aggregate(d, DIMENSIONS)
    orders = d[DIMENSIONS + ['id_pedido','facturado','devuelto']].groupby(
        DIMENSIONS + ['id_pedido'], observed=True, dropna=False)[['facturado','devuelto']].max().reset_index()
    customers = d.loc[d.facturado, DIMENSIONS + ['id_cliente','id_sku']].drop_duplicates()
    returns = aggregate(d.loc[d.devuelto], DIMENSIONS + ['id_cliente','motivo_devol'])
    skus = aggregate(d, DIMENSIONS + ['id_sku','categoria_sku','marca_sku'])
    clients = aggregate(d, DIMENSIONS + ['id_cliente'])
    return {'cube':cube, 'orders':orders, 'customers':customers, 'returns':returns,
            'skus':skus, 'clients':clients}


def select(data, start, end, filters):
    result = {}
    for key, frame in data.items():
        mask = frame.fecha_pedido.between(pd.Timestamp(start), pd.Timestamp(end))
        for col, values in filters.items():
            if values:
                mask &= frame[col].isin(values)
        result[key] = frame.loc[mask]
    return result


def summary(data, keys):
    cube = data['cube'].assign(Total='Selección')
    orders = data['orders'].assign(Total='Selección')
    customers = data['customers'].assign(Total='Selección')
    sums = aggregate(cube, keys).set_index(keys)
    sums['pedidos'] = orders.groupby(keys, observed=True).id_pedido.nunique()
    sums['pedidos_facturados'] = orders.loc[orders.facturado].groupby(keys, observed=True).id_pedido.nunique()
    sums['clientes'] = customers.groupby(keys, observed=True).id_cliente.nunique()
    sums[['pedidos_facturados','clientes']] = sums[['pedidos_facturados','clientes']].fillna(0)
    for name, numerator, denominator, scale in [
        ('tasa_facturacion','gmv_facturado','gmv_ingresado',100),
        ('tasa_devolucion','gmv_devuelto','gmv_facturado',100),
        ('tasa_pre','fuga_pre','gmv_ingresado',100),
        ('tasa_devolucion_kg','kg_devuelto','kg_facturado',100),
        ('drop_kg','kg_facturado','pedidos_facturados',1),
        ('ticket','gmv_facturado','pedidos_facturados',1),
        ('densidad','gmv_facturado','kg_facturado',1),
        ('frecuencia','pedidos_facturados','clientes',1)]:
        sums[name] = divide(sums[numerator], sums[denominator]) * scale
    return sums.reset_index()


def pareto(frame, key, metric):
    d = aggregate(frame, [key], [metric]).sort_values(metric, ascending=False, na_position='last')
    total = d[metric].sum(min_count=1) if d[metric].notna().all() else np.nan
    d['porcentaje_acumulado'] = divide(d[metric].cumsum(), total) * 100
    d['ABC'] = np.select([d.porcentaje_acumulado.le(80), d.porcentaje_acumulado.le(95),
                         d.porcentaje_acumulado.notna()], ['A','B','C'], default='SIN_BASE')
    return d
