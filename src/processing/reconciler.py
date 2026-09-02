from __future__ import annotations

import json
from datetime import date
from pathlib import Path

import pandas as pd

from config.settings import recent_window_start
from src.processing.cleaner import fold_text, normalized_text


def combine_general_and_recent(general: pd.DataFrame, recent: pd.DataFrame, today: date) -> pd.DataFrame:
    """Partition by calendar date: historical before 3M, recent on/after 3M."""
    cutoff = pd.Timestamp(recent_window_start(today))
    older_general = general.loc[general["Fecha_Ingreso_DT"] < cutoff].copy()
    current_recent = recent.loc[recent["Fecha_Ingreso_DT"] >= cutoff].copy()
    return pd.concat([older_general, current_recent], ignore_index=True)


def classify_return_reason(reason: object, mapping: dict[str, list[str]]) -> str:
    candidate = fold_text(reason)
    if not candidate:
        return "SIN_DEVOLUCION"
    for category, patterns in mapping.items():
        if any(pattern in candidate for pattern in patterns):
            return category
    return "OTROS_POR_REVISAR"


def apply_business_rules(frame: pd.DataFrame, mapping_path: Path) -> pd.DataFrame:
    mapping = json.loads(mapping_path.read_text(encoding="utf-8"))
    result = frame.copy()
    result["Motivo_Devolucion_Categoria"] = result["Motivo_Devolucion"].map(
        lambda value: classify_return_reason(value, mapping)
    )
    result["is_return"] = result["Motivo_Devolucion_Categoria"].ne("SIN_DEVOLUCION")
    result["Saldo_Total_Pedido"] = result["Saldo_Total_Pedido"].fillna(0)
    result["Estado_Conciliacion"] = "ENTREGADO_TOTAL"
    result.loc[~result["has_invoice"], "Estado_Conciliacion"] = "NO_FACTURADO"
    result.loc[result["has_invoice"] & (result["Saldo_Total_Pedido"] <= 0), "Estado_Conciliacion"] = "SIN_VALOR_FINAL"
    result.loc[
        result["has_invoice"] & (result["Saldo_Total_Pedido"] > 0) & result["is_return"],
        "Estado_Conciliacion",
    ] = "ENTREGADO_PARCIAL"
    return result


def merge_master(frame: pd.DataFrame, master: pd.DataFrame) -> pd.DataFrame:
    required = {"Material", "Marca", "Categoria Cuota"}
    missing = required.difference(master.columns)
    if missing:
        raise ValueError("Maestro SKU incompleto: " + ", ".join(sorted(missing)))
    catalog = master.loc[:, ["Material", "Marca", "Categoria Cuota"]].copy()
    catalog["Material"] = catalog["Material"].map(normalized_text)
    duplicated = catalog["Material"].duplicated(keep=False)
    if duplicated.any():
        sample = ", ".join(catalog.loc[duplicated, "Material"].head(5))
        raise ValueError(f"Maestro SKU no es unico; ejemplo: {sample}")
    result = frame.merge(catalog, how="left", left_on="SKU_Material_Ingresado", right_on="Material", validate="m:1")
    result["sku_master_status"] = result["Material"].notna().map({True: "EN_MAESTRO", False: "SIN_MAESTRO"})
    result["Marca"] = result["Marca"].map(normalized_text).replace("", "SIN_MAESTRO").fillna("SIN_MAESTRO")
    result["Categoria Cuota"] = result["Categoria Cuota"].map(normalized_text).replace("", "SIN_MAESTRO").fillna("SIN_MAESTRO")
    return result
