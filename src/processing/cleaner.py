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
        frame[column] = normalized_series(frame[column])
    for column in NUMERIC_COLUMNS:
        frame[f"{column}__missing_source"] = normalized_series(frame[column]).eq('')
        parsed = parse_regional_series(frame[column])
        frame[f"{column}__invalid_format"] = ~frame[f"{column}__missing_source"] & parsed.isna()
        frame[column] = parsed

    # The source contract is D/MM/AAAA (single-digit days are valid).
    frame["Fecha_Ingreso_DT"] = pd.to_datetime(frame["Fecha_Ingreso"], format="%d/%m/%Y", errors="coerce")
    frame["Fecha_Facturacion_DT"] = pd.to_datetime(frame["Fecha_Facturacion"], format="%d/%m/%Y", errors="coerce")
    frame["source_name"] = source_name
    frame["source_row"] = range(2, len(frame) + 2)
    frame["has_invoice"] = ~frame["ID_Factura_Final"].str.lower().isin({"", "0", "0.0"})
    frame["is_promotional"] = (frame["Cantidad_Ingresada"].fillna(0) > 0) & (frame["Valor_Neto_Ingresado"].fillna(0) <= 0)
    frame["Canal_UI"] = frame["Tipo_Pedido"].map({"GENERAL": "COSTEÑO", "PEDIDO BEES": "BEES"}).fillna(frame["Tipo_Pedido"])
    frame["Zona_OfVta_Clean"] = fold_series(frame["Zona_OfVta"]).str.upper()
    frame["Ruta_Final"] = frame["Columna_AE_Zpedidos"].replace("", "SIN_RUTA")

    warnings: list[str] = []
    invalid_dates = int(frame["Fecha_Ingreso_DT"].isna().sum())
    if invalid_dates:
        warnings.append(f"{source_name}: {invalid_dates:,} filas con Fecha_Ingreso invalida.")
    return frame, warnings


def normalized_series(series):
    text = series.astype('string').fillna('').str.strip()
    return text.mask(text.str.lower().isin(['nan','none','<na>']), '')


def fold_series(series):
    return normalized_series(series).str.lower().str.normalize('NFD').str.replace('[\u0300-\u036f]', '', regex=True)


def parse_regional_series(series):
    text = normalized_series(series).str.replace('\u00a0', '', regex=False).str.replace(' ', '', regex=False)
    negative = text.str.startswith('(') & text.str.endswith(')')
    text = text.mask(negative, text.str.slice(1,-1)).str.replace(r'^(S/|\$)', '', regex=True)
    both = text.str.contains(',', regex=False) & text.str.contains('.', regex=False)
    comma_last = text.str.rfind(',').gt(text.str.rfind('.'))
    text = text.mask(both & comma_last, text.str.replace('.', '', regex=False))
    text = text.mask(both & ~comma_last, text.str.replace(',', '', regex=False))
    parsed = pd.to_numeric(text.str.replace(',', '.', regex=False), errors='coerce').astype(float)
    return parsed.mask(negative, -parsed)
