from __future__ import annotations

import unicodedata

import pandas as pd

from config.settings import CONCILIATION_COLUMNS, NUMERIC_COLUMNS


class SchemaError(ValueError):
    pass


def normalized_text(value: object) -> str:
    text = "" if pd.isna(value) else str(value).strip()
    return "" if text.lower() in {"nan", "none", "<na>"} else text


def fold_text(value: object) -> str:
    return "".join(
        char for char in unicodedata.normalize("NFD", normalized_text(value).lower())
        if unicodedata.category(char) != "Mn"
    )


def clean_conciliation(raw: pd.DataFrame, source_name: str) -> tuple[pd.DataFrame, list[str]]:
    missing = [column for column in CONCILIATION_COLUMNS if column not in raw.columns]
    if missing:
        raise SchemaError("Columnas obligatorias ausentes: " + ", ".join(missing))

    frame = raw.loc[:, CONCILIATION_COLUMNS].copy()
    text_columns = set(CONCILIATION_COLUMNS).difference(NUMERIC_COLUMNS)
    for column in text_columns:
        frame[column] = frame[column].map(normalized_text)
    for column in NUMERIC_COLUMNS:
        frame[f"{column}__missing_source"] = frame[column].map(lambda value: normalized_text(value) == "")
        frame[column] = pd.to_numeric(frame[column], errors="coerce")

    frame["Fecha_Ingreso_DT"] = pd.to_datetime(frame["Fecha_Ingreso"], dayfirst=True, errors="coerce")
    frame["Fecha_Facturacion_DT"] = pd.to_datetime(frame["Fecha_Facturacion"], dayfirst=True, errors="coerce")
    frame["source_name"] = source_name
    frame["source_row"] = range(2, len(frame) + 2)
    frame["has_invoice"] = ~frame["ID_Factura_Final"].map(fold_text).isin({"", "0", "0.0"})
    frame["is_promotional"] = (frame["Cantidad_Ingresada"].fillna(0) > 0) & (frame["Valor_Neto_Ingresado"].fillna(0) <= 0)
    frame["Canal_UI"] = frame["Tipo_Pedido"].map({"GENERAL": "COSTEÑO", "PEDIDO BEES": "BEES"}).fillna(frame["Tipo_Pedido"])
    frame["Zona_OfVta_Clean"] = frame["Zona_OfVta"].map(fold_text).str.upper()
    frame["Ruta_Final"] = frame["Columna_AE_Zpedidos"].map(normalized_text).replace("", "SIN_RUTA")

    warnings: list[str] = []
    invalid_dates = int(frame["Fecha_Ingreso_DT"].isna().sum())
    if invalid_dates:
        warnings.append(f"{source_name}: {invalid_dates:,} filas con Fecha_Ingreso invalida.")
    return frame, warnings
