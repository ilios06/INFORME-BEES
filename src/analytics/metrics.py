from __future__ import annotations

import pandas as pd


def safe_rate(numerator: float, denominator: float) -> float:
    return 0.0 if not denominator else numerator / denominator


def funnel_metrics(frame: pd.DataFrame) -> dict[str, float | int]:
    orders = int(frame["ID_Pedido_Ingresado"].nunique())
    invoiced = int(frame.loc[frame["has_invoice"], "ID_Pedido_Ingresado"].nunique())
    delivered = int(frame.loc[frame["Saldo_Total_Pedido"].fillna(0) > 0, "ID_Pedido_Ingresado"].nunique())
    returned = int(frame.loc[frame["is_return"], "ID_Pedido_Ingresado"].nunique())
    return {
        "orders": orders,
        "invoiced_orders": invoiced,
        "delivered_orders": delivered,
        "returned_orders": returned,
        "gross_entered": float(frame["TOTAL"].sum(min_count=1) or 0),
        "final_value": float(frame["Saldo_Total_Pedido"].sum(min_count=1) or 0),
        "invoice_rate": safe_rate(invoiced, orders),
        "delivery_rate": safe_rate(delivered, invoiced),
        "final_conversion_rate": safe_rate(delivered, orders),
    }


def quality_metrics(frame: pd.DataFrame) -> dict[str, int]:
    return {
        "rows": len(frame),
        "orders": int(frame["ID_Pedido_Ingresado"].nunique()),
        "missing_master_rows": int(frame["sku_master_status"].eq("SIN_MAESTRO").sum()),
        "invalid_ingress_date_rows": int(frame["Fecha_Ingreso_DT"].isna().sum()),
        "source_numeric_missing": int(frame.filter(regex="__missing_source$").sum().sum()),
        "ac_nonzero_multi_line_orders": int(
            (frame.loc[frame["Saldo_Total_Pedido"].fillna(0) != 0]
             .groupby("ID_Pedido_Ingresado").size() > 1).sum()
        ),
    }
