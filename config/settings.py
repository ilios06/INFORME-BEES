from __future__ import annotations

from datetime import date


APP_NAME = "Conciliacion comercial BEES"
RECENT_WINDOW_CALENDAR_MONTHS = 3
DATA_CACHE_TTL_SECONDS = 60 * 60

PALETTE = {
    "canvas": "#0D1117",
    "surface": "#141A23",
    "card": "#1B212C",
    "primary": "#7C5CFF",
    "secondary": "#2D8CFF",
    "positive": "#22C55E",
    "negative": "#EF4444",
    "text": "#F5F7FA",
    "muted": "#A1A7B3",
    "border": "#2A313C",
}

CONCILIATION_COLUMNS = (
    "ID_Pedido_Ingresado", "SKU_Material_Ingresado", "Columna_AE_Zpedidos",
    "Zona_OfVta", "Fecha_Ingreso", "Valor_Neto_Ingresado", "Impuestos_Ingresados",
    "TOTAL", "Cantidad_Ingresada", "Peso_Ingresado", "UM_Comercial", "Codigo_Cliente",
    "CN_VA05", "Resultado_Cruce_Col_I", "Tipo_Pedido", "ID_Factura_Final",
    "SKU_Facturado", "Valor_Neto_Facturado", "Fecha_Facturacion", "Cantidad_Facturada",
    "Peso_Facturado", "Cantidad_Devuelta", "Cantidad_Devuelta_UM_Comercial",
    "Tipo_Devolucion", "Fuente_Conversion_Devolucion", "Valor_Neto_Devuelto",
    "Impuesto_Devuelto", "Total_Devuelto", "Saldo_Total_Pedido",
    "Fuente_Precio_Devuelto", "Peso_Neto_Devuelto", "Peso_Bruto_Devuelto",
    "Fuente_Peso_Devuelto", "Motivo_Devolucion",
)

NUMERIC_COLUMNS = (
    "Valor_Neto_Ingresado", "Impuestos_Ingresados", "TOTAL", "Cantidad_Ingresada",
    "Peso_Ingresado", "Valor_Neto_Facturado", "Cantidad_Facturada", "Peso_Facturado",
    "Cantidad_Devuelta", "Cantidad_Devuelta_UM_Comercial", "Valor_Neto_Devuelto",
    "Impuesto_Devuelto", "Total_Devuelto", "Saldo_Total_Pedido", "Peso_Neto_Devuelto",
    "Peso_Bruto_Devuelto",
)

SOURCE_SECRET_KEYS = {
    "general": "general_spreadsheet_id",
    "recent": "recent_spreadsheet_id",
    "master": "master_sku_spreadsheet_id",
}


def recent_window_start(today: date) -> date:
    """First day of the current calendar month plus the two preceding months."""
    offset = today.year * 12 + today.month - RECENT_WINDOW_CALENDAR_MONTHS
    return date(offset // 12, offset % 12 + 1, 1)
