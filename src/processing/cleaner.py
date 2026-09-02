from __future__ import annotations

import unicodedata
from numbers import Number

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


def parse_regional_number(value: object) -> float:
    """Parse Sheets values using either decimal comma or decimal point.

    Google Sheets returns the commercial source as text with decimal commas
    (for example ``57,992838``). A blank remains missing; malformed nonblank
    values remain NaN so quality controls can surface them instead of treating
    them as zero.
    """
    if isinstance(value, Number) and not isinstance(value, bool):
        return float(value)

    text = normalized_text(value).replace("\u00a0", "").replace(" ", "")
    if not text:
        return float("nan")

    negative_parentheses = text.startswith("(") and text.endswith(")")
    if negative_parentheses:
        text = text[1:-1]
    text = text.removeprefix("S/").removeprefix("$")

    if "," in text and "." in text:
        if text.rfind(",") > text.rfind("."):
            text = text.replace(".", "").replace(",", ".")
        else:
            text = text.replace(",", "")
    elif "," in text:
        text = text.replace(",", ".")

    parsed = pd.to_numeric(text, errors="coerce")
    if pd.isna(parsed):
        return float("nan")
    return -float(parsed) if negative_parentheses else float(parsed)


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
        parsed = frame[column].map(parse_regional_number)
        frame[f"{column}__invalid_format"] = ~frame[f"{column}__missing_source"] & parsed.isna()
        frame[column] = parsed

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
